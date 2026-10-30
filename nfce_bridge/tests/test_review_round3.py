"""Independent review, round 3 (NFCE_updated_independent_review.md): each finding's failure scenario, reproduced.
Every test here failed on the Final Trade Software code of 20 Oct 2026 (or describes behaviour it lacked)."""
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta

import pytest

from bridge.paper import PaperTrade, lot_plan
from bridge.providers import IST, Quote
from bridge.rules import Signal, SignalError
from conftest import T0, StubProvider, make_payload, sig


def rows(b, q, *a):
    with b.store._lock:
        return b.store.db.execute(q, a).fetchall()


# ---------- H02: whole lots ----------
def test_H02_paper_trades_exit_whole_lots_only():
    assert lot_plan(10) == (4, 3, 3) and lot_plan(3) == (1, 1, 1) and lot_plan(1) == (1, 0, 0) and lot_plan(2) == (1, 1, 0)
    for lots in (1, 2, 3, 5, 10):
        n1, n2, n3 = lot_plan(lots)
        assert n1 + n2 + n3 == lots and min(n1, n2, n3) >= 0
    now = T0
    q = lambda px: Quote("F", px, now, now, bid=px - 0.1, ask=px + 0.1)   # noqa: E731
    t = PaperTrade(book="theoretical", underlying="NIFTY", tf="5", decision="PASS", grade="A", side=1, entry=100.0,
                   sl=90.0, t1=110.0, t2=120.0, t3=130.0, opened=now.isoformat(), lots=10)
    t.on_quote(q(110.0), now)
    assert t.rem * t.lots == pytest.approx(6)                      # 4 of 10 lots out at T1, 6 whole lots left
    one = PaperTrade(book="theoretical", underlying="NIFTY", tf="5", decision="PASS", grade="A", side=1, entry=100.0,
                     sl=90.0, t1=110.0, t2=120.0, t3=130.0, opened=now.isoformat(), lots=1)
    assert one.on_quote(q(110.0), now) and one.exit_reason == "T1 (all lots)" and one.pnl == pytest.approx(10.0)


# ---------- H03: atomic one-position rule ----------
def test_H03_concurrent_distinct_signals_cannot_both_open(make_bridge, clock):
    b, prov, tg = make_bridge()
    real = b.paper.has_open

    def slow_has_open(*a):
        r = real(*a)
        time.sleep(0.15)                       # widen the window between "is it flat?" and the insert
        return r
    b.paper.has_open = slow_has_open
    th = [threading.Thread(target=b.handle_payload, args=(sig(clock=clock, sid=f"race{i}"), "tradingview"))
          for i in range(2)]
    for x in th:
        x.start()
    for x in th:
        x.join()
    n = rows(b, "SELECT COUNT(*) FROM paper_trades WHERE book='executable' AND status='OPEN'")[0][0]
    assert n == 1


def test_H03_database_refuses_a_second_open_position(make_bridge, clock):
    b, prov, tg = make_bridge()
    b.handle_payload(sig(clock=clock, sid="a"), "tradingview")
    with pytest.raises(sqlite3.IntegrityError):
        with b.store.db:
            b.store.db.execute("INSERT INTO paper_trades (book, sid, underlying, tf, status) "
                               "VALUES ('executable', 'b', 'NIFTY', '5', 'OPEN')")


# ---------- H04: freshness judged at the entry decision ----------
def test_H04_slow_work_cannot_open_a_trade_on_an_old_quote(make_bridge, clock):
    b, prov, tg = make_bridge()

    def slow_forecast(root, now):
        clock.advance(seconds=300)            # e.g. a slow history download
        return None, "slow"
    b.range_forecast = slow_forecast
    text = b.handle_payload(sig(clock=clock, sid="slow"), "tradingview")
    assert "executable book: NOT entered (entry decision 30" in text


def test_H04_quote_is_refetched_and_rechecked_at_the_decision(make_bridge, clock):
    b, prov, tg = make_bridge()

    def freeze_then_forecast(root, now):
        prov.frozen_ltt = clock() - timedelta(minutes=10)   # the feed froze after the alert's first quote
        return None, "n/a"
    b.range_forecast = freeze_then_forecast
    text = b.handle_payload(sig(clock=clock, sid="frz"), "tradingview")
    assert "NOT entered (no fresh futures quote" in text


# ---------- H05: a futures quote needs an exchange timestamp ----------
def test_H05_futures_quote_without_exchange_time_is_not_fresh(make_bridge, clock):
    b, prov, tg = make_bridge()
    real = prov.quotes

    def no_ltt(keys):
        out = real(keys)
        for k, q in out.items():
            if k.startswith("NSE_FO"):
                q.last_trade_time = None
        return out
    prov.quotes = no_ltt
    text = b.handle_payload(sig(clock=clock, sid="noltt"), "tradingview")
    assert "NOT entered (no fresh futures quote with an exchange timestamp)" in text


# ---------- H07: option recorder keeps the R1 expiry and every strike the day touched ----------
class ExpiryStub(StubProvider):
    def __init__(self, *a, expiries=(), **k):
        super().__init__(*a, **k)
        self._exp = list(expiries)

    def expiries(self, key):
        return self._exp

    def chain(self, key, expiry):
        p = make_payload(spot=float(self.payload["data"][0]["underlying_spot_price"]), expiry=expiry, n=20)
        self.payload = {**p}
        from bridge.providers import parse_upstox_chain
        from datetime import timezone
        return parse_upstox_chain(p, key, fetched_at=self.clock().astimezone(timezone.utc))


def test_H07_expiry_day_also_records_the_next_expiry(settings, clock):
    from bridge.service import Bridge
    from bridge.store import Store
    from conftest import FakeTelegram
    today = clock().date().isoformat()
    prov = ExpiryStub(make_payload(), clock=clock, expiries=[today, "2026-10-28"])
    b = Bridge(settings, prov, Store(settings.db_path), FakeTelegram(), clock=clock)
    b.refresh_chain("NIFTY")
    got = {r[0] for r in rows(b, "SELECT DISTINCT expiry FROM option_quotes")}
    assert got == {today, "2026-10-28"}


def test_H07_strike_held_after_a_large_move_is_still_recorded(settings, clock):
    from bridge.service import Bridge
    from bridge.store import Store
    from conftest import FakeTelegram
    prov = ExpiryStub(make_payload(spot=25000.0), clock=clock, expiries=["2026-10-27"])
    b = Bridge(settings, prov, Store(settings.db_path), FakeTelegram(), clock=clock)
    b.refresh_chain("NIFTY")                                       # ITM call chosen now: 24950
    prov.payload = make_payload(spot=25400.0)                      # 400-point rally
    clock.advance(minutes=30)
    b.refresh_chain("NIFTY")
    last = rows(b, "SELECT MAX(ts) FROM option_quotes")[0][0]
    later = rows(b, "SELECT COUNT(*) FROM option_quotes WHERE strike=24950 AND type='CE' AND ts = ?", last)[0][0]
    assert later == 1
    assert rows(b, "SELECT MIN(strike) FROM option_quotes WHERE ts = ?", last)[0][0] <= 25000 - 5 * 50


def test_H07_front_contract_is_recorded_per_day(make_bridge, clock):
    b, prov, tg = make_bridge()
    b.refresh_quotes("NIFTY")
    assert rows(b, "SELECT key, root, day FROM contracts") == [("NSE_FO|FUT-NIFTY", "NIFTY", clock().date().isoformat())]


# ---------- H12: one price domain ----------
def test_H12_spot_chart_levels_are_moved_to_futures_prices(make_bridge, clock):
    b, prov, tg = make_bridge(basis=80.0)
    text = b.handle_payload(sig(entry=25000.0, sl=24900.0, clock=clock, sid="spot1", symbol="NSE:NIFTY"), "tradingview")
    assert "moved to futures with the live basis +80.0" in text
    e, sl, t1 = rows(b, "SELECT entry, sl, t1 FROM paper_trades WHERE book='executable' AND sid='spot1'")[0]
    assert sl == pytest.approx(24980.0) and t1 == pytest.approx(25180.0)
    assert e - sl == pytest.approx(100.0 + 0.1 + 0.2, abs=0.01)           # risk stays ~100 points, not 180


def test_H12_spot_levels_without_a_basis_are_never_paper_traded(make_bridge, clock):
    b, prov, tg = make_bridge(basis=80.0)
    real = prov.quotes
    prov.quotes = lambda keys: {k: v for k, v in real(keys).items() if k.startswith("NSE_FO")}
    text = b.handle_payload(sig(clock=clock, sid="spot2", symbol="NSE:NIFTY"), "tradingview")
    assert "executable book: NOT entered (levels are SPOT prices" in text
    assert "theoretical book: NOT entered (levels are SPOT prices" in text


def test_H12_domain_from_symbol_or_explicit_field():
    base = dict(side="BUY", entry=1000, sl=990)
    assert Signal.from_payload({**base, "symbol": "NSE:NIFTY1!"}).domain == "futures"
    assert Signal.from_payload({**base, "symbol": "NSE:NIFTY"}).domain == "spot"
    assert Signal.from_payload({**base, "symbol": "NSE:NIFTY", "px": "futures"}).domain == "futures"
    s = Signal.from_payload({**base, "symbol": "NSE:NIFTY"}).to_futures(5.0)
    assert (s.entry, s.sl, s.t1, s.t2, s.t3, s.domain) == (1005, 995, 1015, 1025, 1035, "futures")


# ---------- M01: bar time in the future ----------
def test_M01_future_dated_alert_does_not_open(make_bridge, clock):
    b, prov, tg = make_bridge()
    text = b.handle_payload(sig(clock=clock, sid="fut", delay_s=-3600), "tradingview")
    assert "NOT entered (bar time is 3600s in the future" in text


# ---------- M02: defaults completed before validation ----------
def test_M02_missing_targets_are_completed_then_validated():
    with pytest.raises(SignalError, match="in order"):
        Signal.from_payload({"side": "BUY", "entry": 25000, "sl": 24960, "t1": 25160})
    s = Signal.from_payload({"side": "BUY", "entry": 25000, "sl": 24960})
    assert (s.t1, s.t2, s.t3) == (25040, 25080, 25120)


# ---------- M09: delivery and health ----------
def test_M09_daily_report_is_retried_after_a_failed_delivery(make_bridge, clock):
    b, prov, tg = make_bridge()
    tg.send = lambda text: False
    clock.set(datetime(2026, 10, 21, 15, 25, tzinfo=IST))
    b.daily_report()
    assert b.store.kv_get("report_day") is None
    tg.send = lambda text: True
    b.daily_report()
    assert b.store.kv_get("report_day") == "2026-10-21"


def test_M09_health_names_the_dead_instrument(make_bridge, clock, settings):
    settings.poll_underlyings = ["NIFTY", "BANKNIFTY"]
    b, prov, tg = make_bridge()
    b.refresh_quotes("NIFTY")
    b.refresh_chain("NIFTY")
    probs = b.health_status()["problems"]
    assert "no fresh futures quotes for BANKNIFTY" in probs and "no fresh futures quotes for NIFTY" not in probs


# ---------- M11: index cards never use stock trades ----------
def test_M11_index_signal_evidence_is_index_futures_only():
    from bridge.evidence import assess, load_table
    t = load_table()
    s = Signal.from_payload({"side": "BUY", "entry": 25000, "sl": 24960, "symbol": "NSE:NIFTY1!"})
    for hh in (10, 14):
        when = datetime(2026, 10, 21, hh, 0, tzinfo=IST)
        card = assess(t, s, "NIFTY", when, when)
        assert card.key.startswith("index futures") and "stock" not in card.key
        assert card.cell["n"] in (t["index_cells"]["tv|morning"]["n"], t["index_cells"]["tv|later"]["n"])
