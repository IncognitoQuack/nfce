"""Candidate intraday strategies on 5-minute bars, for the multi-year research (../evidence/research_protocol.md).

All functions are causal: a decision on a bar uses only that bar's close and earlier data. Fills:
- entries at the signal bar's close (momentum enters at the open of its start bar);
- stops at the stop price, or at the bar's open if it gaps through (checked before targets);
- targets at the target price;
- end-of-day exits at the close of the 15:15 bar (15:20), or of the last bar if that bar is missing ("eod_incomplete").
Each trade: dict(day, side, entry, exit, risk, reason, entry_time, orders).
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

TZ = "Asia/Kolkata"


def _days(bars: pd.DataFrame):
    b = bars.sort_index()
    ist = b.index.tz_convert(TZ)
    for day, d in b.groupby(ist.normalize()):
        d = d.copy()
        d.index = d.index.tz_convert(TZ)
        d["hm"] = d.index.hour * 60 + d.index.minute          # bar START minute of day
        yield day, d


def daily_atr_prev(bars: pd.DataFrame, n: int = 14) -> pd.Series:
    """ATR14 of daily bars built from the intraday bars, shifted so day t sees only days < t."""
    ist = bars.index.tz_convert(TZ)
    d = bars.groupby(ist.normalize()).agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    pc = d.close.shift(1)
    tr = pd.concat([d.high - d.low, (d.high - pc).abs(), (d.low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean().shift(1)


def _manage(rest: pd.DataFrame, side: int, entry: float, stop: float, target: float | None, eod_hm: int = 15 * 60 + 15):
    """Walk bars after entry: stop first, then target, then the 15:15-bar close."""
    for t, r in rest.iterrows():
        if (side > 0 and r.low <= stop) or (side < 0 and r.high >= stop):
            return (min(r.open, stop) if side > 0 else max(r.open, stop)), "stop", t
        if target is not None and ((side > 0 and r.high >= target) or (side < 0 and r.low <= target)):
            return target, "target", t
        if r.hm >= eod_hm:
            return float(r.close), "eod", t
    if len(rest):
        return float(rest.close.iloc[-1]), "eod_incomplete", rest.index[-1]
    return None


def orb(bars: pd.DataFrame, or_min: int = 30, stop: str = "opp", exit: str = "eod", volgate: bool = False,
        last_entry_close: int = 13 * 60) -> list[dict]:
    atr = daily_atr_prev(bars) if volgate else None
    out = []
    for day, d in _days(bars):
        start = 9 * 60 + 15
        rng = d[d.hm < start + or_min]
        if len(rng) < or_min // 5 or rng.hm.iloc[0] != start:
            continue                                         # incomplete opening range: no decision possible
        hi, lo = float(rng.high.max()), float(rng.low.min())
        if volgate:
            a = atr.get(day, np.nan)
            if not (np.isfinite(a) and 0.25 * a <= hi - lo <= 0.60 * a):
                continue
        after = d[d.hm >= start + or_min]
        for i, (t, r) in enumerate(after.iterrows()):
            if r.hm + 5 > last_entry_close:
                break
            side = 1 if r.close > hi else -1 if r.close < lo else 0
            if not side:
                continue
            entry = float(r.close)
            sl = (lo if side > 0 else hi) if stop == "opp" else (hi + lo) / 2
            risk = (entry - sl) * side
            if risk <= 0:
                break
            tgt = entry + side * 2 * risk if exit == "2R" else None
            res = _manage(after.iloc[i + 1:], side, entry, sl, tgt)
            if res:
                px, why, xt = res
                out.append(dict(day=day.date(), side=side, entry=entry, exit=float(px), risk=risk, reason=why,
                                entry_time=t + pd.Timedelta(minutes=5), orders=2))
            break                                           # one decision a day
    return out


def momentum(bars: pd.DataFrame, start_hm: int = 14 * 60 + 30, big_only: bool = False) -> list[dict]:
    """Gao et al. (2018) style: sign of 09:15->10:15 return, traded from start_hm to the 15:25 close."""
    atr = daily_atr_prev(bars)
    prev_close, hist, out = None, [], []
    for day, d in _days(bars):
        complete = (d.hm == 15 * 60 + 25).any()
        b1015 = d[d.hm == 10 * 60 + 10]
        e = d[d.hm == start_hm]
        x = d[d.hm == 15 * 60 + 25]
        if prev_close is not None and len(b1015) and len(e) and len(x):
            r1 = float(b1015.close.iloc[0]) / prev_close - 1
            ok = (not big_only) or (len(hist) >= 60 and abs(r1) > np.median(hist[-60:]))
            a = atr.get(day, np.nan)
            if ok and r1 != 0 and np.isfinite(a):
                side = 1 if r1 > 0 else -1
                out.append(dict(day=day.date(), side=side, entry=float(e.open.iloc[0]), exit=float(x.close.iloc[0]),
                                risk=0.25 * a, reason="eod", entry_time=e.index[0], orders=2))
            hist.append(abs(r1))
        elif prev_close is not None and len(b1015):
            hist.append(abs(float(b1015.close.iloc[0]) / prev_close - 1))
        prev_close = float(d.close.iloc[-1]) if complete else None   # an incomplete session is not a reference
    return out


def _ema(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def vwap_trend(bars: pd.DataFrame, k: float = 1.5) -> list[dict]:
    b = bars.sort_index()
    c = b.close.to_numpy(float)
    e20, e50 = _ema(c, 20), _ema(c, 50)
    tr = np.maximum(b.high - b.low, np.maximum((b.high - b.close.shift()).abs(), (b.low - b.close.shift()).abs()))
    atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().to_numpy()
    pos = {t: i for i, t in enumerate(b.index)}
    out = []
    for day, d in _days(b):
        hlc3 = (d.high + d.low + d.close) / 3
        v = d.volume.fillna(0)
        cv = v.cumsum()
        vw = np.where(cv > 0, (hlc3 * v).cumsum() / cv, hlc3)
        sig = np.flatnonzero(d.hm.to_numpy() == 10 * 60 + 10)
        if not len(sig):
            continue
        j = sig[0]
        i = pos[d.index[j]]
        if not np.isfinite(atr[i]):
            continue
        close = float(d.close.iloc[j])
        side = 1 if close > vw[j] and e20[i] > e50[i] else -1 if close < vw[j] and e20[i] < e50[i] else 0
        if not side:
            continue
        sl = close - side * k * atr[i]
        res = _manage(d.iloc[j + 1:], side, close, sl, None)
        if res:
            px, why, _ = res
            out.append(dict(day=day.date(), side=side, entry=close, exit=float(px), risk=k * atr[i], reason=why,
                            entry_time=d.index[j] + pd.Timedelta(minutes=5), orders=2))
    return out


def expiry_dates(sessions: list[dt.date], instr: str) -> frozenset:
    """Historical NSE expiry days (approximation, see research_protocol.md); a holiday moves it to the previous session."""
    ss = sorted(sessions)
    sset = set(ss)

    def shift_back(d):
        while d not in sset and d >= ss[0]:
            d -= dt.timedelta(days=1)
        return d if d in sset else None

    out = set()
    d = ss[0]
    while d <= ss[-1]:
        week_start = d - dt.timedelta(days=d.weekday())
        if instr == "NIFTY":
            wd = 3 if week_start < dt.date(2025, 9, 1) else 1
            target = week_start + dt.timedelta(days=wd)
            x = shift_back(target)
            if x and x >= week_start:
                out.add(x)
        d += dt.timedelta(days=7)
    if instr == "BANKNIFTY":
        d = ss[0]
        while d <= ss[-1]:
            ws = d - dt.timedelta(days=d.weekday())
            if ws < dt.date(2023, 9, 4):
                x = shift_back(ws + dt.timedelta(days=3))
            elif ws < dt.date(2024, 11, 14):
                x = shift_back(ws + dt.timedelta(days=2))
            else:
                x = None
            if x and x >= ws:
                out.add(x)
            d += dt.timedelta(days=7)
        for m in pd.period_range(ss[0], ss[-1], freq="M"):
            if m.start_time.date() < dt.date(2024, 11, 14):
                continue
            wd = 3 if m.start_time.date() < dt.date(2025, 9, 1) else 1
            last = m.end_time.date()
            while last.weekday() != wd:
                last -= dt.timedelta(days=1)
            x = shift_back(last)
            if x:
                out.add(x)
    return frozenset(out)
