import math

import pytest

from bridge.analytics import summarize
from bridge.providers import parse_upstox_chain
from bridge.rules import Signal, SignalError, evaluate
from conftest import make_payload


def summ(call=None, put=None, spot=25000.0, prev_missing=False):
    return summarize(parse_upstox_chain(make_payload(spot=spot, call=call, put=put, prev_missing=prev_missing), "X"),
                     window=5)


def buy(entry=25000, sl=24960, t1=25040, grade="A"):
    return Signal(symbol="NSE:NIFTY1!", side="BUY", entry=entry, sl=sl, t1=t1, grade=grade)


def sell(entry=25000, sl=25040, t1=24960, grade="A"):
    return Signal(symbol="NSE:NIFTY1!", side="SELL", entry=entry, sl=sl, t1=t1, grade=grade)


def test_buy_vetoed_when_flow_bearish_and_wall_in_path_is_building():
    s = summ(call={25050: (2_000_000, 500_000, 30.0)})            # +1.5M call ΔOI at 25050 -> bearish_lean
    assert s.flow in ("bearish", "bearish_lean")
    d = evaluate(buy(t1=25100), s, basis=0.0)
    assert d.action == "VETO" and any("25050" in r and "building" in r for r in d.reasons)


def test_buy_not_vetoed_when_wall_is_not_building():
    # bearish flow comes from 25300 (outside the path); the wall inside the path is losing call OI
    s = summ(call={25050: (2_000_000, 2_100_000, 30.0), 25200: (900_000, 100_000, 10.0)})
    d = evaluate(buy(t1=25100), s, basis=0.0)
    assert s.flow in ("bearish", "bearish_lean") and d.action == "PASS"


def test_buy_not_vetoed_when_wall_beyond_t1():
    s = summ(call={25300: (2_000_000, 500_000, 10.0)})
    assert evaluate(buy(t1=25100), s, basis=0.0).action == "PASS"


def test_buy_not_vetoed_when_flow_not_bearish():
    s = summ(call={25050: (2_000_000, 1_900_000, 30.0)}, put={24900: (900_000, 300_000, 20.0)})
    assert s.flow in ("bullish", "bullish_lean")
    assert evaluate(buy(t1=25100), s, basis=0.0).action == "PASS"


def test_boost_needs_strict_unwinding_against_the_trade():
    s = summ(put={24950: (600_000, 200_000, 20.0)})              # puts added, calls unchanged
    d = evaluate(buy(), s, basis=0.0)
    assert d.action == "PASS" and not d.boosted
    s2 = summ(put={24950: (600_000, 200_000, 20.0)}, call={25100: (100_000, 300_000, 20.0)})
    d2 = evaluate(buy(), s2, basis=0.0)
    assert d2.boosted and d2.grade_out == "A+"


def test_sell_mirror_veto_and_boost():
    s = summ(put={24950: (2_000_000, 500_000, 30.0)})            # put writing, wall at 24950 inside T1..entry
    assert evaluate(sell(t1=24900), s, basis=0.0).action == "VETO"
    s2 = summ(call={25050: (600_000, 200_000, 20.0)}, put={24900: (100_000, 300_000, 20.0)})
    d2 = evaluate(sell(), s2, basis=0.0)
    assert d2.action == "PASS" and d2.boosted


def test_unchecked_cases_never_pass_silently():
    assert evaluate(buy(), None, basis=0.0).action == "NO_DATA"
    assert evaluate(buy(), summ(), basis=None).action == "NO_DATA"            # no live futures quote
    assert evaluate(buy(), summ(prev_missing=True), basis=0.0).action == "NO_DATA"


def test_futures_prices_shifted_by_live_basis():
    # futures 25060 = spot 25000 + basis 60; T1 25110 -> spot 25050, so the building wall at 25050 is in the path
    s = summ(call={25050: (2_000_000, 500_000, 40.0)})
    assert evaluate(buy(entry=25060, sl=25010, t1=25110), s, basis=60.0).action == "VETO"
    assert evaluate(buy(entry=25060, sl=25010, t1=25110), s, basis=0.0).action == "PASS"   # wall below entry


def test_signal_from_indicator_json():
    raw = {"v": 2, "id": "NIFTY1!-5-1792310100000-L", "t": 1792310100000, "symbol": "NSE:NIFTY1!", "tf": "5",
           "side": "BUY", "entry": 24512.5, "sl": 24480.1, "t1": 24544.9, "t2": 24577.3, "t3": 24609.7,
           "score": 82, "grade": "A+", "oi": "Long build-up"}
    s = Signal.from_payload(raw)
    assert s.side == "BUY" and s.grade == "A+" and s.t3 == 24609.7 and s.sid.startswith("NIFTY1!") and s.bar_time_ms


@pytest.mark.parametrize("bad", [
    {"side": "BUY", "entry": 100, "sl": 100},                         # zero risk
    {"side": "BUY", "entry": 100, "sl": 101},                         # stop on the wrong side
    {"side": "SELL", "entry": 100, "sl": 99},
    {"side": "BUY", "entry": 100, "sl": 99, "t1": 99.5},              # target behind entry
    {"side": "BUY", "entry": 100, "sl": 99, "t1": 102, "t2": 101},    # targets out of order
    {"side": "BUY", "entry": float("nan"), "sl": 99},
    {"side": "BUY", "entry": "abc", "sl": 99},
    {"side": "BUY", "entry": 100, "sl": 50},                          # 50% risk: implausible
    {"side": "HOLD", "entry": 100, "sl": 99},
    {"side": "BUY", "sl": 99},
])
def test_invalid_signals_rejected(bad):
    with pytest.raises(SignalError):
        Signal.from_payload(bad)


def test_default_targets_and_r():
    s = Signal.from_payload({"side": "SELL", "entry": 100, "sl": 102})
    assert s.t1 == 98 and math.isclose(s.R, 2)
