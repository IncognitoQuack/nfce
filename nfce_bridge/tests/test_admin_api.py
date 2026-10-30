"""The desk's admin API (bridge/admin_api.py): local only, secret only, one account at a time, every call audited."""
import json
from datetime import datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bridge.admin_api import register
from bridge.providers import IST
from bridge.store import Store

SECRET = "desk-" + "y" * 24


class FakeAccount:
    def __init__(self, name, sids):
        self.name, self.strategy, self.paused = name, "base", False
        self.positions = {s: SimpleNamespace(sid=s, symbol=f"{s} PE", lots=2, rem_lots=2, entry=10.0,
                                             opened="2026-10-28T10:18:00+05:30", hits=0) for s in sids}
        self.closed = []

    def close(self, now, which, reason):
        ps = list(self.positions) if which == "all" else [which]
        self.closed += [(p, reason) for p in ps]
        for p in ps:
            self.positions.pop(p)
        return [f"{self.name}: sold {p} ({reason})" for p in ps]

    def set_paused(self, on):
        self.paused = on


def setup(tmp_path, secret=SECRET, hosts=frozenset({"testclient"})):
    halted = {"v": False}
    b = SimpleNamespace(store=Store(tmp_path / "a.db"),
                        accounts=[FakeAccount("5L", ["S1", "S2"]), FakeAccount("WIDE", ["S1"])],
                        risk=SimpleNamespace(halted=lambda: halted["v"], set_halted=lambda v: halted.update(v=v)),
                        now=lambda: datetime(2026, 10, 28, 11, 0, tzinfo=IST))
    app = FastAPI()
    register(app, b, local_hosts=set(hosts), secret_fn=lambda: secret)
    return b, TestClient(app), halted


def events(b):
    return [json.loads(r[0]) for r in b.store.db.execute("SELECT raw FROM events WHERE source='admin' ORDER BY id")]


def test_refused_without_the_secret_from_elsewhere_or_when_off(tmp_path):
    b, c, _ = setup(tmp_path)
    assert c.get("/admin/positions").status_code == 403
    assert c.get("/admin/positions", headers={"X-Admin-Secret": "wrong"}).status_code == 403
    _, c2, _ = setup(tmp_path, hosts={"127.0.0.1"})                      # a LAN client is never local
    assert c2.get("/admin/positions", headers={"X-Admin-Secret": SECRET}).status_code == 403
    _, c3, _ = setup(tmp_path, secret="")
    assert c3.get("/admin/positions", headers={"X-Admin-Secret": ""}).status_code == 503
    assert events(b) == []


def test_close_hits_one_account_only_and_is_audited_as_manual(tmp_path):
    # Telegram's /close <n> closes position n in EVERY account; the desk must not
    b, c, _ = setup(tmp_path)
    h = {"X-Admin-Secret": SECRET}
    r = c.post("/admin/action", headers=h, json={"action": "close", "acct": "5L", "sid": "S1", "device": "phone"})
    assert r.status_code == 200 and r.json()["result"] == ["5L: sold S1 (MANUAL close (desk))"]
    five, wide = b.accounts
    assert list(five.positions) == ["S2"] and list(wide.positions) == ["S1"]          # WIDE's S1 untouched
    ev = events(b)
    assert ev[0] == {"cmd": "close", "acct": "5L", "sid": "S1", "via": "desk", "device": "phone"}
    assert ev[1]["result"] == ["5L: sold S1 (MANUAL close (desk))"]
    assert c.post("/admin/action", headers=h, json={"action": "close", "acct": "5L", "sid": "S1"}).status_code == 404
    assert c.post("/admin/action", headers=h, json={"action": "close", "acct": "XX", "sid": "S1"}).status_code == 404
    assert c.post("/admin/action", headers=h, json={"action": "short", "acct": "5L"}).status_code == 400
    assert c.post("/admin/action", headers=h, json={"action": "buy", "acct": "5L"}).status_code == 403   # strategy acct


def test_close_all_pause_and_halt(tmp_path):
    b, c, halted = setup(tmp_path)
    h = {"X-Admin-Secret": SECRET}
    c.post("/admin/action", headers=h, json={"action": "close_all", "acct": "5L"})
    assert b.accounts[0].positions == {} and list(b.accounts[1].positions) == ["S1"]
    c.post("/admin/action", headers=h, json={"action": "pause", "acct": "WIDE"})
    assert b.accounts[1].paused and not b.accounts[0].paused
    c.post("/admin/action", headers=h, json={"action": "halt"})
    assert halted["v"] and all(a.paused for a in b.accounts)
    pos = c.get("/admin/positions", headers=h).json()
    assert pos["halted"] is True and pos["accounts"][1]["positions"][0]["sid"] == "S1"
    c.post("/admin/action", headers=h, json={"action": "unhalt"})
    assert not halted["v"] and not any(a.paused for a in b.accounts)


def test_a_real_account_closes_through_the_api_with_a_manual_fill(settings):
    # end to end with the real Account: buy via consider(), sell via the desk's admin API at the live bid
    from bridge.account import Account
    from conftest import FakeTelegram
    from test_account import T, Prov, leg
    prov = Prov()
    halted = {"v": False}
    b = SimpleNamespace(store=Store(settings.db_path), provider=prov, tg=FakeTelegram(),
                        _fresh=lambda q, now, exchange_time=True: True,
                        risk=SimpleNamespace(halted=lambda: halted["v"], set_halted=lambda v: halted.update(v=v)),
                        now=lambda: T)
    a = Account(b, 200_000, risk_pct=1.0, daily_loss_pct=3.0, max_open=4, name="5L")
    b.accounts = [a]
    assert "bought 2 lots" in a.consider(T, "s1", leg(), "SPOT", 1, [23070, 23130, 23160, 23190], 0.0, "test")
    prov.q = {"OPT": (58, 57.0, 58.0)}
    app = FastAPI()
    register(app, b, local_hosts={"testclient"}, secret_fn=lambda: SECRET)
    r = TestClient(app).post("/admin/action", headers={"X-Admin-Secret": SECRET},
                             json={"action": "close", "acct": "5L", "sid": "s1", "device": "test"})
    assert r.status_code == 200 and "MANUAL close (desk)" in r.json()["result"][0]
    assert not a.positions
    fill = b.store.db.execute("SELECT action, lots, price, reason FROM account_fills WHERE sid='s1' AND action='SELL'").fetchone()
    assert fill == ("SELL", 2, 57.0, "MANUAL close (desk)")


def test_the_secret_is_read_from_env_not_from_the_frozen_config(tmp_path):
    from bridge.admin_api import env_secret
    env = tmp_path / ".env"
    env.write_text("WEBHOOK_SECRET=a\nDESK_ADMIN_SECRET=xyz\n")
    assert env_secret(env) == "xyz" and env_secret(tmp_path / "missing") == ""
