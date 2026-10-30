"""The bot without an assistant (owner, 21 Oct evening): roles, plain English, admin control, unattended jobs."""
import json
from datetime import datetime, timedelta

import httpx
import pytest

from bridge.providers import IST
from bridge.telegram import Telegram
from conftest import FakeTelegram

ADMIN, USER = "900000001", "42"


class RoleTelegram(FakeTelegram):
    """FakeTelegram with roles: who is asking (reply_to) and who is admin."""

    def __init__(self):
        super().__init__()
        self.reply_to = None
        self.admins = {ADMIN}
        self.chat_id = USER
        self.to = []
        self.admin_sent = []
        self.users = lambda: set()
        self.muted = lambda: set()
        self.requests = []

    def is_admin(self, chat):
        return chat is None or chat in self.admins

    def known_chats(self):
        return {USER, ADMIN} | set(self.users())

    def broadcast_targets(self):
        return sorted(self.known_chats() - (set(self.muted()) - self.admins))

    def send(self, text, html=False, to=None):
        self.to.append(to)
        return super().send(text, html)

    def send_admin(self, text, html=False):
        self.admin_sent.append(text)
        return True


@pytest.fixture(autouse=True)
def _on_the_charger(monkeypatch, request):
    """Tests never read this Mac's real battery (22 Oct: it was on battery and a watchdog test failed)."""
    import bridge.bot as botmod
    if request.node.name != "test_power_status_reads_pmset":
        monkeypatch.setattr(botmod, "power_status", lambda: (True, 100))
    import bridge.preflight as pf                        # the real preflight reads the live .env and this Mac
    monkeypatch.setattr(pf, "checks", lambda: [])


@pytest.fixture
def bot_bridge(settings, clock):
    from bridge.service import Bridge
    from bridge.store import Store
    from conftest import StubProvider, make_payload
    settings.accounts = {"5L": 500_000}
    prov = StubProvider(make_payload(), clock=clock)
    tg = RoleTelegram()
    b = Bridge(settings, prov, Store(settings.db_path), tg, clock=clock)
    return b, tg


def as_(tg, chat):
    tg.reply_to = chat


def test_users_cannot_control_and_admins_can(bot_bridge):
    b, tg = bot_bridge
    as_(tg, USER)
    assert "for the admin" in b.handle_command("/pause")
    assert "for the admin" in b.handle_command("/close all")
    assert not b.risk.halted()
    assert "Admin commands" not in b.handle_command("/help")
    as_(tg, ADMIN)
    assert "Paused" in b.handle_command("/pause")
    assert b.risk.halted() and b.accounts[0].paused
    assert "Admin commands" in b.handle_command("/help")
    b.handle_command("/resume")
    assert not b.risk.halted() and not b.accounts[0].paused


def test_plain_english_questions_are_answered_and_statements_are_notes(bot_bridge):
    b, tg = bot_bridge
    as_(tg, USER)
    assert "Paper account 5L" in b.handle_command("profit?")
    assert "Today" in b.handle_command("any signals today?")
    reply = b.handle_command("Focus on Nifty 50 calls/ puts and the top 5 gainers of the day")
    assert reply.startswith("📝 Noted") and any("Message from user 42" in m for m in tg.admin_sent)
    as_(tg, ADMIN)
    assert "Paused" in b.handle_command("@admin: pause trading")      # an admin's plain request runs
    assert "for the admin" not in b.handle_command("stop trading")
    as_(tg, USER)
    assert "Paused" not in b.handle_command("pause trading")          # a user's never does


def test_dangerous_commands_need_a_confirmation_code(bot_bridge, clock):
    b, tg = bot_bridge
    from bridge.options import OptionLeg
    a = b.accounts[0]
    leg = OptionLeg("NIFTY", "NSE_FO|OPT", 25000, "CE", "2026-10-27", 99.0, 100.0, 0.5, 65, 85.0, 115, 130, 145, "")
    a.consider(clock(), "s1", leg, "NSE_INDEX|Nifty 50", 1, [24970, 25030, 25060, 25090], 0.0, "x")
    as_(tg, ADMIN)
    ask = b.handle_command("/close all")
    code = ask.split("/confirm ")[1].split()[0]
    assert a.positions and "Nothing to confirm" in b.handle_command("/confirm 0000")
    ask = b.handle_command("/close all")
    code = ask.split("/confirm ")[1].split()[0]
    out = b.handle_command(f"/confirm {code}")
    assert "closed by admin" in out and not a.positions
    code = b.handle_command("/restart").split("/confirm ")[1].split()[0]
    b.handle_command(f"/confirm {code}")
    assert b.bot.restart_requested


def test_settings_toggles_and_users(bot_bridge):
    b, tg = bot_bridge
    as_(tg, ADMIN)
    assert "risk_pct = 0.5" in b.handle_command("/set risk 0.5")
    assert "between" in b.handle_command("/set risk 9")
    assert "0.1×" in b.handle_command("/set stockrisk 0.1") and b.s.stock_signal_risk == 0.1
    b.handle_command("/toggle stocks off")
    assert b.bot.off("stocks") and not b.bot.off("index")
    b.handle_command("/adduser 555")
    assert "555" in b.bot.users() and "555" in tg.known_chats()
    as_(tg, "555")
    b.handle_command("/stop")
    assert "555" in b.bot.muted() and "555" not in tg.broadcast_targets()
    b.handle_command("/start")
    assert "555" in tg.broadcast_targets()
    as_(tg, ADMIN)
    assert "Settings" in b.handle_command("/config") and "removed" in b.handle_command("/removeuser 555")


def test_unknown_chats_become_access_requests_and_added_users_are_accepted():
    updates = {"ok": True, "result": [
        {"update_id": 1, "message": {"chat": {"id": 555, "type": "private"}, "from": {"id": 555, "first_name": "Ravi"},
                                     "text": "/start"}},
    ]}
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=updates)))
    tg = Telegram("1:x", USER, client=client, admin_chat_ids={ADMIN})
    assert tg.poll_commands() == [] and tg.requests == [("555", "Ravi", "/start")]
    tg.users = lambda: {"555"}
    assert tg.poll_commands() == ["/start"]
    assert tg.is_admin(ADMIN) and not tg.is_admin(USER) and not tg.is_admin("555")
    tg.muted = lambda: {"555", ADMIN}
    assert tg.broadcast_targets() == [USER, ADMIN]                     # admins can never be muted


def test_watchdog_alerts_after_three_minutes_and_reports_recovery(bot_bridge, clock):
    b, tg = bot_bridge
    t0 = datetime(2026, 10, 22, 10, 0, tzinfo=IST)
    problems = {"p": ["no fresh option chain for NIFTY"]}
    b.health_status = lambda: {"ok": not problems["p"], "problems": problems["p"], "last_error": None}
    import bridge.bot as botmod
    real = botmod.time.time
    try:
        botmod.time.time = lambda: 1000.0
        b.bot._watchdog(t0)
        assert not tg.admin_sent
        botmod.time.time = lambda: 1000.0 + 181
        b.bot._watchdog(t0)
        assert "no fresh option chain" in tg.admin_sent[-1]
        problems["p"] = []
        b.bot._watchdog(t0)
        assert tg.admin_sent[-1].startswith("✅ Recovered")
    finally:
        botmod.time.time = real


def test_token_watch_morning_brief_and_end_of_day(bot_bridge, clock, tmp_path):
    b, tg = bot_bridge
    b.s.provider = "upstox"
    b.s.token_file = tmp_path / "none.json"
    t = datetime(2026, 10, 22, 8, 30, tzinfo=IST)
    b.bot.tick(t)
    b.bot.tick(t + timedelta(minutes=1))
    assert sum("/login" in m for m in tg.admin_sent) == 1
    b.bot.tick(datetime(2026, 10, 22, 9, 6, tzinfo=IST))
    assert any(m.startswith("☀️ Good morning") for m in tg.sent)
    b.bot.tick(datetime(2026, 10, 22, 15, 36, tzinfo=IST))
    assert any("End of day" in m for m in tg.admin_sent)
    assert list((b.s.db_path.parent / "backups").glob("nfce_*.db"))


def test_phone_login_reads_the_code_from_the_pasted_address(bot_bridge, monkeypatch):
    from bridge import upstox_login
    b, tg = bot_bridge
    b.s.upstox_api_key, b.s.upstox_api_secret = "k", "s"
    as_(tg, ADMIN)
    assert "Send /login first" in b.handle_command("/code abc")
    msg = b.handle_command("/login")
    state = b.bot._login_state
    assert "state=" + state in msg
    with pytest.raises(upstox_login.LoginError):
        upstox_login.code_from("http://127.0.0.1:8765/callback?code=X1&state=other", state)
    got = {}
    monkeypatch.setattr(upstox_login, "exchange_code", lambda s, code: got.setdefault("code", code) and
                        datetime(2026, 10, 23, 3, 30, tzinfo=IST))
    out = b.handle_command(f"/code http://127.0.0.1:8765/callback?code=X1&state={state}")
    assert got["code"] == "X1" and "token saved" in out and b.bot._login_state is None


def test_errors_are_kept_and_a_burst_alerts_the_admin_once(bot_bridge):
    b, tg = bot_bridge
    for i in range(25):
        b._error(f"chain NIFTY: boom {i}")
    assert sum("errors in the last 10 minutes" in m for m in tg.admin_sent) == 1
    as_(tg, ADMIN)
    assert "boom 24" in b.handle_command("/errors")
    assert "Latest notes" in b.handle_command("/notes") or "No notes" in b.handle_command("/notes")


def test_strategy_accounts_are_quiet_compared_side_by_side_and_keep_their_rules(settings, clock):
    # 22 Oct evening (evidence/strategy_accounts_protocol.md): 5 accounts, only the first sends its own messages
    from bridge.service import Bridge
    from bridge.store import Store
    from conftest import StubProvider, make_payload
    settings.accounts = {"5L": 500_000, "CONC": 500_000, "WIDE": 500_000}
    settings.account_strategies = {"5L": "base", "CONC": "concentrated", "WIDE": "wide"}
    tg = RoleTelegram()
    b = Bridge(settings, StubProvider(make_payload(), clock=clock), Store(settings.db_path), tg, clock=clock)
    assert [(a.name, a.strategy, a.quiet) for a in b.accounts] == [("5L", "base", False), ("CONC", "concentrated", True),
                                                                   ("WIDE", "wide", True)]
    text = b.accounts_text()
    assert "Paper account 5L" in text and "Strategy accounts" in text and "<b>CONC</b> (concentrated)" in text
    as_(tg, ADMIN)
    b.handle_command("/set risk 0.5")
    assert b.accounts[0].risk_pct == 0.5 and b.accounts[1].risk_pct == 5.0 and b.accounts[2].risk_pct == 1.0


def test_an_admins_longer_message_goes_to_the_assistant_not_a_keyword_command(bot_bridge):
    # live 22 Oct: "check was this trade a success or not" became /today, and "check the system why it's
    # malfunctioning ... why it's making so much loss" became /account; the admin was waiting for a real answer
    b, tg = bot_bridge
    b.s.assistant_relay = True
    as_(tg, ADMIN)
    for text in ("check was this trade a success or not",
                 "check the system why it's malfunctioning fix and make it correct and why it's making so much loss"):
        assert "passed to your assistant" in b.handle_command(text)
    assert "Paper account 5L" in b.handle_command("profit?")                  # short questions still answered
    assert "Paused" in b.handle_command("pause trading")


def test_watchdog_warns_the_admin_when_the_mac_runs_on_battery(bot_bridge, clock, monkeypatch):
    # live 22 Oct: the Mac ran on battery (45% -> 43%) all morning; nobody was told except by the assistant
    b, tg = bot_bridge
    import bridge.bot as botmod
    t0 = datetime(2026, 10, 22, 10, 0, tzinfo=IST)
    b.health_status = lambda: {"ok": True, "problems": [], "last_error": None}
    state = {"v": (True, 80)}
    monkeypatch.setattr(botmod, "power_status", lambda: state["v"])
    b.bot._watchdog(t0)
    assert not any("battery" in m for m in tg.admin_sent)                      # on the charger: silent
    state["v"] = (False, 45)
    b.bot._watchdog(t0)
    b.bot._watchdog(t0 + timedelta(minutes=1))
    warned = [m for m in tg.admin_sent if "battery" in m]
    assert len(warned) == 1 and "45%" in warned[0] and "charger" in warned[0]   # once, not every minute
    state["v"] = (False, 24)
    b.bot._watchdog(t0 + timedelta(minutes=30))
    assert sum("battery" in m.lower() for m in tg.admin_sent) == 2 and "24%" in tg.admin_sent[-1]
    state["v"] = (None, None)                                                  # pmset unavailable: no crash, no alert
    b.bot._watchdog(t0 + timedelta(minutes=31))


def test_power_status_reads_pmset(monkeypatch):
    import subprocess
    import bridge.bot as botmod
    out = "Now drawing from 'Battery Power'\n -InternalBattery-0 (id=1)\t43%; discharging; 8:42 remaining present: true\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=out, stderr=""))
    assert botmod.power_status() == (False, 43)
    out2 = "Now drawing from 'AC Power'\n -InternalBattery-0 (id=1)\t97%; charging; present: true\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=out2, stderr=""))
    assert botmod.power_status() == (True, 97)


def test_risk_and_meme_commands_while_running(bot_bridge, clock):
    # admin, 22 Oct 16:39: more commands; /risk is the portfolio view, /meme a little humour (alerts stay professional)
    b, tg = bot_bridge
    from bridge.offline_bot import MEMES
    from bridge.options import OptionLeg
    as_(tg, USER)
    assert "No open positions" in b.handle_command("/risk")
    a = b.accounts[0]
    leg = OptionLeg("NIFTY", "NSE_FO|OPT", 25000, "PE", "2026-10-27", 99.0, 100.0, -0.5, 65, 85.0, 115, 130, 145, "")
    a.consider(clock(), "s1", leg, "NSE_INDEX|Nifty 50", -1, [25030, 24970, 24940, 24910], 0.0, "x")
    r = b.handle_command("/risk")
    assert "5L: 1 SELL / 0 BUY" in r and "if every stop is hit" in r
    assert b.handle_command("/meme") in MEMES
    assert "/risk" in b.handle_command("/help") and "/meme" in b.handle_command("/help")


def test_the_morning_brief_lists_preflight_problems(bot_bridge, clock, monkeypatch):
    # 22 Oct evening: problems found by bridge/preflight.py reach the admin's phone at 09:05
    b, tg = bot_bridge
    import bridge.preflight as pf
    monkeypatch.setattr(pf, "checks", lambda: [(True, "fine"), (False, "power: ON BATTERY (42%): connect the charger")])
    brief = b.bot.morning_brief(clock())
    assert "ON BATTERY" in brief and "fine" not in brief
    monkeypatch.setattr(pf, "checks", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert "Paper trading only" in b.bot.morning_brief(clock())         # a failing check never breaks the brief
