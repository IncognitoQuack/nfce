import math

import pytest

from bridge.analytics import flow_state, max_pain, summarize
from bridge.providers import StrikeRow, parse_upstox_chain
from conftest import make_payload


def test_parse_and_basic_summary():
    s = summarize(parse_upstox_chain(make_payload(spot=25010), "NSE_INDEX|Nifty 50"), window=5)
    assert s.step == 50 and s.atm_strike == 25000 and len(s.window_rows) == 11
    assert s.pcr_oi == 1.0 and s.atm_iv == 12.0 and s.expiry == "2026-10-27"
    assert s.doi_available and s.put_doi == 0 and s.call_doi == 0 and s.flow == "neutral"


def test_missing_previous_oi_is_unavailable_not_zero():
    s = summarize(parse_upstox_chain(make_payload(prev_missing=True), "X"))
    assert not s.doi_available and s.put_doi is None and s.flow == "unavailable" and s.pcr_doi is None


@pytest.mark.parametrize("side", ["call", "put"])
def test_one_sided_missing_previous_oi_is_unavailable(side):
    ch = parse_upstox_chain(make_payload(prev_missing=side), "X")
    row = ch.rows[0]
    assert (row.call_prev_oi is None) == (side == "call") and (row.put_prev_oi is None) == (side == "put")
    assert summarize(ch).flow == "unavailable"


def test_walls_and_flow():
    call = {25200: (900_000, 400_000, 30.0), 25100: (150_000, 100_000, 60.0)}   # +550k call ΔOI
    put = {24800: (700_000, 300_000, 25.0)}                                      # +400k put ΔOI
    s = summarize(parse_upstox_chain(make_payload(call=call, put=put), "X"), window=5)
    assert s.max_call_oi_strike == 25200 and s.max_put_oi_strike == 24800
    assert s.put_doi == 400_000 and s.call_doi == 550_000
    assert math.isclose(s.pcr_doi, 400_000 / 550_000) and s.flow == "neutral"   # 0.73 is between 0.7 and 1.43


@pytest.mark.parametrize("put,call,state", [
    (10, -10, "bullish"), (-10, 10, "bearish"), (10, 1, "bullish_lean"), (1, 10, "bearish_lean"),
    (10, 9, "neutral"), (-10, -10, "unwinding"), (10, 0, "bullish_lean"), (0, 10, "bearish_lean"),
    (-500_000, 0, "bearish_lean"), (0, -10, "bullish_lean"), (0, 0, "neutral"), (None, 5, "unavailable"),
])
def test_flow_quadrants(put, call, state):
    assert flow_state(put, call) == state


def test_max_pain_textbook():
    rows = [StrikeRow(strike=k, call_oi=c, put_oi=p) for k, c, p in
            [(100, 10, 50), (110, 20, 40), (120, 60, 10), (130, 50, 5)]]
    assert max_pain(rows) == 110


def test_synthetic_forward_is_information_only():
    call = {25000: (100_000, 100_000, 80.0)}
    put = {25000: (100_000, 100_000, 20.0)}
    s = summarize(parse_upstox_chain(make_payload(spot=25000, call=call, put=put), "X"))
    assert s.synth_forward == 25060
    assert not hasattr(s, "basis")          # the weekly synthetic forward is never used as the futures basis
