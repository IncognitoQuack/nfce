"""gs/costs.py and gs/ledger.py: per-fill fees by date, and cash / short / credit examples reconciled to the paisa."""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gs import costs as gc  # noqa: E402
from gs import ledger as lg  # noqa: E402
from gs.types import ExecutionEvent  # noqa: E402
from nfce import costs as frozen  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
T = datetime(2026, 10, 27, 9, 35, tzinfo=IST)
D = date(2026, 10, 27)
PAISA = 0.005


def fill(i, side, qty, px, fee, inst="X", t=T):
    return ExecutionEvent.new(f"in-{inst}", i, t + timedelta(seconds=i), "fill", instrument_id=inst, side=side,
                              qty=qty, price=px, fee=fee)


# ---------------------------------------------------------------- fees
def test_equity_fill_fees_by_hand():
    buy = gc.equity_fill_fee(1, 1000.0, 100, D)
    v = 100_000.0
    assert buy.stt == 0 and buy.stamp == pytest.approx(3.0) and buy.brokerage == 20.0
    assert buy.total == pytest.approx(20 + 0.0000322 * v + 1e-6 * v + 3.0 + 0.18 * (20 + 0.0000322 * v + 1e-6 * v))
    sell = gc.equity_fill_fee(-1, 1000.0, 100, D)
    assert sell.stt == pytest.approx(25.0) and sell.stamp == 0
    assert 8.0 < gc.round_trip_equity_bp(1000.0, 100, D) < 8.6          # ~8.3 bp at a Rs 1 L ticket (Rs 40 brokerage = 4 bp)


def test_fill_fees_add_up_to_the_frozen_round_trips():
    for when in (date(2024, 6, 3), date(2026, 10, 27)):
        a = gc.option_fill_fee(1, 120.0, 65, when) + gc.option_fill_fee(-1, 95.0, 65, when)
        assert a.total == pytest.approx(frozen.option_fees(120.0, 95.0, 65, when).total, abs=1e-9)
        f = gc.futures_fill_fee(1, 22600.0, 65, when) + gc.futures_fill_fee(-1, 22650.0, 65, when)
        assert f.total == pytest.approx(frozen.futures_fees(22600.0, 22650.0, 1, 65, when).total, abs=1e-9)


def test_fees_follow_the_fill_date_schedule():
    old = gc.option_fill_fee(-1, 100.0, 65, date(2026, 3, 31))
    new = gc.option_fill_fee(-1, 100.0, 65, date(2026, 4, 1))
    assert old.stt == pytest.approx(0.001 * 6500) and new.stt == pytest.approx(0.0015 * 6500)
    with pytest.raises(ValueError):
        gc.equity_fill_fee(1, 100.0, 0, D)


# ---------------------------------------------------------------- ledger
def test_cash_long_round_trip_reconciles():
    f1, f2 = gc.equity_fill_fee(1, 1000.0, 100, D).total, gc.equity_fill_fee(-1, 1010.0, 100, D).total
    L = lg.Ledger.new("SIP", 500_000)
    L = lg.apply_event(L, fill(0, 1, 100, 1000.0, f1))
    assert lg.equity(L, {"X": 1005.0}) == pytest.approx(500_000 + 500 - f1, abs=PAISA)
    L = lg.apply_event(L, fill(1, -1, 100, 1010.0, f2))
    assert L.open_positions() == {} and L.realized == pytest.approx(1000.0)
    assert lg.net_pnl(L, {}) == pytest.approx(1000.0 - f1 - f2, abs=PAISA) == pytest.approx(L.realized_net, abs=PAISA)
    assert L.day_realized_net == pytest.approx(1000.0 - f1 - f2, abs=PAISA)


def test_cash_short_reconciles_and_loses_when_price_rises():
    L = lg.Ledger.new("SIP", 500_000)
    L = lg.apply_event(L, fill(0, -1, 50, 2000.0, 30.0))
    assert L.cash == pytest.approx(500_000 + 100_000 - 30) and L.positions["X"].qty == -50
    assert lg.net_pnl(L, {"X": 2010.0}) == pytest.approx(-500 - 30, abs=PAISA)
    L = lg.apply_event(L, fill(1, 1, 50, 2010.0, 25.0))
    assert L.realized == pytest.approx(-500.0) and lg.net_pnl(L, {}) == pytest.approx(-555.0, abs=PAISA)


def test_credit_iron_fly_reconciles_at_max_loss():
    """Wings bought first, shorts sold; spot then rallies past the call wing: loss = (W - credit) x qty + fees."""
    q = 65
    legs = [("CW", 1, 138.85), ("PW", 1, 101.55), ("SC", -1, 287.0), ("SP", -1, 191.45)]
    L = lg.Ledger.new("OVN", 1_000_000)
    fees = 0.0
    for i, (k, s, p) in enumerate(legs):
        f = gc.option_fill_fee(s, p, q, D).total
        fees += f
        L = lg.apply_event(L, fill(i, s, q, p, f, inst=k))
    credit = 287.0 + 191.45 - 138.85 - 101.55
    assert L.cash == pytest.approx(1_000_000 + credit * q - fees, abs=PAISA)
    # at expiry-like marks with spot 23,400: SC 750, CW 450, puts worthless; W = 300
    marks = {"CW": 450.0, "PW": 0.0, "SC": 750.0, "SP": 0.0}
    assert lg.net_pnl(L, marks) == pytest.approx(-(300 - credit) * q - fees, abs=PAISA)


def test_fills_apply_once_and_partial_closes_keep_the_average():
    L = lg.Ledger.new("SIP", 100_000)
    e = fill(0, 1, 30, 100.0, 1.0)
    L = lg.apply_event(lg.apply_event(L, e), e)                           # replayed twice
    assert L.positions["X"].qty == 30 and L.fees == 1.0
    L = lg.apply_event(L, fill(1, 1, 10, 104.0, 1.0))
    assert L.positions["X"].avg_price == pytest.approx(101.0)
    L = lg.apply_event(L, fill(2, -1, 20, 103.0, 1.0))
    assert L.positions["X"].qty == 20 and L.positions["X"].avg_price == pytest.approx(101.0)
    assert L.realized == pytest.approx(40.0)
    L = lg.apply_event(L, fill(3, -1, 30, 99.0, 1.0))                     # flips to short 10 at 99
    assert L.positions["X"].qty == -10 and L.positions["X"].avg_price == 99.0
    assert L.realized == pytest.approx(40.0 - 40.0)


def test_non_fill_events_do_not_move_cash():
    L = lg.Ledger.new("SIP", 100_000)
    x = ExecutionEvent.new("in-X", 0, T, "expire", reason="no fill in 180 s")
    L2 = lg.apply_event(L, x)
    assert L2.cash == L.cash and x.exec_id in L2.applied


def test_unresolved_positions_have_no_point_equity_only_bounds():
    L = lg.Ledger.new("OVN", 1_000_000)
    L = lg.apply_event(L, fill(0, -1, 65, 200.0, 20.0, inst="SC"))
    L = lg.mark_unresolved(L, "SC")
    assert lg.equity(L, {"SC": 150.0}) is None                            # a stale mark cannot certify anything
    lo, hi = lg.equity_bounds(L, {"SC": 150.0}, worst={"SC": 500.0}, best={"SC": 0.0})
    assert lo == pytest.approx(1_000_000 + 13_000 - 20 - 500 * 65) and hi == pytest.approx(1_000_000 + 13_000 - 20)
    with pytest.raises(KeyError):
        lg.equity_bounds(L, {}, worst={})
    L = lg.apply_event(L, fill(1, 1, 65, 210.0, 20.0, inst="SC"))         # closed later: resolved
    assert "SC" not in L.unresolved and lg.equity(L, {}) == pytest.approx(1_000_000 - 650 - 40)


def test_reserves_and_missing_marks():
    L = lg.with_reserve(lg.Ledger.new("OVN", 1_000_000), "ovn-1", 4631.53)
    assert L.reserved == pytest.approx(4631.53)
    assert lg.release_reserve(L, "ovn-1").reserved == 0
    with pytest.raises(ValueError):
        lg.with_reserve(L, "x", -1)
    L = lg.apply_event(L, fill(0, 1, 10, 50.0, 0.0))
    assert lg.equity(L, {}) is None


def test_a_new_day_restarts_the_realized_day_pnl():
    L = lg.apply_event(lg.Ledger.new("SIP", 100_000), fill(0, 1, 10, 100.0, 5.0))
    L = lg.start_day(L, "2026-10-28")
    nxt = T.replace(day=28)
    L = lg.apply_event(L, fill(1, -1, 10, 103.0, 5.0, t=nxt))
    assert L.day_realized_net == pytest.approx(30.0 - 5.0) and L.realized_net == pytest.approx(30.0 - 10.0)
