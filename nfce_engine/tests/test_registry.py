import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce.registry import ALPHA_EXPERIMENT, judge_r1, judge_r2, judge_r3, one_sample, welch  # noqa: E402


def draws(n, mu, sd=1.0, seed=1):
    r = random.Random(seed)
    return [r.gauss(mu, sd) for _ in range(n)]


def test_alpha_is_split_across_the_four_confirmatory_experiments():
    assert abs(ALPHA_EXPERIMENT - 0.05 / 4) < 1e-12           # R1-R4 share one family (review round 3, M05)


def test_small_samples_are_inconclusive_not_pass():
    assert judge_r1(draws(50, 1.0), draws(50, 0.0), 0).result == "INCONCLUSIVE"
    assert judge_r2({"NIFTY": [(2024, 1.0, 1.0)] * 300}).result == "INCONCLUSIVE"        # one index only
    assert judge_r3(draws(120, 1.0), draws(60, 0.0)).result == "INCONCLUSIVE"            # 180 < 200 signals
    assert judge_r3(draws(200, 1.0), draws(20, 0.0)).result == "INCONCLUSIVE"             # too few vetoes


def test_r1_skips_above_ten_percent_make_it_inconclusive():
    v = judge_r1(draws(250, 0.5), draws(250, 0.0), skipped=40)
    assert v.result == "INCONCLUSIVE" and "skipped" in v.note


def test_r1_pass_and_fail():
    opt, fut = draws(400, 0.4, seed=2), draws(400, 0.0, seed=3)
    assert judge_r1(opt, fut, 5).result == "PASS"
    assert judge_r1(draws(400, 0.03, sd=0.1, seed=4), fut, 5).result == "FAIL"     # positive but below +0.10R


def test_r2_needs_every_check_on_both_indices():
    def rows(mu, seed):
        r = draws(300, mu, seed=seed)
        return [(2021 + i % 5, x, x * 1000) for i, x in enumerate(r)]
    assert judge_r2({"NIFTY": rows(0.5, 1), "BANKNIFTY": rows(0.5, 2)}).result == "PASS"
    v = judge_r2({"NIFTY": rows(0.5, 1), "BANKNIFTY": rows(0.0, 2)})
    assert v.result == "FAIL" and not v.checks["BANKNIFTY net R per trade"][2]


def test_r3_pass_requires_separation_and_positive_pass_book():
    assert judge_r3(draws(200, 0.5, seed=5), draws(60, -0.5, seed=6)).result == "PASS"
    v = judge_r3(draws(200, -0.1, seed=5), draws(60, -1.0, seed=6))         # veto helps, but PASS trades still lose
    assert v.result == "FAIL" and v.note == "delete the veto rule"


def test_statistics_helpers():
    m, t, p = one_sample([1.0, 2.0, 3.0])
    assert m == 2.0 and t > 3 and p < 0.05
    d, t, p = welch([1.0, 2.0, 3.0, 4.0], [0.0, 1.0, 2.0, 3.0])
    assert d == 1.0 and 0 < p < 0.5


def test_r4_paired_rule():
    from nfce.registry_r4 import R4_ALPHA, judge_r4
    assert abs(R4_ALPHA - 0.0125) < 1e-12
    assert judge_r4([(0.0, 0.1)] * 50).result == "INCONCLUSIVE"
    ex = draws(150, 0.0, seed=8)
    better = [(e, e + d) for e, d in zip(ex, draws(150, 0.15, sd=0.3, seed=9))]
    assert judge_r4(better).result == "PASS"
    same = [(e, e + d) for e, d in zip(ex, draws(150, 0.0, sd=0.3, seed=9))]
    assert judge_r4(same).result == "FAIL"


def test_r6_live_range_benchmark_scorer():
    import sqlite3
    import numpy as np
    import pandas as pd
    from tools.registry_eval_r6 import judge, load
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE range_forecasts (root TEXT, bar_close TEXT, model TEXT, ts TEXT, price REAL, q10 REAL,"
                " q50 REAL, q90 REAL, realized REAL)")
    rng = np.random.default_rng(5)
    days = pd.bdate_range("2026-10-21", periods=45)
    z = {0.1: -1.2816, 0.5: 0.0, 0.9: 1.2816}
    for d in days:
        for k in range(22):
            t = (d + pd.Timedelta(hours=9, minutes=45 + 15 * k)).tz_localize("Asia/Kolkata").isoformat()
            for root in ("NIFTY", "BANKNIFTY"):
                mu = -5.5 + 0.3 * rng.normal()
                y = mu + 0.3 * rng.normal()
                for model, bias in (("M1", 0.0), ("HAR", 0.15), ("ENS", 0.075)):
                    q = [mu + bias + 0.3 * z[a] for a in (0.1, 0.5, 0.9)]
                    con.execute("INSERT INTO range_forecasts VALUES (?,?,?,?,?,?,?,?,?)", (root, t, model, t, 25000, *q, y))
    v, lines = judge(load(con))
    text = "\n".join(lines)
    assert v == "JUDGED"
    assert "C1 calibrated: HOLDS" in text and "C3 ML vs linear (M1 vs HAR): HOLDS" in text
    assert "C4 ensemble: does not hold" in text                 # the average of a good and a worse model is not better
    few = load(con)
    few = few[few.day < few.day.min() + pd.Timedelta(days=10)]
    assert judge(few)[0].startswith("NOT YET")
