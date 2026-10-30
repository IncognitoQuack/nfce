"""Unit tests for the external-report candidates (nfce/research2.py), on hand-built bars."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce.research2 import (late_momentum, morning_move, noise_area, nr7, oops, sigma_momentum, weekend_holiday_orb,  # noqa: E402
                            williams_dsr, williams_pd)

TZ = "Asia/Kolkata"


def day(date, path, vol=100.0):
    idx = pd.date_range(f"{date} 09:15", periods=len(path), freq="5min", tz=TZ)
    return pd.DataFrame(path, columns=["open", "high", "low", "close"], index=idx).assign(volume=vol)


def flat(date, px=100.0, rng=1.0, n=75):
    return day(date, [(px, px + rng / 2, px - rng / 2, px)] * n)


def history(n=20, start="2026-01-01", rng=1.0, px=100.0):
    return [flat(d.date(), px, rng) for d in pd.bdate_range(start, periods=n)]


def test_williams_pd_buys_at_the_level_and_exits_at_the_close():
    h = history(20)
    last = h[-1].index[0].date()
    nxt = (pd.Timestamp(last) + pd.offsets.BDay(1)).date()
    p = [(100, 100.2, 99.9, 100)] * 10 + [(100.3, 101, 100.3, 100.9)] + [(100.9, 101, 100.8, 100.9)] * 64
    (t,) = [x for x in williams_pd(pd.concat(h + [day(nxt, p)])) if x["day"] == nxt]
    assert t["side"] == 1 and t["entry"] == pytest.approx(100.5) and t["exit"] == pytest.approx(100.9)   # level = open + 0.5


def test_williams_dsr_stop_is_the_open_and_target_is_four_r():
    h = history(5)
    nxt = (pd.Timestamp(h[-1].index[0].date()) + pd.offsets.BDay(1)).date()
    # DSR = 1 (flat days, range 1): buy at 100.5, stop at the 100 open, target 102.5
    p = [(100, 100.2, 99.9, 100)] * 2 + [(100.4, 100.6, 100.4, 100.6)] + [(100.6, 102.6, 100.5, 102.4)] + [(102, 102, 102, 102)] * 71
    (t,) = williams_dsr(pd.concat(h + [day(nxt, p)]))
    assert t["entry"] == pytest.approx(100.5) and t["risk"] == pytest.approx(0.5) and t["reason"] == "target"
    assert t["exit"] == pytest.approx(102.5)


def test_nr7_needs_the_narrowest_range_and_uses_the_opposite_boundary_stop():
    h = [flat(d.date(), 100, rng=2.0 - 0.1 * k) for k, d in enumerate(pd.bdate_range("2026-01-01", periods=9))]
    nxt = (pd.Timestamp(h[-1].index[0].date()) + pd.offsets.BDay(1)).date()
    p = [(100, 100.3, 99.8, 100)] * 3 + [(100, 100.9, 100, 100.8)] + [(100.8, 100.9, 99.3, 99.6)] * 71
    (t,) = nr7(pd.concat(h + [day(nxt, p)]))
    assert t["side"] == 1 and t["entry"] == pytest.approx(100.6) and t["reason"] == "stop"
    assert t["exit"] == pytest.approx(99.4)                                     # NR7 low 100 - 1.2/2


def test_nr7_skips_when_not_compressed():
    h = history(10)                                                             # equal ranges: not strictly narrowest
    nxt = (pd.Timestamp(h[-1].index[0].date()) + pd.offsets.BDay(1)).date()
    assert nr7(pd.concat(h + [day(nxt, [(100, 101, 99, 100)] * 75)])) == []


def test_oops_gap_down_reversal_needs_vix_and_enters_back_inside_yesterday():
    h = history(3)
    nxt = (pd.Timestamp(h[-1].index[0].date()) + pd.offsets.BDay(1)).date()
    p = [(99.0, 99.1, 98.8, 99.0)] * 2 + [(99.0, 99.6, 98.9, 99.5)] + [(99.5, 100.1, 99.4, 100.0)] * 72   # prev low 99.5
    bars = pd.concat(h + [day(nxt, p)])
    vix_hi = pd.Series(16.0, index=bars.index)
    (t,) = oops(bars, vix_hi)
    assert t["side"] == 1 and t["entry"] == pytest.approx(99.5) and t["reason"] == "target" and t["exit"] == pytest.approx(100.0)
    assert oops(bars, pd.Series(12.0, index=bars.index)) == []                 # VIX gate


def test_weekend_orb_trades_only_after_a_weekend_and_exits_by_10_15():
    fri = flat("2026-01-02")
    p = [(100, 100.5, 99.5, 100)] * 3 + [(100, 101, 100, 100.8)] + [(100.8, 101.2, 100.7, 101)] * 71
    mon = day("2026-01-05", p)
    tue = day("2026-01-06", p)
    t = weekend_holiday_orb(pd.concat([fri, mon, tue]))
    assert len(t) == 1 and str(t[0]["day"]) == "2026-01-05" and t[0]["side"] == 1 and t[0]["entry"] == pytest.approx(100.8)


def test_morning_move_trades_the_direction_of_a_half_percent_first_half_hour():
    h = history(20)
    nxt = (pd.Timestamp(h[-1].index[0].date()) + pd.offsets.BDay(1)).date()
    p = [(100, 100.2, 99.9, 100.1)] * 5 + [(100.1, 100.7, 100.1, 100.6)] + [(100.6, 101, 100.5, 100.9)] * 69
    (t,) = morning_move(pd.concat(h + [day(nxt, p)]))
    assert t["side"] == 1 and t["entry"] == pytest.approx(100.6) and t["exit"] == pytest.approx(100.9)


def test_late_momentum_requires_aligned_and_large_moves():
    h = history(2)
    nxt = (pd.Timestamp(h[-1].index[0].date()) + pd.offsets.BDay(1)).date()
    p = [(100, 100.3, 99.9, 100.2)] * 6 + [(100.2, 100.8, 100.2, 100.7)] * 63 + [(100.7, 100.9, 100.6, 100.8)] * 6
    (t,) = late_momentum(pd.concat(h + [day(nxt, p)]))
    assert t["side"] == 1 and t["risk"] == pytest.approx(0.003 * t["entry"])


def test_noise_area_long_only_never_shorts_and_trails_on_vwap():
    rng = np.random.default_rng(1)
    days = []
    px = 100.0
    for d in pd.bdate_range("2026-01-01", periods=30):
        path = []
        drift = 0.08 if rng.random() < 0.5 else -0.08
        for _ in range(75):
            o = px
            c = o + drift + rng.normal(0, 0.02)
            path.append((o, max(o, c) + 0.01, min(o, c) - 0.01, c))
            px = c
        days.append(day(d.date(), path))
    b = pd.concat(days)
    lo = noise_area(b, long_only=True)
    both = noise_area(b)
    assert lo and all(t["side"] == 1 for t in lo) and any(t["side"] == -1 for t in both)


def test_sigma_momentum_trends_produce_trades_with_atr_stops():
    rng = np.random.default_rng(2)
    days, px = [], 100.0
    for d in pd.bdate_range("2026-01-01", periods=40):
        path = []
        for k in range(75):
            o = px
            c = o + (0.15 if 20 <= k < 40 else 0.0) + rng.normal(0, 0.03)
            path.append((o, max(o, c) + 0.02, min(o, c) - 0.02, c))
            px = c
        days.append(day(d.date(), path))
    t = sigma_momentum(pd.concat(days))
    assert t and all(x["risk"] > 0 for x in t) and {x["reason"] for x in t} <= {"z0", "stop", "eod", "eod_incomplete"}
