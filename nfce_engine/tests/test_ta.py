import statistics
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce import ta  # noqa: E402


def test_ema_seeded_with_sma_and_lags_linear_series():
    x = np.arange(1, 11, dtype=float)
    e = ta.ema(x, 3)
    assert np.isnan(e[:2]).all()
    assert e[2] == 2.0                                  # SMA of 1,2,3
    assert np.allclose(e[2:], x[2:] - 1)                # EMA(3) of a unit ramp lags by exactly 1


def test_rma_constant_and_seed():
    x = np.full(30, 7.0)
    assert np.allclose(ta.rma(x, 14)[13:], 7.0)
    y = np.arange(20, dtype=float)
    r = ta.rma(y, 5)
    assert r[4] == y[:5].mean()
    assert np.isclose(r[5], 0.2 * y[5] + 0.8 * r[4])


def test_stdev_is_population():
    rng = np.random.default_rng(1)
    x = rng.normal(size=50)
    s = ta.stdev(x, 20)
    assert np.isclose(s[-1], statistics.pstdev(x[-20:]))


def test_linreg_matches_polyfit_and_exact_line():
    t = np.arange(40, dtype=float)
    line = 2 * t + 5
    assert np.isclose(ta.linreg(line, 20, 0)[-1], line[-1])
    assert np.isclose(ta.linreg(line, 20, 1)[-1], line[-2])
    rng = np.random.default_rng(2)
    y = rng.normal(size=40).cumsum()
    b, a = np.polyfit(np.arange(20), y[-20:], 1)
    assert np.isclose(ta.linreg(y, 20, 0)[-1], a + b * 19)


def test_true_range_and_atr_by_hand():
    h = np.array([10.0, 12.0, 11.0])
    l = np.array([8.0, 9.0, 7.0])
    c = np.array([9.0, 11.0, 8.0])
    tr = ta.true_range(h, l, c, True)
    assert list(tr) == [2.0, 3.0, 4.0]          # bar 3: max(4, |11-11|, |7-11|) = 4
    assert np.isnan(ta.true_range(h, l, c, False)[0])
    a = ta.atr(h, l, c, 2)
    assert a[1] == 2.5 and a[2] == 0.5 * 4 + 0.5 * 2.5


def test_dmi_equal_up_and_down_moves_count_as_neither_despite_float_noise():
    """Golden parity, 22 Sep 2026 12:15 NIFTY1!: high +5.7 and low -5.7 in prices with one decimal. In float64,
    23385.7 - 23380.0 > 23360.1 - 23354.4 by 2e-12, which gave +DM = 5.7; TradingView (and the definition) gives 0."""
    h = np.array([23380.0, 23385.7])
    l = np.array([23360.1, 23354.4])
    assert (h[1] - h[0]) > (l[0] - l[1])                         # the float noise that caused the mismatch
    rng = np.random.default_rng(5)
    base = 23370.0 + np.cumsum(rng.normal(0, 3, 40)).round(1)
    hh = np.r_[base + 6, h]
    ll = np.r_[base - 6, l]
    hh[-2], ll[-2] = h[0], l[0]                                  # the bar before: high 23380.0, low 23360.1
    cc = np.r_[base, 23374.7, 23375.1][: len(hh)]
    plus, _, _ = ta.dmi(hh, ll, cc, 14, 14)
    plus0, _, _ = ta.dmi(hh[:-1], ll[:-1], cc[:-1], 14, 14)
    trur = ta.rma(ta.true_range(hh, ll, cc, False), 14)
    pdm_prev = plus0[-1] * trur[-2] / 100                        # rma(+DM) one bar earlier
    expected = 100 * (pdm_prev * 13 / 14) / trur[-1]             # +DM = 0 on the last bar
    assert plus[-1] == pytest.approx(expected, rel=1e-9)


def test_dmi_on_steady_uptrend():
    t = np.arange(80, dtype=float)
    h, l = 100 + t + 1, 100 + t - 1
    c = 100 + t
    plus, minus, adx = ta.dmi(h, l, c, 14, 14)
    assert plus[-1] > 40 and minus[-1] == 0 and adx[-1] > 95


def test_supertrend_direction_follows_trend():
    up = np.r_[np.linspace(100, 200, 60), np.linspace(200, 120, 60)]
    h, l = up + 1, up - 1
    _, d = ta.supertrend(h, l, up, 3.0, 10)
    assert d[55] == -1          # uptrend
    assert d[-1] == 1           # downtrend after the reversal
    assert set(np.unique(d)) <= {-1.0, 1.0}


def test_shift_and_highest():
    x = np.array([1.0, 3.0, 2.0, 5.0])
    assert np.isnan(ta.shift(x)[0]) and list(ta.shift(x)[1:]) == [1.0, 3.0, 2.0]
    assert list(ta.highest(x, 2)[1:]) == [3.0, 3.0, 5.0]
