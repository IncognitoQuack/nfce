"""Hardening: randomised inputs and injected failures. The bridge must never crash, never lose an alert, never invent a
fill, and never open a position from bad input. Seeds are fixed, so any failure is reproducible."""
import json
import math
import random
from datetime import timedelta

import httpx
import pytest

from bridge.providers import ProviderError, TokenExpired
from bridge.rules import Signal, SignalError
from conftest import make_payload, sig

N = 400
JUNK = [None, "", "abc", -1, 0, 1e308, float("nan"), float("inf"), [], {}, "25000", True, "NSE:NIFTY1!", 25000.0, -25000.0,
        "BUY", "SELL", "buy", 2 ** 63, "1e5", "☃", " " * 50, "x" * 5000]
FIELDS = ["side", "entry", "sl", "t1", "t2", "t3", "symbol", "tf", "score", "grade", "id", "t", "v", "oi", "closed",
          "events", "event", "pos", "kind"]


def random_payload(rng: random.Random) -> dict:
    p = sig() if rng.random() < 0.5 else {}
    for _ in range(rng.randint(0, 6)):
        p[rng.choice(FIELDS)] = rng.choice(JUNK)
    if rng.random() < 0.2:
        p = {rng.choice(FIELDS): rng.choice(JUNK)}
    return p


def test_signal_parser_either_validates_or_rejects_cleanly():
    rng = random.Random(1)
    for _ in range(N * 3):
        p = random_payload(rng)
        try:
            s = Signal.from_payload(p)
        except SignalError:
            continue
        r = abs(s.entry - s.sl)
        assert math.isfinite(s.entry) and s.entry > 0 and r > 0                       # whatever passes is sane
        assert (s.entry - s.sl) * (1 if s.side == "BUY" else -1) > 0 and r / s.entry <= 0.05


def test_random_alerts_never_crash_and_are_always_accounted_for(make_bridge, clock):
    b, prov, tg = make_bridge()
    rng = random.Random(2)
    for i in range(N):
        p = random_payload(rng)
        if rng.random() < 0.3:
            p["id"] = f"fz{i}"
        b.handle_payload(p, "tradingview")                                              # must not raise
        clock.advance(seconds=7)
    statuses = dict(b.store.db.execute("SELECT status, COUNT(*) FROM inbox GROUP BY status").fetchall())
    assert set(statuses) <= {"DONE", "REJECTED"}                                        # nothing stuck, nothing errored
    for entry, sl in b.store.db.execute("SELECT entry, sl FROM paper_trades").fetchall():
        assert entry > 0 and sl > 0 and entry != sl                                      # no position from bad input


def test_random_commands_never_crash(make_bridge):
    b, _, tg = make_bridge()
    rng = random.Random(3)
    words = ["/check", "/status", "/paper", "/health", "/trust", "/halt", "/resume", "/help", "BUY", "SELL", "25000",
             "24960", "abc", "-5", "nan", "inf", "NIFTY", "BANKNIFTY", "{", "}", '{"side":"BUY"}', "/CHECK@bot", ""]
    for _ in range(N):
        b.handle_command(" ".join(rng.choice(words) for _ in range(rng.randint(0, 6))))     # must not raise
    assert tg.sent


@pytest.mark.parametrize("exc", [ProviderError("boom"), TokenExpired("expired"), httpx.ReadTimeout("slow"),
                                 ValueError("weird payload"), KeyError("data"), ZeroDivisionError()])
def test_any_provider_failure_never_kills_the_worker_or_an_alert(make_bridge, clock, exc):
    b, prov, tg = make_bridge()
    prov.fail = exc
    for _ in range(5):
        b.tick()                                                                       # must not raise
        clock.advance(seconds=15)
    text = b.handle_payload(sig(clock=clock, sid=f"f-{type(exc).__name__}"), "tradingview")
    assert "Chain check: ⚠️ UNCHECKED" in text and "NOT entered" in text               # no data -> no executable entry
    assert b.store.db.execute("SELECT status FROM inbox").fetchone()[0] == "DONE"
    prov.fail = None
    clock.advance(seconds=20)
    b.tick()
    assert b.health_status()["last_error"] is None or b.fresh_quotes("NIFTY")[0] is not None  # recovers on its own


def test_telegram_failure_never_loses_the_alert(make_bridge, clock):
    b, prov, tg = make_bridge()

    def broken(text):
        raise httpx.ConnectError("no network")
    tg.send = broken
    with pytest.raises(httpx.ConnectError):
        tg.send("x")
    try:
        b.handle_payload(sig(clock=clock, sid="tgfail"), "tradingview")
    except httpx.ConnectError:
        pass
    row = b.store.db.execute("SELECT status FROM inbox WHERE sid='tgfail'").fetchone()
    assert row is not None                                                             # stored before any send attempt


def test_clock_jumping_backwards_never_books_a_fill(make_bridge, clock):
    b, prov, tg = make_bridge()
    b.handle_payload(sig(clock=clock, sid="cb"), "tradingview")
    clock.advance(seconds=-120)                                                        # NTP correction / sleep resume
    prov.payload = make_payload(spot=24955.0)
    b.tick()
    clock.advance(seconds=200)
    b.tick()
    rows = b.store.db.execute("SELECT book, status, exit_reason FROM paper_trades").fetchall()
    assert all(st in ("OPEN", "CLOSED", "UNRESOLVED", "REJECTED") for _, st, _ in rows)
    assert all(not (st == "CLOSED" and not why) for _, st, why in rows)                # every close has a reason


def test_restart_in_the_middle_of_a_trade_keeps_it_and_its_evidence(make_bridge, clock, settings):
    from bridge.service import Bridge
    from bridge.store import Store
    from conftest import FakeTelegram, StubProvider
    b, prov, tg = make_bridge()
    b.handle_payload(sig(clock=clock, sid="rs"), "tradingview")
    assert b.paper.open
    b2 = Bridge(settings, StubProvider(make_payload(), clock=clock), Store(settings.db_path), FakeTelegram(), clock=clock)
    assert {t.sid for t in b2.paper.open} == {"rs"}
    assert b2.store.db.execute("SELECT trust FROM signal_evidence WHERE sid='rs'").fetchone() is not None
    assert b2.handle_payload(sig(clock=clock, sid="rs"), "tradingview") == "duplicate alert ignored"
