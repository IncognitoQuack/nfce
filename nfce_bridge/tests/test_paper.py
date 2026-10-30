from datetime import datetime, timedelta

import pytest

from bridge.costs import futures_cost_points
from bridge.paper import PaperBook, PaperTrade
from bridge.providers import IST, Quote
from bridge.store import Store

D = datetime(2026, 10, 21, 10, 0, tzinfo=IST)


def at(h, m, day=0):
    return D.replace(hour=h, minute=m) + timedelta(days=day)


def q(px, t, spread=0.2):
    return Quote("NSE_FO|F", px, t, t, bid=px - spread / 2, ask=px + spread / 2)


def trade(book="theoretical", side=1, entry=100.0, sl=90.0, t1=110.0, t2=120.0, t3=130.0):
    return PaperTrade(book, "NIFTY", "5", "PASS", "A", side, entry, sl, t1, t2, t3, opened=at(10, 0).isoformat(), sid="x")


def feed(t, prices, start=(10, 0), step_s=15):
    tm = at(*start)
    for px in prices:
        tm += timedelta(seconds=step_s)
        if t.on_quote(q(px, tm), tm):
            return tm
    return None


def test_theoretical_t1_then_breakeven_is_plus_0_4R():
    t = trade()
    feed(t, [111, 105, 99.5])
    assert t.status == "CLOSED" and t.exit_reason == "trail/BE stop"
    assert t.pnl == pytest.approx(0.4 * 10)                    # BE stop crossed between ticks -> filled at the stop


def test_theoretical_gap_fills_at_observed_price():
    t = trade()
    t.on_quote(q(111, at(10, 1)), at(10, 1))
    t.on_quote(q(99.5, at(10, 5)), at(10, 5))                 # 4 minutes without data -> gap
    assert "gap" in t.flags and t.pnl == pytest.approx(0.4 * 10 + 0.6 * -0.5)


def test_all_targets_is_1_9R_and_square_off():
    t = trade()
    feed(t, [121, 131])
    assert t.pnl == pytest.approx(19.0) and t.exit_reason == "T3"
    s = trade(side=-1, entry=100, sl=110, t1=90, t2=80, t3=70)
    s.opened = at(15, 14).isoformat()
    s.on_quote(q(95, at(15, 14) + timedelta(seconds=30)), at(15, 14) + timedelta(seconds=30))
    assert s.on_quote(q(96, at(15, 15)), at(15, 15)) and s.pnl == pytest.approx(4) and s.exit_reason == "square-off 15:15"


def test_executable_target_exact_one_tick_through():
    t = trade(book="executable")
    t.on_quote(q(110.1, at(10, 1)), at(10, 1))           # 110.1 - 110 = 0.0999... in floating point: must still fill
    assert t.t1hit


def test_executable_targets_need_trade_through_and_stops_exit_at_touch():
    t = trade(book="executable")
    t.on_quote(q(110.0, at(10, 1)), at(10, 1))                # touches T1 but does not trade through
    assert not t.t1hit
    t.on_quote(q(110.1, at(10, 2)), at(10, 2))
    assert t.t1hit and t.stop == 100
    t.on_quote(q(99.0, at(10, 3), spread=1.0), at(10, 3))     # BE stop: SL-M -> bid 98.5 minus 2 ticks
    assert t.status == "CLOSED"
    assert t.pnl == pytest.approx(0.4 * 10 + 0.6 * (98.5 - 0.2 - 100))


def test_executable_stop_never_better_than_stop():
    t = trade(book="executable")
    t.on_quote(q(89.9, at(10, 1), spread=0.0), at(10, 1))     # bid 89.9, minus slippage 89.7 (below the stop: kept)
    assert t.pnl == pytest.approx(89.7 - 100)


def test_costs_by_book():
    th, ex = trade(), trade(book="executable")
    for t in (th, ex):
        t.pnl, t.exit_value, t.orders = 10.0, 110.0, 2
    fee = futures_cost_points(100, 110, 1, D.date(), 65, 10, 2, 0.0)       # 10 whole lots (PAPER_LOTS)
    assert ex.net_pts() == pytest.approx(10 - fee)
    assert th.net_pts() == pytest.approx(10 - fee - 2 * 4 * 0.1)   # theoretical adds the backtests' 4 ticks/side


def test_overnight_trade_becomes_unresolved():
    t = trade()
    t.on_quote(q(101, at(14, 0)), at(14, 0))
    assert t.on_quote(q(105, at(9, 16, day=1)), at(9, 16, day=1))
    assert t.status == "UNRESOLVED" and "overnight" in t.flags


def test_outage_across_square_off_becomes_unresolved():
    t = trade()
    t.on_quote(q(101, at(15, 0)), at(15, 0))
    assert t.on_quote(q(102, at(15, 25)), at(15, 25))
    assert t.status == "UNRESOLVED" and "missed_square_off" in t.flags


def test_book_dedup_persistence_and_day_stats(tmp_path):
    store = Store(tmp_path / "p.db")
    book = PaperBook(store)
    assert book.open_trade(trade())
    assert not book.open_trade(trade())                       # same signal id in the same book: refused
    assert book.open_trade(trade(book="executable"))          # the other book may hold it
    assert len(PaperBook(store).open) == 2                    # reload after "restart"
    closed = book.on_quote("NIFTY", q(85, at(10, 1)), at(10, 1))
    assert len(closed) == 2
    st = book.day_stats(D.date(), "executable")
    assert st["trades"] == 1 and st["losses"] == 1 and st["r_sum"] < -1
