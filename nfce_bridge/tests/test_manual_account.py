"""The owner's manual account MAN (strategy "manual"): no automatic entries; desk buys/sells only; 15:15 square-off."""
from datetime import timedelta
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bridge.account import Account
from bridge.admin_api import register
from test_account import LV, T, acct, leg  # noqa: F401  (acct is a fixture)


def man(acct, strategy="manual", name="MAN"):  # noqa: F811
    a, prov = acct
    return Account(a.b, 500_000, name=name, strategy=strategy), prov


def test_manual_account_takes_no_signals(acct):  # noqa: F811
    m, _ = man(acct)
    assert m.consider(T, "s1", leg(), "SPOT", 1, LV, 0.0, "x") == "" and not m.positions


def test_manual_buy_hours_cash_and_no_automatic_exits(acct):  # noqa: F811
    m, prov = man(acct)
    assert "09:15–15:10 only" in m.manual_buy(T.replace(hour=9, minute=10), leg(), 2, "SPOT", 1)
    assert "cash" in m.manual_buy(T, leg(ask=60.0), 200, "SPOT", 1)                       # 200 x 65 x 60 > 5 L
    out = m.manual_buy(T, leg(ask=60.0), 2, "SPOT", 1)
    assert "bought 2 lots" in out and m.cash == 500_000 - 2 * 65 * 60
    sid = next(iter(m.positions))
    prov.q = {"OPT": (20, 19.0, 20.0), "SPOT": (1.0, None, None)}                     # premium and spot collapse
    m.on_tick(T + timedelta(minutes=40))
    assert sid in m.positions                                                           # no stop, no hard stop
    prov.q = {"OPT": (500, 499.0, 500.0), "SPOT": (99999.0, None, None)}
    m.on_tick(T + timedelta(minutes=41))
    assert sid in m.positions                                                           # no target either
    m.on_tick(T.replace(hour=15, minute=15))
    assert not m.positions                                                              # 15:15 square-off applies
    last = m.store.db.execute("SELECT reason FROM account_fills WHERE acct='MAN' ORDER BY id DESC LIMIT 1").fetchone()
    assert last[0] == "15:15 square-off"


def test_manual_sell_part_then_the_rest(acct):  # noqa: F811
    m, prov = man(acct)
    m.manual_buy(T, leg(ask=60.0), 3, "SPOT", -1)
    sid = next(iter(m.positions))
    prov.q = {"OPT": (64, 63.0, 64.0)}
    assert "sold 1 lot" in m.manual_sell(T, sid, 1)[0] and m.positions[sid].rem_lots == 2
    assert "sold 2 lots" in m.manual_sell(T, sid)[0] and not m.positions
    assert "no open position" in m.manual_sell(T, sid)[0]


def test_api_buys_only_in_the_manual_account(acct, monkeypatch):  # noqa: F811
    m, prov = man(acct)
    base, _ = man(acct, "base", "5L")
    b = m.b
    b.accounts, b.now = [base, m], (lambda: T)
    b.s = SimpleNamespace(underlyings={"NIFTY": "SPOT"})
    b.stocks = SimpleNamespace(universe=[{"symbol": "TCS", "equity_key": "TCSK", "lot": 175}])
    b.risk = SimpleNamespace(halted=lambda: False, set_halted=lambda v: None)
    prov.q = {"SPOT": (23100.0, None, None)}
    import bridge.options as opts
    picked = {}

    def fake_pick(provider, key, und, spot, side, entry, sl, targets, units, today):
        picked.update(key=key, und=und, side=side, units=units)
        return leg(ask=60.0, und=und, key="OPTX", units=units)
    monkeypatch.setattr(opts, "pick_leg", fake_pick)
    app = FastAPI()
    register(app, b, local_hosts={"testclient"}, secret_fn=lambda: "S" * 30)
    c, h = TestClient(app), {"X-Admin-Secret": "S" * 30}
    r = c.post("/admin/action", headers=h, json={"action": "buy", "acct": "5L", "underlying": "NIFTY", "side": 1, "lots": 1})
    assert r.status_code == 403 and not base.positions                     # strategy accounts never take manual buys
    r = c.post("/admin/action", headers=h, json={"action": "buy", "acct": "MAN", "underlying": "nifty", "side": -1, "lots": 2})
    assert r.status_code == 200 and "bought 2 lots" in r.json()["result"][0]
    assert picked == {"key": "SPOT", "und": "NIFTY", "side": -1, "units": 65}
    assert c.post("/admin/action", headers=h, json={"action": "buy", "acct": "MAN", "underlying": "XYZ",
                                                   "side": 1, "lots": 1}).status_code == 404
    assert c.post("/admin/action", headers=h, json={"action": "buy", "acct": "MAN", "underlying": "TCS",
                                                   "side": 1, "lots": 0}).status_code == 400
    assert c.get("/admin/universe", headers=h).json() == {"underlyings": ["NIFTY", "TCS"]}


def test_two_manual_buys_in_the_same_second_keep_separate_ids(acct):  # noqa: F811
    m, _ = man(acct)
    m.manual_buy(T, leg(ask=10.0), 1, "SPOT", 1)
    m.manual_buy(T, leg(ask=10.0), 1, "SPOT", 1)
    assert len(m.positions) == 2 and all(p.rem_lots == 1 for p in m.positions.values())


def test_eod_reviews_the_owners_manual_trades(acct, monkeypatch, tmp_path):  # noqa: F811
    from ops import desk, eod_report
    m, prov = man(acct)
    monkeypatch.setattr(desk, "_strategies", lambda: {"5L": "base", "MAN": "manual"})
    m.store.db.execute("CREATE TABLE IF NOT EXISTS paper_trades (id INTEGER PRIMARY KEY, book TEXT, sid TEXT, opened TEXT, "
                       "underlying TEXT, side INTEGER)")
    m.store.db.execute("INSERT INTO paper_trades (book, sid, opened, underlying, side) VALUES ('stock3m', 'x', ?, 'NIFTY', 1)",
                       ((T - timedelta(minutes=5)).isoformat(),))
    m.store.db.commit()
    m.manual_buy(T, leg(ask=60.0), 2, "SPOT", 1)
    sid = next(iter(m.positions))
    prov.q = {"OPT": (66, 65.0, 66.0)}
    m.manual_sell(T + timedelta(minutes=12), sid)
    day = T.date().isoformat()
    r = eod_report.manual_review(m.store.db, day, stream=tmp_path / "none.db")
    t = r["trades"][0]
    assert (t["acct"], t["lots"], t["held_min"], t["exit"]) == ("MAN", 2, 12, "MANUAL sell (desk)")
    assert t["net"] > 0 and t["signal"].startswith("stock3m") and r["overrides"] == []
