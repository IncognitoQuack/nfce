import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nfce import costs  # noqa: E402
from nfce.engine import Trade  # noqa: E402
from nfce.stats import CostModel, block_bootstrap_mean, clopper_pearson, holm, report  # noqa: E402


def test_cost_module_identical_in_engine_and_bridge():
    other = ROOT.parent / "nfce_bridge" / "bridge" / "costs.py"
    if other.exists():
        assert other.read_bytes() == (ROOT / "nfce" / "costs.py").read_bytes()


def test_reproduces_independent_review_fee_table():
    """Review §4: Nifty 25,000 x 65 -> Rs 966.2155 (14.8649 pts); Bank 55,000 x 30 -> Rs 980.3542 (32.6785 pts)."""
    n = costs.futures_fees(25000, 25000, 1, 65, date(2026, 10, 18))
    b = costs.futures_fees(55000, 55000, 1, 30, date(2026, 10, 18))
    assert n.total == pytest.approx(966.2155, abs=1e-3) and n.total / 65 == pytest.approx(14.8649, abs=1e-4)
    assert b.total == pytest.approx(980.3542, abs=1e-3) and b.total / 30 == pytest.approx(32.6785, abs=1e-4)
    o = costs.option_fees(200, 200, 65, date(2026, 10, 18))
    assert o.total / 65 == pytest.approx(1.2003, abs=1e-4)                     # review: P200 -> 1.2003 premium pts


def test_dated_schedule_is_cheaper_before_april_2026():
    old = costs.futures_fees(25000, 25000, 1, 65, date(2024, 6, 3)).stt
    mid = costs.futures_fees(25000, 25000, 1, 65, date(2025, 6, 3)).stt
    new = costs.futures_fees(25000, 25000, 1, 65, date(2026, 6, 3)).stt
    assert old < mid < new and new == pytest.approx(812.5)


def test_short_side_pays_stt_on_entry_notional():
    long_ = costs.futures_fees(25000, 25100, 1, 65, date(2026, 6, 3))
    short = costs.futures_fees(25000, 24900, -1, 65, date(2026, 6, 3))
    assert long_.stt == pytest.approx(0.0005 * 25100 * 65) and short.stt == pytest.approx(0.0005 * 25000 * 65)


def test_more_orders_cost_more_and_amortise_over_lots():
    two = costs.futures_cost_points(25000, 25000, 1, date(2026, 6, 3), 65, 1, 2)
    four = costs.futures_cost_points(25000, 25000, 1, date(2026, 6, 3), 65, 1, 4)
    four10 = costs.futures_cost_points(25000, 25000, 1, date(2026, 6, 3), 65, 10, 4)
    assert four - two == pytest.approx(2 * 20 * 1.18 / 65) and four10 < four


def _t(day, pnl, R=10.0, side="L", entry=25000.0, orders=2):
    return Trade(pd.Timestamp(day, tz="Asia/Kolkata"), side, 70, False, entry, R, pnl, "Q", 5, None, "A", orders)


def test_report_dated_vs_current_and_intervals():
    trades = [_t("2024-06-03", 20), _t("2024-06-03", -10), _t("2026-06-03", 20), _t("2026-06-04", -10)]
    dated = report(trades, CostModel("dated", 65, 1, 0.0))
    cur = report(trades, CostModel("current", 65, 1, 0.0))
    assert dated["net_r"] > cur["net_r"]                          # 2024 trades were cheaper than today's schedule
    assert dated["days"] == 3 and dated["ci_day"][0] <= dated["net_r"] <= dated["ci_day"][1]


def test_block_bootstrap_is_wider_for_clustered_days():
    vals, iid, day = [], [], []
    for d in range(30):
        v = 1.0 if d % 2 else -1.0
        vals += [v] * 5
        day += [d] * 5
        iid += list(range(d * 5, d * 5 + 5))
    lo_b, hi_b = block_bootstrap_mean(vals, day)
    lo_i, hi_i = block_bootstrap_mean(vals, iid)
    assert (hi_b - lo_b) > 1.5 * (hi_i - lo_i)


def test_holm_and_clopper_pearson():
    rej = holm({"a": 0.001, "b": 0.02, "c": 0.04})
    assert rej == {"a": True, "b": True, "c": True}             # 0.001<=.0167, .02<=.025, .04<=.05
    assert holm({"a": 0.03, "b": 0.04}) == {"a": False, "b": False}
    lo, hi = clopper_pearson(8, 19)
    assert lo == pytest.approx(0.2025, abs=0.002) and hi == pytest.approx(0.6650, abs=0.002)   # review: 20.3-66.5%
