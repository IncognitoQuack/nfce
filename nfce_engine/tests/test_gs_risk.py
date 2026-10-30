"""gs/risk.py: regime map, sizing, portfolio caps, clusters, DG / day-loss / drawdown latches and their persistence."""
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gs import risk as rk  # noqa: E402

E = 500_000.0


def fresh(day="2026-10-27", eq=E):
    return rk.start_day(rk.RiskState("SIP"), day, eq)


def test_regime_map():
    assert rk.regime_multiplier(15.0, 0.05) == 1.0
    assert rk.regime_multiplier(22.0, 0.05) == 0.5
    assert rk.regime_multiplier(26.0, 0.0) == 0.25 and rk.regime_multiplier(26.0, 0.0, short_vol=True) == 0.0
    assert rk.regime_multiplier(16.0, 0.25) == 0.25 and rk.regime_multiplier(16.0, 0.25, True) == 0.0
    assert rk.regime_multiplier(None, 0.0) == 0.0 and rk.regime_multiplier(float("nan"), 0.0) == 0.0


def test_cash_sizing_by_risk_ticket_and_fees():
    # equity 5 L -> b = 1,250; stop 10 + 0.25 x ATR 20 = 15 + friction 0.5 + fees -> ~79 shares by risk,
    # but the Rs 1 L ticket at Rs 1,500 allows only 66
    fee = lambda q: 40.0 / q                                       # noqa: E731  Rs 40 brokerage spread over q
    q, L = rk.cash_qty(1500.0, 10.0, 20.0, E, 1.0, 0.5, fee)
    assert q == 66 and q * L <= 1250
    q2, L2 = rk.cash_qty(200.0, 10.0, 20.0, E, 1.0, 0.5, fee)        # cheap stock: risk binds, fees counted at q
    assert q2 * L2 <= 1250 and (q2 + 1) * (15.5 + 40 / (q2 + 1)) > 1250
    assert rk.cash_qty(1500.0, 10.0, 20.0, E, 0.25, 0.5, fee)[0] == 17          # quarter size in high VIX
    assert rk.cash_qty(1500.0, 10.0, 20.0, E, 0.0, 0.5, fee)[0] == 0
    assert rk.cash_qty(1500.0, 10.0, 20.0, E, 1.0, 0.5, fee, depth_cap=12)[0] == 12


def cand(inst="A", notional=60_000.0, sector="bank"):
    return rk.Exposure(inst, notional, 0.0, sector)


def test_portfolio_caps_reduce_or_reject():
    st = fresh()
    book = rk.BookView(E)
    q, why = rk.approve_cash(cand(), 1000.0, 60, 20.0, book, st)
    assert q == 60 and why == ()
    # cash stress cap 1% = 5,000: 4,000 already at risk -> room for 50 shares at Rs 20 each
    held = rk.Exposure("B", 50_000.0, 4_000.0, "it")
    q, why = rk.approve_cash(cand(), 1000.0, 60, 20.0, rk.BookView(E, (held,)), st)
    assert q == 50 and "reduced by cash stress" in why
    # one stock <= 20% of equity
    big = rk.Exposure("A", 95_000.0, 100.0, "bank")
    q, _ = rk.approve_cash(cand(), 1000.0, 60, 1.0, rk.BookView(E, (big,)), st)
    assert q == 5


def test_max_open_and_net_and_sector_caps():
    st = fresh()
    four = tuple(rk.Exposure(f"S{i}", 10_000.0, 10.0, f"sec{i}") for i in range(4))
    assert rk.approve_cash(cand(), 1000.0, 10, 1.0, rk.BookView(E, four), st) == (0, ("max open positions",))
    longs = (rk.Exposure("L1", 100_000.0, 10.0, "x"), rk.Exposure("L2", 100_000.0, 10.0, "y"),
             rk.Exposure("L3", 40_000.0, 10.0, "z"))
    q, _ = rk.approve_cash(cand("N", 10_000.0, "w"), 1000.0, 50, 1.0, rk.BookView(E, longs), st)
    assert q == 10                                                    # net long cap 50% = 2.5 L
    q, _ = rk.approve_cash(cand("N", -10_000.0, "w"), 1000.0, 50, 1.0, rk.BookView(E, longs), st)
    assert q == 50                                                    # a short reduces net exposure
    sec = (rk.Exposure("B1", 100_000.0, 10.0, "bank"), rk.Exposure("B2", 45_000.0, 10.0, "bank"))
    assert rk.approve_cash(cand("B3"), 1000.0, 50, 1.0, rk.BookView(E, sec), st)[0] == 5   # sector 30%


def test_pending_partial_fills_count_at_requested_size():
    """A pending intent is an exposure at its full requested size: a partial fill cannot open room."""
    st = fresh()
    pending = rk.Exposure("A", 90_000.0, 1_500.0, "bank")            # requested 90k, only 20k filled so far
    q, _ = rk.approve_cash(cand("A"), 1000.0, 60, 20.0, rk.BookView(E, (pending,)), st)
    assert q == 10                                                    # stock cap 1 L - 90k


def test_stale_marks_block_new_entries():
    st = fresh()
    stale = rk.Exposure("Z", 10_000.0, 100.0, "x", stale=True)
    assert rk.approve_cash(cand(), 1000.0, 10, 1.0, rk.BookView(E, (stale,)), st)[0] == 0
    ok, why = rk.approve_option(rk.Exposure("OVN", kind="option", reserve=4000.0, overnight=True, short_vol=True),
                                rk.BookView(1_000_000.0, (stale,)), rk.start_day(rk.RiskState("OVN"), "d", 1e6), 5000)
    assert not ok and "no valid mark" in why[0]


def test_clusters_join_same_sector_and_high_correlation():
    xs = [rk.Exposure("A", sector="bank"), rk.Exposure("B", sector="bank"), rk.Exposure("C", sector="it"),
          rk.Exposure("D", sector="auto")]
    cl = rk.clusters(xs, {("C", "D"): 0.75})
    assert cl["A"] == cl["B"] and cl["C"] == cl["D"] and cl["A"] != cl["C"]
    st = fresh()
    held = (rk.Exposure("C", 20_000.0, 2_400.0, "it"),)
    q, why = rk.approve_cash(cand("D", 20_000.0, "auto"), 1000.0, 20, 20.0, rk.BookView(E, held, {("C", "D"): 0.8}), st)
    assert q == 5 and "reduced by cluster" in why                     # cluster cap 0.5% = 2,500


def test_option_caps_budget_overnight_and_short_vol():
    st = rk.start_day(rk.RiskState("OVN"), "2026-10-26", 1_000_000.0)
    s = rk.Exposure("OVN-1", kind="option", reserve=4_632.0, overnight=True, short_vol=True)
    assert rk.approve_option(s, rk.BookView(1e6), st, 5000.0) == (True, ())
    assert not rk.approve_option(s, rk.BookView(1e6), st, 2500.0)[0]                 # half size: one lot too big
    other = rk.Exposure("RANGE-1", kind="option", reserve=1_000.0, short_vol=True)
    ok, why = rk.approve_option(s, rk.BookView(1e6, (other,)), st, 5000.0)
    assert not ok and "cap: short-volatility cap" in why


def test_dg_latch_per_book_and_fees_count():
    st = fresh()                                                      # r0 = 1,250 -> DG arms at H >= 2,500
    st = rk.update(st, 2_000.0, E + 2_000)
    assert rk.can_enter(st)[0]
    st = rk.update(st, 2_600.0, E + 2_600)
    st = rk.update(st, 1_400.0, E + 1_400)                            # 1,400 > 0.5 x 2,600
    assert rk.can_enter(st)[0]
    st = rk.update(st, 1_300.0, E + 1_300)                            # = 0.5 x 2,600
    assert rk.can_enter(st) == (False, "DG latch") and st.dg_peak == 2_600.0
    other = fresh()                                                   # another book is not latched
    assert rk.can_enter(other)[0]


def test_day_loss_latch_uses_marks_and_reserves_and_resets_next_day():
    st = fresh()
    st = rk.update(st, -1_000.0, E - 7_600)                           # realized only -1k, but equity -7.6k (1.52%)
    assert rk.can_enter(st) == (False, "day-loss latch")
    assert rk.can_enter(rk.start_day(st, "2026-10-28", E - 7_600))[0]


def test_drawdown_pause_survives_new_days_and_restarts_until_review():
    st = fresh()
    st = rk.update(st, 0.0, E + 10_000)
    st = rk.start_day(st, "2026-10-28", E + 10_000)
    for day in ("2026-10-29", "2026-10-30", "2026-11-02"):          # 510k -> 483k: 5.3% below the high
        st = rk.start_day(st, day, st.start_equity - 9_000)
        st = rk.update(st, 0.0, st.start_equity)
    assert st.paused and rk.can_enter(st) == (False, "paused (drawdown)")
    restored = rk.RiskState.from_dict(st.to_dict())                   # persisted and reloaded
    assert restored == st and rk.can_enter(rk.start_day(restored, "2026-11-03", 490_000))[0] is False
    assert rk.can_enter(rk.review_resume(restored, 490_000))[0]


def test_a_restart_within_the_day_keeps_the_latches():
    st = rk.update(fresh(), -8_000.0, E - 8_000)
    assert rk.start_day(st, "2026-10-27", E - 8_000) == st
