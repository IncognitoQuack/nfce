import json
import time
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from bridge.app import create_app
from bridge.providers import IST
from bridge.risk import market_open
from bridge.service import signal_id, symbol_root
from bridge.upstox_login import token_expiry
from conftest import make_payload, sig


def rows(b, sql):
    return b.store.db.execute(sql).fetchall()


def test_symbol_root_and_signal_id():
    assert symbol_root("NSE:NIFTY1!") == "NIFTY" and symbol_root("BANKNIFTY") == "BANKNIFTY"
    assert signal_id({"id": "abc"}) == "abc"
    a, b = signal_id({"side": "BUY", "entry": 1}), signal_id({"side": "BUY", "entry": 1})
    assert a == b and a.startswith("h:") and a != signal_id({"side": "BUY", "entry": 2})


def test_pass_flow_opens_both_books(make_bridge, clock):
    b, prov, tg = make_bridge()
    text = b.handle_payload(sig(clock=clock), "tradingview")
    assert "Chain check: ✅ PASS" in text and "No order placed" in text
    assert "theoretical book: opened" in text and "executable book: entered 10 lots at 25000.3" in text   # ask 25000.1 + 2 ticks
    assert b.store.count("signals") == 1 and b.store.count("inbox") == 1
    books = sorted(r[0] for r in rows(b, "SELECT book FROM paper_trades WHERE status='OPEN'"))
    assert books == ["executable", "theoretical"]


def test_executable_blocks_have_reasons(make_bridge, clock):
    b, prov, tg = make_bridge()
    t = b.handle_payload(sig(clock=clock, delay_s=600, sid="old"), "tradingview")
    assert "NOT entered (entry decision 600s after the bar closed" in t
    t = b.handle_payload({k: v for k, v in sig(sid="no-time").items() if k != "t"}, "tradingview")
    assert "NOT entered (alert has no bar time" in t
    prov.spread = 10.0
    clock.advance(seconds=16)                                  # let the cached quote expire
    t = b.handle_payload(sig(clock=clock, sid="wide"), "tradingview")
    assert "NOT entered (spread 10.0 pts" in t
    prov.spread = 0.2
    clock.advance(seconds=16)
    b.handle_command("/halt")
    t = b.handle_payload(sig(clock=clock, sid="halted"), "tradingview")
    assert "NOT entered (halted" in t
    rej = rows(b, "SELECT COUNT(*) FROM paper_trades WHERE status='REJECTED'")[0][0]
    assert rej == 4


def test_manual_check_and_pasted_json_are_analysis_only(make_bridge, clock):
    b, _, tg = make_bridge()
    assert "analysis only" in b.handle_command("/check SELL 25000 25040")
    assert "analysis only" in b.handle_command(json.dumps(sig(clock=clock)))
    assert rows(b, "SELECT COUNT(*) FROM paper_trades")[0][0] == 0
    assert "Usage" in b.handle_command("/check BUY oops") and "/status" in b.handle_command("/help")


def test_events(make_bridge):
    b, _, tg = make_bridge()
    b.handle_payload({"symbol": "NSE:NIFTY1!", "event": "Long exit: SL hit", "sl": 24480.1}, "tradingview")
    assert "SL hit" in tg.sent[-1] and "SL now" not in tg.sent[-1]           # closed trade: no "SL now"
    b.handle_payload({"v": 2, "id": "e1", "symbol": "NSE:NIFTY1!", "tf": "5", "pos": 1, "sl": 25000,
                      "events": ["Long T1 hit: book part, SL->BE"]}, "tradingview")
    assert "T1 hit" in tg.sent[-1] and "SL now 25000" in tg.sent[-1]
    assert b.store.count("events") == 2


def test_webhook_security_and_durable_inbox(make_bridge, clock, settings):
    b, _, tg = make_bridge()
    key = settings.webhook_secret
    with TestClient(create_app(b, start_loops=False)) as c:
        body = json.dumps(sig(clock=clock))
        assert c.post("/tv", content=body).status_code == 403
        assert c.post("/tv?key=wrong", content=body).status_code == 403
        assert c.post(f"/tv?key={key}", content="not json").status_code == 400
        assert c.post(f"/tv?key={key}", content="x" * 20_000).status_code == 413
        t = time.perf_counter()
        r = c.post(f"/tv?key={key}", content=body, headers={"Content-Type": "text/plain"})
        assert r.status_code == 200 and r.json()["ok"] and time.perf_counter() - t < 3
        assert c.post(f"/tv?key={key}", content=body).json().get("duplicate")       # same alert twice
        h = c.get("/health")
        assert h.status_code == 503 and "poll worker not running" in h.json()["problems"]
    assert b.store.count("inbox") == 1 and b.store.count("signals") == 1


def test_rate_limit(make_bridge, clock, settings):
    b, _, _ = make_bridge()
    settings.max_requests_per_minute = 3
    with TestClient(create_app(b, start_loops=False)) as c:
        codes = [c.post(f"/tv?key={settings.webhook_secret}", content=json.dumps(sig(clock=clock, sid=f"r{i}"))).status_code
                 for i in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]


def test_recover_inbox_after_crash(make_bridge, clock):
    b, _, _ = make_bridge()
    inbox_id, dup = b.accept(sig(clock=clock), "tradingview")      # accepted, then "crash" before processing
    assert not dup and b.store.inbox_pending()
    assert b.recover_inbox() == 1 and not b.store.inbox_pending() and b.store.count("signals") == 1


def test_health_ok_when_workers_and_data_are_fresh(make_bridge, clock):
    b, _, _ = make_bridge()
    b.tick()
    assert b.health_status()["ok"], b.health_status()


def test_market_hours_and_token_expiry():
    assert market_open(datetime(2026, 10, 16, 10, 0, tzinfo=IST))
    assert not market_open(datetime(2026, 10, 17, 10, 0, tzinfo=IST))
    assert not market_open(datetime(2026, 10, 16, 9, 0, tzinfo=IST))
    assert not market_open(datetime(2026, 10, 16, 15, 45, tzinfo=IST))
    assert token_expiry(datetime(2026, 10, 16, 20, 0, tzinfo=IST)) == datetime(2026, 10, 17, 3, 30, tzinfo=IST)
    assert token_expiry(datetime(2026, 10, 17, 2, 30, tzinfo=IST)) == datetime(2026, 10, 17, 3, 30, tzinfo=IST)


def test_iv_change_same_session_only(make_bridge, clock):
    b, prov, _ = make_bridge(make_payload(iv=12.0))
    b.refresh_chain("NIFTY")
    clock.advance(minutes=15)
    prov.payload = make_payload(iv=13.5)
    s, _ = b.refresh_chain("NIFTY")
    d, note = b.store.iv_change(s.underlying_key, s.fetched_at)
    assert abs(d - 1.5) < 1e-9 and note == ""


def test_chain_refresh_records_option_quotes_for_the_atm_window(make_bridge):
    """Registry R1 needs timestamped option bid/ask; the bridge records ATM +/- window strikes on every refresh."""
    b, prov, _ = make_bridge(make_payload())
    s, snap = b.refresh_chain("NIFTY")
    assert b.store.count("option_quotes") == 2 * (2 * b.s.window + 1)
    ce = rows(b, "SELECT key, ltp, bid, ask, oi, expiry, snap_id FROM option_quotes WHERE strike=25000 AND type='CE'")
    assert ce == [("NSE_FO|C25000", 21.0, 20.5, 21.5, 100000.0, "2026-10-27", snap)]      # fixture ATM ltp = 1 + 20
    prov.payload = make_payload(bid_ask=False)
    b.refresh_chain("NIFTY")
    assert rows(b, "SELECT COUNT(*) FROM option_quotes WHERE bid IS NULL AND ask IS NULL")[0][0] == 2 * (2 * b.s.window + 1)


def test_daily_report_once_and_persisted(make_bridge, clock):
    b, _, _ = make_bridge()
    assert b.daily_report(clock().replace(hour=14)) is None
    assert b.daily_report(clock().replace(hour=15, minute=25)) is not None
    b2, _, _ = make_bridge()                                       # restart: marker survives
    assert b2.daily_report(clock().replace(hour=15, minute=40)) is None


def test_every_signal_leads_with_its_evidence_label_and_card(make_bridge, clock):
    """Trust upgrade: the headline is the measured evidence, not the chain check; the card is stored."""
    b, _, tg = make_bridge()
    text = b.handle_payload(sig(clock=clock, sid="ev1"), "tradingview")
    first = text.splitlines()[0]
    assert first.startswith(("🔴 NO EDGE", "🟠 LEAD (unproven)", "🟢 VALIDATED")) and "NIFTY BUY" in first
    assert "Evidence (" in text and "Costs for this signal:" in text and "Evidence (index futures" in text
    assert "Not a recommendation" in text
    row = rows(b, "SELECT sid, trust, cell_key, cost_share FROM signal_evidence")
    assert row and row[0][0] == "ev1" and row[0][1] in ("NO EDGE", "LEAD (unproven)", "VALIDATED") and row[0][3] > 0


def test_tight_stop_is_labelled_no_edge_because_of_costs(make_bridge, clock):
    b, _, _ = make_bridge()
    text = b.handle_payload(sig(entry=25000.0, sl=24995.0, clock=clock, sid="tight"), "tradingview")
    assert text.startswith("🔴 NO EDGE") and "too tight for futures costs" in text


def test_trust_command_shows_evidence_base_and_live_record(make_bridge):
    b, _, _ = make_bridge()
    text = b.handle_command("/trust")
    assert "VALIDATED classes: none" in text and "504" in text and "no closed executable paper trades yet" in text
