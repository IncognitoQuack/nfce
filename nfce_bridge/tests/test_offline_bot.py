"""The offline responder (admin, 22 Oct 16:39: "a better bot that even responds when the system is offline")."""
from datetime import datetime

import pytest

from bridge.offline_bot import MEMES, OfflineBot
from bridge.providers import IST

ADMIN, USER = "900", "42"
NOW = datetime(2026, 10, 22, 19, 30, tzinfo=IST)


class FakeTg:
    def __init__(self):
        self.admins, self.chat_id = {ADMIN}, USER
        self.inbox: list[tuple[str, str]] = []
        self.sources: list[str] = []
        self.requests: list = []
        self.sent: list[tuple[str, str]] = []
        self.docs: list[str] = []
        self.polls = self.commits = 0

    def poll_commands(self, timeout=10):
        self.polls += 1
        out, self.sources = [t for _, t in self.inbox], [c for c, _ in self.inbox]
        self.inbox = []
        return out

    def commit(self):
        self.commits += 1

    def _send_one(self, chat, text, html):
        self.sent.append((chat, text))
        return True

    def send_admin(self, text, html=False):
        self.sent.append(("admins", text))
        return True

    def send_document(self, path, caption="", to=None):
        self.docs.append(str(path))
        return True

    def is_admin(self, chat):
        return str(chat) in self.admins


@pytest.fixture
def off(settings):
    from bridge.store import Store
    settings.accounts = {"5L": 500_000, "CONC": 500_000}
    settings.account_strategies = {"5L": "base", "CONC": "concentrated"}
    store = Store(settings.db_path)
    tg = FakeTg()
    ob = OfflineBot(settings, store, tg, now=lambda: NOW, bridge_up=lambda: False)
    return ob, tg, store


def test_it_answers_status_accounts_today_risk_and_help_while_the_bridge_is_down(off):
    ob, tg, _ = off
    st = ob.handle(USER, "/status")
    assert "offline" in st and "08:45" in st
    acc = ob.handle(USER, "/account")
    assert "Paper account 5L" in acc and "<b>CONC</b> (concentrated)" in acc
    assert "Today" in ob.handle(USER, "/today")
    assert "No open positions" in ob.handle(USER, "/risk")
    assert "/meme" in ob.handle(USER, "/help")
    assert ob.handle(USER, "/meme") in MEMES


def test_plain_text_is_saved_for_the_assistant_and_the_ledger_is_admin_only(off, tmp_path):
    ob, tg, store = off
    r = ob.handle(ADMIN, "please also look at why SENSEX quotes go stale")
    assert "saved" in r.lower()
    ev = store.db.execute("SELECT source, raw FROM events ORDER BY id DESC LIMIT 1").fetchone()
    assert ev[0] == "telegram-admin" and "SENSEX" in ev[1]
    assert "admin" in ob.handle(USER, "/ledger").lower() and not tg.docs
    ob.handle(ADMIN, "/ledger")
    assert tg.docs and tg.docs[0].endswith(".csv")


def test_it_polls_only_while_the_bridge_is_down_and_acknowledges_what_it_answered(off):
    ob, tg, _ = off
    up = {"v": True}
    ob._bridge_up = lambda: up["v"]
    tg.inbox = [(USER, "/status")]
    assert ob.step() == 0 and tg.polls == 0                        # the bridge owns Telegram while it runs
    up["v"] = False
    assert ob.step() == 1 and tg.polls == 1 and tg.commits == 1
    assert tg.sent[-1][0] == USER and "offline" in tg.sent[-1][1]


# ---------------- supervisor (22 Oct: the bridge died at 09:49 and nothing noticed for 30 minutes) ----------------
class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def sup(off, t):
    ob, tg, store = off
    clk = Clock(t)
    ob.now = clk
    state = {"up": True, "proc": True, "launched": 0}
    ob._bridge_up = lambda: state["up"]
    ob._bridge_process = lambda: state["proc"]
    ob._health_json = lambda: None                        # never the real port 8000

    def launch():
        state["launched"] += 1
        state["proc"] = True
    ob._launch_bridge = launch
    from pathlib import Path
    ob.maintenance_file = Path("/nonexistent-nfce/.nfce_maintenance")   # never the real home folder
    return ob, tg, clk, state


def test_supervisor_restarts_a_bridge_that_died_during_the_market_and_tells_the_admin(off):
    from datetime import timedelta
    ob, tg, clk, st = sup(off, datetime(2026, 10, 23, 9, 40, tzinfo=IST))
    ob.supervise()                                        # seen running today
    st["up"], st["proc"] = False, False
    clk.t += timedelta(minutes=9)                         # 09:49: dies
    ob.supervise()
    assert st["launched"] == 0                            # not before 60 s
    clk.t += timedelta(seconds=61)
    ob.supervise()
    assert st["launched"] == 1 and any("restarting" in m for _, m in tg.sent)
    st["up"] = True
    clk.t += timedelta(minutes=1)
    ob.supervise()
    assert any("running again" in m for _, m in tg.sent)


def test_supervisor_never_starts_the_day_never_duplicates_and_gives_up_after_three(off):
    from datetime import timedelta
    ob, tg, clk, st = sup(off, datetime(2026, 10, 23, 9, 40, tzinfo=IST))
    st["up"], st["proc"] = False, False
    clk.t += timedelta(minutes=5)
    ob.supervise()
    assert st["launched"] == 0                            # never seen up today: the morning start is the owner's
    st["up"], st["proc"] = True, True
    ob.supervise()
    st["up"] = False                                      # down, but a bridge process still exists (starting / hung)
    clk.t += timedelta(minutes=2)
    ob.supervise()
    assert st["launched"] == 0
    for _ in range(5):                                    # keeps dying: at most 3 restarts, then a person is needed
        st["proc"] = False
        clk.t += timedelta(minutes=2)
        ob.supervise()
    assert st["launched"] == 3 and any("needs a person" in m for _, m in tg.sent)


def test_supervisor_is_quiet_outside_market_hours(off):
    from datetime import timedelta
    ob, tg, clk, st = sup(off, datetime(2026, 10, 23, 15, 0, tzinfo=IST))
    ob.supervise()
    st["up"], st["proc"] = False, False
    clk.t += timedelta(minutes=30)                        # 15:30: the normal shutdown
    ob.supervise()
    assert st["launched"] == 0 and not tg.sent


def test_supervisor_stands_down_while_the_maintenance_file_exists(off, tmp_path):
    from datetime import timedelta
    ob, tg, clk, st = sup(off, datetime(2026, 10, 23, 10, 0, tzinfo=IST))
    ob.maintenance_file = tmp_path / ".nfce_maintenance"
    ob.supervise()
    ob.maintenance_file.write_text("")
    st["up"], st["proc"] = False, False
    for _ in range(3):
        clk.t += timedelta(minutes=2)
        ob.supervise()
    assert st["launched"] == 0
    ob.maintenance_file.unlink()
    clk.t += timedelta(minutes=2)
    ob.supervise()
    clk.t += timedelta(minutes=2)
    ob.supervise()
    assert st["launched"] == 1


def test_supervisor_restarts_a_hung_bridge_whose_market_loop_stopped(off):
    from datetime import timedelta
    ob, tg, clk, st = sup(off, datetime(2026, 10, 23, 11, 0, tzinfo=IST))
    beat = {"t": clk.t}
    ob._health_json = lambda: {"poll_beat": beat["t"].isoformat()}
    killed = []
    ob._stop_bridge = lambda: killed.append(clk.t)
    ob.supervise()
    clk.t += timedelta(minutes=4)                         # beat 4 minutes old: still fine
    ob.supervise()
    assert not killed
    clk.t += timedelta(minutes=2)                         # 6 minutes: hung
    ob.supervise()
    assert len(killed) == 1 and any("not responding" in m for _, m in tg.sent)
    clk.t += timedelta(seconds=30)
    ob.supervise()
    assert len(killed) == 1                               # once, then start.sh restarts it
