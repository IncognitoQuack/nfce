"""OVN v3: the parity forward and the strike it selects; everything else is v2's own code."""
import pandas as pd
import pytest

from tools import overnight_options as ovn
from tools import overnight_v3 as v3


def _snap(spot=22760.75, fwd=22785.0, expiry="2026-11-03", ks=range(22500, 23050, 50), drop_puts=()):
    rows = []
    for k in ks:
        intrinsic = fwd - k
        c_mid, p_mid = max(intrinsic, 0) + 150, max(-intrinsic, 0) + 150         # call - put = fwd - k exactly
        rows.append(dict(ts="2026-10-28T15:20:30", time="15:20:30", expiry=expiry, spot=spot, strike=float(k), typ="CE",
                         bid=c_mid - 0.5, ask=c_mid + 0.5, bid_qty=1000, ask_qty=1000, iv=15.0, ltp=c_mid))
        if k not in drop_puts:
            rows.append(dict(ts="2026-10-28T15:20:30", time="15:20:30", expiry=expiry, spot=spot, strike=float(k),
                             typ="PE", bid=p_mid - 0.5, ask=p_mid + 0.5, bid_qty=1000, ask_qty=1000, iv=15.0, ltp=p_mid))
    return pd.DataFrame(rows)


def test_parity_forward_recovers_the_forward_from_the_three_strikes_nearest_spot():
    assert v3.parity_forward(_snap(), "2026-11-03") == pytest.approx(22785.0)
    assert v3.parity_forward(_snap(), "2026-11-10") is None


def test_forward_uses_only_valid_pairs_and_none_when_there_are_none():
    s = _snap(drop_puts=(22750,))                     # one of the 3 nearest has no put: the other two still give F
    assert v3.parity_forward(s, "2026-11-03") == pytest.approx(22785.0)
    s2 = _snap(drop_puts=(22700, 22750, 22800))
    assert v3.parity_forward(s2, "2026-11-03") is None


def test_v3_centres_on_the_forward_where_v2_centres_on_the_frozen_spot():
    s = _snap()
    k_v2 = ovn.pick_strikes(s, "2026-11-03", atr=180.0)["K"]
    s3 = s.copy()
    s3["spot"] = v3.parity_forward(s, "2026-11-03")
    k_v3 = ovn.pick_strikes(s3, "2026-11-03", atr=180.0)["K"]
    assert (k_v2, k_v3) == (22750.0, 22800.0)          # 27 Oct's case: one strike apart


def test_score_v3_has_no_rows_while_recorded_days_precede_its_start(tmp_path):
    (tmp_path / "study_chain_20261027.db").touch()     # recorded days exist, but all before 28 Oct
    assert len(v3.score_v3(data=tmp_path)) == 0
    t = v3.score_v3(data=tmp_path / "none")            # no files at all: like v2, the start day is "missing data"
    assert list(t["status"]) == ["missing data (no chain file)"]
