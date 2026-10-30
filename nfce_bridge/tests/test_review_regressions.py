"""One regression test per finding of the two independent reviews (IDs from their reports).

Each test reproduces the reviewer's failure scenario and asserts the corrected behaviour.
"""
import json
from datetime import timedelta

import httpx
import pytest

from bridge.providers import ProviderError
from bridge.telegram import Telegram
from conftest import make_payload, sig


def open_rows(b, book=None):
    q = "SELECT book, status, exit_reason FROM paper_trades" + (f" WHERE book='{book}'" if book else
                                                                 " WHERE book IN ('executable', 'theoretical')")   # R4: own tests
    return b.store.db.execute(q).fetchall()


def test_F01_no_fake_stop_from_spot_vs_futures_basis(make_bridge, clock):
    """Audit F-01: spot 25,000, NIFTY1! 25,100. A BUY at 25,100 / SL 25,060 must not be stopped on an unchanged market."""
    b, prov, tg = make_bridge(make_payload(spot=25000.0), basis=100.0)
    b.handle_payload(sig(entry=25100, sl=25060, clock=clock), "tradingview")
    for _ in range(8):
        clock.advance(seconds=15)
        b.tick()
    assert all(st == "OPEN" for _, st, _ in open_rows(b)), open_rows(b)


def test_F01_without_quotes_no_executable_trade_and_unchecked(make_bridge, clock):
    b, prov, tg = make_bridge()
    prov.fail = ProviderError("Upstox request failed: ReadTimeout")
    text = b.handle_payload(sig(clock=clock), "tradingview")
    assert "Chain check: ⚠️ UNCHECKED" in text and "executable book: NOT entered (no fresh futures quote" in text


def test_F02_H02_timeouts_never_kill_the_worker_or_drop_signals(make_bridge, clock):
    """F-02/H02: a ReadTimeout must not escape tick() or handle_payload(); the signal is still logged."""
    b, prov, tg = make_bridge()
    prov.fail = ProviderError("Upstox request failed: ReadTimeout")
    b.tick()                                                   # must not raise
    b.handle_payload(sig(clock=clock), "tradingview")
    assert b.store.count("signals") == 1
    prov.fail = RuntimeError("anything else")                  # even unexpected errors are contained
    b.tick()
    prov.fail = None
    clock.advance(seconds=20)
    b.tick()
    assert b.health_status()["ok"]


def test_H03_F07_overnight_carry_is_unresolved_not_profit(make_bridge, clock):
    """H03/F-07: missed 15:15 polls + restart next morning must not carry a position into the next session."""
    b, prov, tg = make_bridge()
    b.handle_payload(sig(clock=clock), "tradingview")
    clock.set(clock().replace(hour=15, minute=0))
    b.tick()
    clock.set(clock() + timedelta(days=1))
    clock.set(clock().replace(hour=9, minute=16))               # restart next morning
    prov.payload = make_payload(spot=24900.0)                   # gap down overnight
    b.tick()
    statuses = {st for _, st, _ in open_rows(b)}
    assert statuses == {"UNRESOLVED"}, open_rows(b)
    assert "excluded" in b.paper.report()


def test_H04_executable_entry_uses_arrival_price_not_signal_price(make_bridge, clock):
    """H04: a BUY signalled at 25,000 that arrives when the market is 25,040 enters the executable book at the ask."""
    b, prov, tg = make_bridge(fut_price=25040.0)
    b.handle_payload(sig(entry=25000, sl=24940, clock=clock), "tradingview")
    ex = b.store.db.execute("SELECT entry FROM paper_trades WHERE book='executable'").fetchone()[0]
    th = b.store.db.execute("SELECT entry FROM paper_trades WHERE book='theoretical'").fetchone()[0]
    assert th == 25000 and ex == pytest.approx(25040.1 + 0.2)


def test_H04_stale_alert_rejected_for_execution(make_bridge, clock):
    b, prov, tg = make_bridge()
    text = b.handle_payload(sig(clock=clock, delay_s=900), "tradingview")
    assert "NOT entered (entry decision 900s after the bar closed" in text


def test_H05_duplicates_and_manual_checks_never_duplicate_positions(make_bridge, clock):
    """H05/F-07(2): same payload twice -> one position per book; /check three times -> no paper trades."""
    b, prov, tg = make_bridge()
    p = sig(clock=clock)
    b.handle_payload(p, "tradingview")
    assert b.handle_payload(dict(p), "tradingview") == "duplicate alert ignored"
    p2 = dict(p, id="other-id")                                 # a different id for the same 5m position
    b.handle_payload(p2, "tradingview")
    for _ in range(3):
        b.handle_command("/check BUY 24500 24470")
    books = [bk for bk, st, _ in open_rows(b) if st == "OPEN"]
    assert sorted(books) == ["executable", "theoretical"]


def test_H09_missing_prev_oi_is_unchecked_and_bad_levels_rejected(make_bridge, clock):
    b, prov, tg = make_bridge(make_payload(prev_missing=True))
    text = b.handle_payload(sig(clock=clock), "tradingview")
    assert "Chain check: ⚠️ UNCHECKED" in text and "previous-day OI missing" in text
    bad = b.handle_payload({"symbol": "NIFTY", "side": "BUY", "entry": 100, "sl": 100, "t1": 100}, "tradingview")
    assert bad.startswith("⚠️ Alert rejected") and b.store.db.execute(
        "SELECT status FROM inbox ORDER BY id DESC LIMIT 1").fetchone()[0] == "REJECTED"


def test_F09_M12_put_unwinding_counts_as_bearish(make_bridge, clock):
    """F-09: put ΔOI -500k, call ΔOI 0 and a building call wall in the path -> VETO (was PASS)."""
    put = {24950: (100_000, 600_000, 20.0)}                     # -500k put ΔOI
    call = {25050: (2_000_000, 2_000_000, 30.0)}
    b, prov, tg = make_bridge(make_payload(put=put, call=call))
    s, _ = b.refresh_chain("NIFTY")
    assert s.flow == "bearish_lean"
    call2 = {25050: (2_000_000, 1_900_000, 30.0)}              # wall now adding OI, call ΔOI total +100k
    b2, _, _ = make_bridge(make_payload(put=put, call=call2))
    text = b2.handle_payload(sig(entry=25000, sl=24960, t1=25100, t2=25150, t3=25200, clock=clock, sid="f09"),
                             "tradingview")
    assert "Chain check: ⛔ VETO" in text, text


def test_M05_iv_change_is_not_compared_overnight(make_bridge, clock):
    b, prov, _ = make_bridge(make_payload(iv=12.0))
    b.refresh_chain("NIFTY")
    clock.set(clock() + timedelta(days=1))
    clock.set(clock().replace(hour=9, minute=30))
    prov.payload = make_payload(iv=15.0)
    s, _ = b.refresh_chain("NIFTY")
    d, note = b.store.iv_change(s.underlying_key, s.fetched_at)
    assert d is None and "no comparable" in note


def test_M07_frozen_feed_or_holiday_blocks_execution(make_bridge, clock):
    """M07: a feed whose last trade is old (holiday / frozen) is stale, whatever the receipt time."""
    b, prov, tg = make_bridge()
    prov.frozen_ltt = clock() - timedelta(hours=18)
    text = b.handle_payload(sig(clock=clock), "tradingview")
    assert "Chain check: ⚠️ UNCHECKED" in text and "no fresh futures quote" in text
    b.tick()
    assert "no fresh futures quotes for NIFTY" in b.health_status()["problems"]


def test_M10_telegram_ignores_groups_and_other_senders():
    updates = {"ok": True, "result": [
        {"update_id": 1, "message": {"chat": {"id": 42, "type": "private"}, "from": {"id": 42}, "text": "/paper"}},
        {"update_id": 2, "message": {"chat": {"id": 42, "type": "group"}, "from": {"id": 42}, "text": "/halt"}},
        {"update_id": 3, "message": {"chat": {"id": 42, "type": "private"}, "from": {"id": 7}, "text": "/halt"}},
        {"update_id": 4, "message": {"chat": {"id": 99, "type": "private"}, "from": {"id": 99}, "text": "/halt"}},
    ]}
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=updates)))
    store = {}
    tg = Telegram("1:x", "42", client=client, offset_get=lambda: store.get("o", 0), offset_set=lambda v: store.update(o=v))
    assert tg.poll_commands() == ["/paper"] and "o" not in store      # not acknowledged before handling (M09)
    tg.commit()
    assert store["o"] == 5


def test_outage_spanning_square_off_then_restart_next_morning(make_bridge, clock, settings):
    """Reviewer's most important missing test: outage across 15:15, restart next morning, stale response, gap."""
    from bridge.service import Bridge
    from bridge.store import Store
    b, prov, tg = make_bridge()
    b.handle_payload(sig(clock=clock), "tradingview")
    clock.set(clock().replace(hour=15, minute=5))
    b.tick()                                                    # last good quote before the outage
    prov.fail = ProviderError("Upstox request failed: ConnectError")
    for m in (10, 15, 20, 25):
        clock.set(clock().replace(minute=m))
        b.tick()                                                # outage: nothing booked, nothing raised
    assert {st for _, st, _ in open_rows(b)} == {"OPEN"}
    prov.fail = None
    clock.set(clock() + timedelta(days=1))
    clock.set(clock().replace(hour=9, minute=10))
    prov.frozen_ltt = clock() - timedelta(hours=17)             # pre-open: stale quote from yesterday
    b2 = Bridge(settings, prov, Store(settings.db_path), tg, clock=clock)   # restart
    b2.tick()
    assert {st for _, st, _ in open_rows(b2)} == {"OPEN"}         # stale data books nothing
    prov.frozen_ltt = None
    clock.set(clock().replace(hour=9, minute=16))
    prov.payload = make_payload(spot=24950.0)                   # gap
    b2.tick()
    assert {st for _, st, _ in open_rows(b2)} == {"UNRESOLVED"}
    assert any("UNRESOLVED" in m for m in tg.sent)


def test_inbox_survives_processing_crash(make_bridge, clock, monkeypatch):
    b, prov, tg = make_bridge()
    monkeypatch.setattr(b, "_signal", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    text = b.handle_payload(sig(clock=clock), "tradingview")
    assert "kept in the inbox" in text
    assert b.store.db.execute("SELECT status FROM inbox").fetchone()[0] == "ERROR"


def test_daily_stop_blocks_after_two_losses(make_bridge, clock):
    b, prov, tg = make_bridge()
    for i in range(2):
        b.handle_payload(sig(clock=clock, sid=f"loss{i}"), "tradingview")
        prov.payload = make_payload(spot=24955.0)              # just through the 24,960 stop: about -1.5R net each
        clock.advance(seconds=20)
        b.tick()
        prov.payload = make_payload(spot=25000.0)
        clock.advance(seconds=20)
    text = b.handle_payload(sig(clock=clock, sid="third"), "tradingview")
    assert "NOT entered (daily stop: 2 losing trades today)" in text


def test_daily_stop_minus_2R(make_bridge, clock):
    b, prov, tg = make_bridge()
    b.handle_payload(sig(clock=clock, sid="big"), "tradingview")
    prov.payload = make_payload(spot=24900.0)                  # gap through the stop: about -2.9R net
    clock.advance(seconds=20)
    b.tick()
    prov.payload = make_payload(spot=25000.0)
    clock.advance(seconds=20)
    text = b.handle_payload(sig(clock=clock, sid="next"), "tradingview")
    assert "NOT entered (daily stop: -2." in text


def test_l02_closed_event_inside_a_signal_is_recorded_and_shown(make_bridge, clock):
    """L02 follow-up: with same-bar re-entry on, Pine sends the old trade's exit inside the new signal ("closed")."""
    b, prov, tg = make_bridge()
    s = sig(clock=clock, sid="new")
    s["closed"] = {"id": "old", "events": ["Long exit: SL hit"]}
    text = b.handle_payload(s, "tradingview")
    assert b.store.count("events") == 1
    ev = json.loads(b.store.db.execute("SELECT raw FROM events").fetchone()[0])
    assert ev["id"] == "old" and ev["pos"] == 0 and ev["events"] == ["Long exit: SL hit"]
    assert "previous trade old: Long exit: SL hit" in text



def test_owner_extra_chat_is_accepted_and_answered_in_its_own_chat():
    import threading
    updates = {"ok": True, "result": [
        {"update_id": 1, "message": {"chat": {"id": 42, "type": "private"}, "from": {"id": 42}, "text": "/paper"}},
        {"update_id": 2, "message": {"chat": {"id": 77, "type": "private"}, "from": {"id": 77}, "text": "/health"}},
        {"update_id": 3, "message": {"chat": {"id": 99, "type": "private"}, "from": {"id": 99}, "text": "/halt"}},
    ]}
    posted = []

    def handler(r):
        if r.url.path.endswith("getUpdates"):
            return httpx.Response(200, json=updates)
        import json as _j
        posted.append(_j.loads(r.content)["chat_id"])
        return httpx.Response(200, json={"ok": True})
    tg = Telegram("1:x", "42", client=httpx.Client(transport=httpx.MockTransport(handler)), extra_chat_ids={"77"})
    assert tg.poll_commands() == ["/paper", "/health"] and tg.sources == ["42", "77"]   # chat 99 still ignored
    tg.reply_to = "77"
    tg.send("answer")
    other = threading.Thread(target=lambda: tg.send("signal"))                 # another thread: a broadcast
    other.start(); other.join()
    tg.reply_to = None
    assert posted == ["77", "42", "77"]          # the broadcast reaches the main chat and the owner's (admin) chat


def test_a_muted_chat_gets_no_direct_replies_either_but_admins_always_do():
    """Owner: "dont send any signals or msg to the main chat" -- the bot's automatic replies obeyed /stop
    and /mute only for broadcasts; a reply to the muted chat's own question still went out."""
    posted = []

    def handler(r):
        posted.append(json.loads(r.content)["chat_id"])
        return httpx.Response(200, json={"ok": True})
    tg = Telegram("1:x", "42", client=httpx.Client(transport=httpx.MockTransport(handler)), admin_chat_ids={"77"})
    tg.muted = lambda: {"42", "77"}
    tg.reply_to = "42"
    tg.send("answer")
    tg.reply_to = "77"                                   # an admin can never be muted
    tg.send("answer")
    tg.reply_to = None
    assert posted == ["77"]
