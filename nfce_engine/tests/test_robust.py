import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce.robust import jitter, mean_range_change, shift, similarity  # noqa: E402

T0 = pd.Timestamp("2026-10-12 09:15", tz="Asia/Kolkata")
BAR = pd.Timedelta(minutes=5)


def frame(n=500):
    rng = np.random.default_rng(1)
    c = 25000 + np.cumsum(rng.normal(0, 5, n)).round(1)
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) + 3.0, "low": np.minimum(o, c) - 3.0, "close": c},
                        index=pd.date_range(T0, periods=n, freq="5min"))


def test_shift_is_bounded_tick_rounded_and_keeps_candle_geometry():
    b = frame()
    p = shift(b, 5, 0.1, seed=3)
    d = p["close"] - b["close"]
    assert d.abs().max() <= 0.5 + 1e-9                                # bounded: |shift| <= k ticks
    assert np.allclose((d / 0.1).round(), d / 0.1)                    # on the tick grid
    for c in ("open", "high", "low"):
        assert np.allclose(p[c] - b[c], d)                            # same shift for every price of a bar
    assert mean_range_change(b, p) == pytest.approx(0.0, abs=1e-9)


def test_jitter_is_bounded_and_reports_its_geometry_change():
    b = frame()
    p = jitter(b, 20, 0.1, seed=4)
    assert ((p - b).abs().max() <= 2.0 + 1e-9).all()
    assert (p["high"] >= p[["open", "close"]].max(axis=1)).all() and (p["low"] <= p[["open", "close"]].min(axis=1)).all()
    assert mean_range_change(b, p) > 0                                # the repair widens ranges: labelled, not hidden


def test_similarity_precision_recall_jaccard_with_timing_tolerance():
    base = [(T0, "L"), (T0 + 10 * BAR, "S"), (T0 + 30 * BAR, "L")]
    pert = [(T0 + BAR, "L"), (T0 + 10 * BAR, "L"), (T0 + 50 * BAR, "S")]
    s0 = similarity(base, pert, 0, BAR)
    assert s0["matched"] == 0 and s0["jaccard"] == 0.0
    s1 = similarity(base, pert, 1, BAR)                                # one bar late on the same side = same signal
    assert s1["matched"] == 1 and s1["precision"] == pytest.approx(1 / 3) and s1["recall"] == pytest.approx(1 / 3)
    assert s1["jaccard"] == pytest.approx(1 / 5)
    assert similarity(base, base, 0, BAR)["jaccard"] == 1.0
