"""Desk risk engine: honest marks, position Greeks, the scenario grid and exposure."""
import pytest

from bridge import desk_risk as rk

POS = {"symbol": "NIFTY 22750 CE", "key": "NSE_FO|1", "under_key": "NSE_INDEX|Nifty 50", "side": 1, "lots": 2,
       "rem_lots": 2, "lot_units": 65, "entry": 200.0}


def test_long_is_marked_at_the_bid_short_at_the_ask_and_last_is_flagged():
    t = rk.Tick(ltp=210.0, bid=209.0, ask=211.0)
    assert rk.mark_of(130, t) == (209.0, "bid") and rk.mark_of(-130, t) == (211.0, "ask")
    assert rk.mark_of(130, rk.Tick(ltp=210.0)) == (210.0, "last")
    assert rk.mark_of(130, None) == (None, "none")
    r = rk.position_risk("5L", POS, rk.Tick(ltp=210.0), rk.Tick(ltp=22760.0))
    assert r.unrealized == pytest.approx(10.0 * 130) and "last trade" in r.notes[0]


def test_position_greeks_scale_with_signed_units():
    opt = rk.Tick(bid=209.0, ask=211.0, delta=0.55, gamma=0.0004, vega=12.0, theta=-9.0)
    r = rk.position_risk("5L", POS, opt, rk.Tick(ltp=22760.0))
    assert (r.units, r.delta, r.vega, r.theta) == (130, pytest.approx(71.5), pytest.approx(1560.0), pytest.approx(-1170.0))
    assert rk.mark_of(-130, opt) == (211.0, "ask")          # a short (not held by any account) closes at the ask


def test_a_put_bought_on_a_sell_signal_is_long_and_loses_when_its_premium_falls():
    # 28 Oct: SENSEX 72700 PE bought at 402.15 on a SELL signal (side -1) showed as a short with the P&L flipped
    put = POS | {"symbol": "SENSEX 72700 PE", "side": -1, "lots": 2, "rem_lots": 2, "lot_units": 20, "entry": 402.15}
    r = rk.position_risk("5L", put, rk.Tick(bid=357.55, ask=360.0, delta=-0.45), rk.Tick(ltp=72787.0))
    assert (r.units, r.mark, r.mark_source) == (40, 357.55, "bid")
    assert r.unrealized == pytest.approx((357.55 - 402.15) * 40) and r.unrealized < 0
    assert r.delta == pytest.approx(-0.45 * 40)              # a long put is short delta


def test_scenario_grid_is_the_second_order_greeks_sum_and_lists_exclusions():
    opt = rk.Tick(bid=209.0, ask=211.0, delta=0.5, gamma=0.001, vega=10.0)
    a = rk.position_risk("5L", POS, opt, rk.Tick(ltp=20000.0))
    b = rk.position_risk("5L", POS | {"symbol": "TCS 2520 CE"}, rk.Tick(bid=20.0), rk.Tick(ltp=2500.0))  # no Greeks
    g = rk.scenario_grid([a, b])
    ds = 20000 * 0.01
    assert g["grid"][(0.01, 0.0)] == pytest.approx(130 * (0.5 * ds + 0.5 * 0.001 * ds * ds))
    assert g["grid"][(0.0, 5.0)] == pytest.approx(130 * 10.0 * 5)
    assert g["included"] == 1 and g["excluded"] == ["TCS 2520 CE"]


def test_exposure_totals_by_underlying():
    opt = rk.Tick(bid=200.0, delta=0.5, gamma=0.0, vega=1.0, theta=-2.0)
    a = rk.position_risk("5L", POS, opt, rk.Tick(ltp=20000.0))
    e = rk.exposure([a])
    assert e["by_underlying"]["NSE_INDEX|Nifty 50"]["delta_rs"] == pytest.approx(65 * 20000)
    assert e["total"]["premium"] == pytest.approx(200 * 130) and e["total"]["unrealized"] == pytest.approx(0.0)
