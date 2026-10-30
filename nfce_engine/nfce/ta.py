"""TradingView-compatible indicator maths (Pine v6 semantics), on numpy float arrays with NaN for `na`.

Each function follows the reference implementation in the Pine Script v6 manual, including how
moving averages are seeded (RMA/EMA start from an SMA of the first `length` values).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

nan = np.nan


def _arr(x) -> np.ndarray:
    return np.asarray(x, dtype=float)


def shift(x, n: int = 1) -> np.ndarray:
    x = _arr(x)
    out = np.full_like(x, nan)
    if n < len(x):
        out[n:] = x[:-n] if n > 0 else x
    return out


def sma(x, n: int) -> np.ndarray:
    return pd.Series(_arr(x)).rolling(n, min_periods=n).mean().to_numpy()


def rolling_sum(x, n: int) -> np.ndarray:
    return pd.Series(_arr(x)).rolling(n, min_periods=n).sum().to_numpy()


def stdev(x, n: int) -> np.ndarray:
    """ta.stdev (biased / population estimate, Pine default)."""
    return pd.Series(_arr(x)).rolling(n, min_periods=n).std(ddof=0).to_numpy()


def highest(x, n: int) -> np.ndarray:
    return pd.Series(_arr(x)).rolling(n, min_periods=n).max().to_numpy()


def lowest(x, n: int) -> np.ndarray:
    return pd.Series(_arr(x)).rolling(n, min_periods=n).min().to_numpy()


def _seeded(x, n: int, alpha: float) -> np.ndarray:
    """sum := na(sum[1]) ? ta.sma(src, n) : alpha * src + (1 - alpha) * sum[1]"""
    x = _arr(x)
    s = sma(x, n)
    out = np.full_like(x, nan)
    prev = nan
    for i in range(len(x)):
        cur = s[i] if np.isnan(prev) else alpha * x[i] + (1 - alpha) * prev
        out[i] = cur
        prev = cur
    return out


def rma(x, n: int) -> np.ndarray:
    return _seeded(x, n, 1.0 / n)


def ema(x, n: int) -> np.ndarray:
    return _seeded(x, n, 2.0 / (n + 1))


def true_range(high, low, close, handle_na: bool) -> np.ndarray:
    h, l, pc = _arr(high), _arr(low), shift(close)
    tr = np.fmax(h - l, np.fmax(np.abs(h - pc), np.abs(l - pc)))
    first = np.isnan(pc)
    tr[first] = (h - l)[first] if handle_na else nan
    return tr


def atr(high, low, close, n: int) -> np.ndarray:
    """ta.atr = ta.rma(ta.tr(true), n)"""
    return rma(true_range(high, low, close, True), n)


def fixnan(x) -> np.ndarray:
    return pd.Series(_arr(x)).ffill().to_numpy()


def dmi(high, low, close, di_len: int, adx_len: int):
    """[+DI, -DI, ADX] exactly as the ta.dmi reference in the Pine manual."""
    h, l = _arr(high), _arr(low)
    up = h - shift(h)
    down = -(l - shift(l))
    # FIX v2 (golden parity): equal moves differ by float noise (23385.7 - 23380.0 vs 23360.1 - 23354.4);
    # TradingView treats them as equal, so a tolerance far below one tick is applied.
    eps = 1e-9 * np.abs(h)
    with np.errstate(invalid="ignore"):
        plus_dm = np.where(np.isnan(up), nan, np.where((up - down > eps) & (up > 0), up, 0.0))
        minus_dm = np.where(np.isnan(down), nan, np.where((down - up > eps) & (down > 0), down, 0.0))
    trur = rma(true_range(h, l, close, False), di_len)
    with np.errstate(invalid="ignore", divide="ignore"):
        plus = fixnan(100 * rma(plus_dm, di_len) / trur)
        minus = fixnan(100 * rma(minus_dm, di_len) / trur)
        s = plus + minus
        adx = 100 * rma(np.abs(plus - minus) / np.where(s == 0, 1, s), adx_len)
    return plus, minus, adx


def supertrend(high, low, close, factor: float, atr_period: int):
    """[supertrend, direction] (direction < 0 = uptrend), per the ta.supertrend reference."""
    h, l, c = _arr(high), _arr(low), _arr(close)
    a = atr(h, l, c, atr_period)
    src = (h + l) / 2
    n = len(c)
    st = np.full(n, nan)
    direction = np.full(n, nan)
    up_b = np.full(n, nan)
    lo_b = np.full(n, nan)
    for i in range(n):
        ub, lb = src[i] + factor * a[i], src[i] - factor * a[i]
        prev_lo = 0.0 if i == 0 or np.isnan(lo_b[i - 1]) else lo_b[i - 1]
        prev_up = 0.0 if i == 0 or np.isnan(up_b[i - 1]) else up_b[i - 1]
        pc = c[i - 1] if i > 0 else nan
        lb = lb if (lb > prev_lo or pc < prev_lo) else prev_lo
        ub = ub if (ub < prev_up or pc > prev_up) else prev_up
        lo_b[i], up_b[i] = lb, ub
        prev_st = st[i - 1] if i > 0 else nan
        if i == 0 or np.isnan(a[i - 1]):
            d = 1.0
        elif prev_st == prev_up:
            d = -1.0 if c[i] > ub else 1.0
        else:
            d = 1.0 if c[i] < lb else -1.0
        direction[i] = d
        # During the ATR warm-up the bands are not real numbers yet: report na (direction stays 1, as in Pine).
        st[i] = np.nan if np.isnan(a[i]) else (lb if d == -1 else ub)
    return st, direction


def linreg(x, n: int, offset: int) -> np.ndarray:
    """ta.linreg: intercept + slope * (n - 1 - offset), least squares over the last n values."""
    x = _arr(x)
    out = np.full_like(x, nan)
    t = np.arange(n, dtype=float)
    tm = t.mean()
    tt = ((t - tm) ** 2).sum()
    for i in range(n - 1, len(x)):
        w = x[i - n + 1: i + 1]
        if np.isnan(w).any():
            continue
        slope = ((t - tm) * (w - w.mean())).sum() / tt
        intercept = w.mean() - slope * tm
        out[i] = intercept + slope * (n - 1 - offset)
    return out
