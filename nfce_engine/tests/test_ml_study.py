"""The ML study must be causal: changing the future must never change a feature, only the targets."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.ml_study import FEATURES, H, symbol_frame, target_before_stop  # noqa: E402

TZ = "Asia/Kolkata"


def bars(days=30, seed=1):
    rng = np.random.default_rng(seed)
    out, px = [], 1000.0
    for d in pd.bdate_range("2025-01-01", periods=days, tz=TZ):
        for t in pd.date_range(d + pd.Timedelta(hours=9, minutes=15), periods=75, freq="5min"):
            o = px
            c = o * (1 + rng.normal(0, 0.002))
            out.append((t, o, max(o, c) * 1.0005, min(o, c) * 0.9995, c, rng.lognormal(8, 0.3)))
            px = c
    return pd.DataFrame(out, columns=["time", "open", "high", "low", "close", "volume"]).set_index("time")


def test_features_never_see_the_future():
    b = bars()
    cut = b.index[len(b) // 2]
    f1 = symbol_frame(b)
    b2 = b.copy()
    after = b2.index > cut
    b2.loc[after, ["open", "high", "low", "close"]] *= 1.5          # rewrite the whole future
    b2.loc[after, "volume"] *= 3
    f2 = symbol_frame(b2)
    feat = [c for c in FEATURES if c in f1.columns]
    past = f1.index <= cut
    pd.testing.assert_frame_equal(f1.loc[past, feat], f2.loc[past, feat])
    near = past & (f1.index > cut - pd.Timedelta(minutes=5 * H))
    assert (f1.loc[near, "R60"].fillna(0) != f2.loc[near, "R60"].fillna(0)).any()   # the targets DO look ahead


def test_targets_only_use_bars_after_the_decision_and_stay_in_the_day():
    b = bars(days=3)
    f = symbol_frame(b)
    last = f.groupby("day").tail(H).index
    assert f.loc[last, "D60"].isna().all()                          # no 60-minute window crosses the close
    i = 10
    exp = np.sign(f.close.iloc[i + H] - f.close.iloc[i])
    assert f.D60.iloc[i] == exp


def test_target_before_stop_counts_stop_first_when_both_touch():
    idx = pd.date_range("2025-01-01 09:15", periods=20, freq="5min", tz=TZ)
    x = pd.DataFrame({"open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0, "volume": 1.0}, index=idx)
    f = symbol_frame(x)
    f["atr5"] = 1.0
    f.iloc[3, f.columns.get_loc("high")] = 101.5                     # both +1 and -1 touched in bar 3
    f.iloc[3, f.columns.get_loc("low")] = 98.5
    assert target_before_stop(f, np.array([0]))[0] == 0.0
    f.iloc[3, f.columns.get_loc("low")] = 99.5                       # only the target is touched
    assert target_before_stop(f, np.array([0]))[0] == 1.0
