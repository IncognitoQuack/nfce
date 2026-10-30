"""Candidates from the ChatGPT and Gemini research reports, implemented exactly as frozen in
../evidence/external_protocol.md. 5-minute bars, bar timestamps = bar START (IST).

Fill conventions (conservative):
- a signal on a completed bar fills at the next bar's open;
- stop-entries fill at max(open, level) for buys, min(open, level) for sells;
- stops fill at the stop, or at the open if the bar gaps through; a stop is also checked on the entry bar;
- when a stop and a target are both touched in one bar, the stop is taken;
- FIX (review round 3, H09): a target is also checked on the ENTRY bar. For an entry at the bar's open, or a stop-entry
  at a level the price crosses on its way to the high (long) / low (short), a target beyond the entry that the bar
  reaches is reached AFTER the fill, so it is unambiguous unless the stop was also touched (then the stop is taken);
- FIX (H10): a position still open when a day's data ends is closed at the last bar with reason "eod_incomplete"
  and counted by the runners (never silently dropped).
Every trade: dict(day, side, entry, exit, risk, reason, orders).
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from .research import _days

LAST = 15 * 60 + 20                      # bar 15:20-15:25: its close is the last regular 5m close


def hm(h, m):
    return h * 60 + m


def daily(bars: pd.DataFrame) -> pd.DataFrame:
    ist = bars.index.tz_convert("Asia/Kolkata")
    d = bars.groupby(ist.normalize()).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                                          close=("close", "last"))
    pc = d.close.shift(1)
    tr = pd.concat([d.high - d.low, (d.high - pc).abs(), (d.low - pc).abs()], axis=1).max(axis=1)
    d["atr_prev"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().shift(1)   # Wilder, days < t only
    d["range"] = d.high - d.low
    return d


def _walk(d: pd.DataFrame, j0: int, side: int, stop: float | None, target: float | None, exit_hm: int = LAST,
          check_entry_bar: bool = True):
    """Manage from bar j0 (the entry bar). Returns (exit price, reason, bar index)."""
    o, h, l, c, m = (d[k].to_numpy() for k in ("open", "high", "low", "close", "hm"))
    for j in range(j0, len(d)):
        if j > j0 or check_entry_bar:
            if stop is not None and ((side > 0 and l[j] <= stop) or (side < 0 and h[j] >= stop)):
                px = stop if j == j0 else (min(o[j], stop) if side > 0 else max(o[j], stop))
                return float(px), "stop", j
        if target is not None and ((side > 0 and h[j] >= target) or (side < 0 and l[j] <= target)):
            return float(target), "target", j
        if m[j] >= exit_hm:
            return float(c[j]), "eod", j
    return float(c[-1]), "eod_incomplete", len(d) - 1


def _trade(day, side, entry, px, risk, why, orders=2):
    return dict(day=day.date() if hasattr(day, "date") else day, side=side, entry=float(entry), exit=float(px),
                risk=float(risk), reason=why, orders=orders)


# ---------------- S1: session-anchor sigma momentum (Medidala) ----------------
def sigma_momentum(bars: pd.DataFrame, z_thr: float = 2.5, z_len: int = 12, ema_len: int = 200,
                   atr_mult: float = 1.5) -> list[dict]:
    b = bars.sort_index()
    ema = b.close.ewm(span=ema_len, adjust=False).mean()
    dd = daily(b)
    out = []
    for day, d in _days(b):
        a = dd.atr_prev.get(day, np.nan)
        if not np.isfinite(a) or len(d) < z_len + 2:
            continue
        cl = d.close.to_numpy()
        anchor = np.cumsum(cl) / np.arange(1, len(cl) + 1)
        dev = pd.Series(cl - anchor)
        z = (dev / dev.rolling(z_len).std(ddof=1)).to_numpy()
        e = ema.reindex(d.index).to_numpy()
        m, o = d.hm.to_numpy(), d.open.to_numpy()
        i = 0
        while i < len(d) - 1:
            close_t = m[i] + 5
            side = 0
            if hm(9, 30) <= close_t <= hm(14, 30) and np.isfinite(z[i]):
                side = 1 if z[i] >= z_thr and cl[i] > e[i] else -1 if z[i] <= -z_thr and cl[i] < e[i] else 0
            if not side:
                i += 1
                continue
            k = i + 1
            entry = o[k]
            stop = entry - side * atr_mult * a
            px, why, jx = None, None, None
            for j in range(k, len(d)):
                if (side > 0 and d.low.iloc[j] <= stop) or (side < 0 and d.high.iloc[j] >= stop):
                    px = min(o[j], stop) if side > 0 and j > k else max(o[j], stop) if side < 0 and j > k else stop
                    why, jx = "stop", j
                    break
                if m[j] >= LAST:
                    px, why, jx = cl[j], "eod", j
                    break
                if (side > 0 and z[j] <= 0) or (side < 0 and z[j] >= 0):
                    if j + 1 < len(d):
                        px, why, jx = o[j + 1], "z0", j + 1
                    else:
                        px, why, jx = cl[j], "eod", j
                    break
            if px is None:
                px, why, jx = cl[-1], "eod_incomplete", len(d) - 1
            out.append(_trade(day, side, entry, px, atr_mult * a, why))
            i = max(jx, i + 1)                               # flat again: new signals from that bar's close
    return out


# ---------------- S2: noise-area momentum (Zarattini et al. 2024) ----------------
def noise_area(bars: pd.DataFrame, long_only: bool = False, lookback: int = 14, max_trades: int = 2) -> list[dict]:
    b = bars.sort_index()
    dd = daily(b)
    days = list(_days(b))
    moves = {}
    for day, d in days:
        o0 = d.open.iloc[0]
        moves[day] = pd.Series((d.close / o0 - 1).abs().to_numpy(), index=d.hm.to_numpy())
    mv = pd.DataFrame(moves).T.sort_index()
    sig = mv.rolling(lookback, min_periods=lookback).mean().shift(1)
    checkpoints = {hm(9, 40) + 30 * k for k in range(11)}            # bars closing 09:45 .. 14:45
    out = []
    prev_close = dd.close.shift(1)
    for day, d in days:
        if day not in sig.index or not np.isfinite(sig.loc[day]).any():
            continue
        pc = prev_close.get(day, np.nan)
        o0 = d.open.iloc[0]
        if not np.isfinite(pc):
            continue
        s = sig.loc[day].reindex(d.hm.to_numpy()).to_numpy()
        up = max(o0, pc) * (1 + s)
        dn = min(o0, pc) * (1 - s)
        hlc3 = ((d.high + d.low + d.close) / 3).to_numpy()
        v = d.volume.fillna(0).to_numpy()
        cv = np.cumsum(v)
        vw = np.where(cv > 0, np.cumsum(hlc3 * v) / np.where(cv > 0, cv, 1), hlc3)
        cl, o, m = d.close.to_numpy(), d.open.to_numpy(), d.hm.to_numpy()
        pos, entry, n = 0, 0.0, 0
        a = dd.atr_prev.get(day, np.nan)
        if not np.isfinite(a):
            continue
        for i in range(len(d)):
            if pos:
                trail = max(up[i], vw[i]) if pos > 0 else min(dn[i], vw[i])
                if m[i] >= LAST:
                    out.append(_trade(day, pos, entry, cl[i], 0.25 * a, "eod"))
                    pos = 0
                    continue
                if np.isfinite(trail) and ((pos > 0 and cl[i] < trail) or (pos < 0 and cl[i] > trail)) and i + 1 < len(d):
                    out.append(_trade(day, pos, entry, o[i + 1], 0.25 * a, "trail"))
                    pos = 0
                    continue
            elif m[i] in checkpoints and n < max_trades and i + 1 < len(d) and np.isfinite(up[i]):
                side = 1 if cl[i] > up[i] else (-1 if cl[i] < dn[i] and not long_only else 0)
                if side:
                    pos, entry, n = side, o[i + 1], n + 1
        if pos:                                                   # FIX (H10): the day's data ended with a position
            out.append(_trade(day, pos, entry, cl[-1], 0.25 * a, "eod_incomplete"))
    return out


# ---------------- S3: Williams prior-day-range breakout (long only) ----------------
def williams_pd(bars: pd.DataFrame, k: float = 0.5) -> list[dict]:
    dd = daily(bars)
    out = []
    prev = dd.shift(1)
    for day, d in _days(bars):
        p = prev.loc[day] if day in prev.index else None
        a = dd.atr_prev.get(day, np.nan)
        if p is None or not np.isfinite(p.high) or not np.isfinite(a):
            continue
        t = d.open.iloc[0] + k * (p.high - p.low)
        for j in range(len(d)):
            if d.hm.iloc[j] > hm(15, 10):
                break
            if d.high.iloc[j] >= t:
                entry = max(t, d.open.iloc[j])
                px, why, _ = _walk(d, j, 1, None, None)
                out.append(_trade(day, 1, entry, px, 0.25 * a, why))
                break
    return out


# ---------------- S4: Williams 3-day dominant swing range breakout ----------------
def williams_dsr(bars: pd.DataFrame) -> list[dict]:
    dd = daily(bars)
    out = []
    idx = list(dd.index)
    pos_of = {d: i for i, d in enumerate(idx)}
    for day, d in _days(bars):
        i = pos_of.get(day)
        if i is None or i < 3:
            continue
        h1, l1, h3, l3 = dd.high.iloc[i - 1], dd.low.iloc[i - 1], dd.high.iloc[i - 3], dd.low.iloc[i - 3]
        dsr = max(abs(h3 - l1), abs(h1 - l3))
        o0 = d.open.iloc[0]
        buy, sell = o0 + 0.5 * dsr, o0 - 0.5 * dsr
        for j in range(len(d)):
            mj = d.hm.iloc[j]
            if mj < hm(9, 20):
                continue
            if mj > hm(14, 30):
                break
            hb, lb = d.high.iloc[j] >= buy, d.low.iloc[j] <= sell
            if hb and lb:
                break                                           # ambiguous bar: skip the day
            if hb or lb:
                side = 1 if hb else -1
                entry = max(d.open.iloc[j], buy) if side > 0 else min(d.open.iloc[j], sell)
                stop = o0
                tgt = entry + side * 2.0 * dsr
                px, why, _ = _walk(d, j, side, stop, tgt)
                out.append(_trade(day, side, entry, px, abs(entry - stop), why))
                break
    return out


# ---------------- S5 / S5c: NR7 (and ID/NR4) compression breakout ----------------
def nr7(bars: pd.DataFrame, include_idnr4: bool = False, atr_floor: float = 0.0) -> list[dict]:
    dd = daily(bars)
    r = dd.range.to_numpy()
    hi, lo = dd.high.to_numpy(), dd.low.to_numpy()
    atr_incl = dd.atr_prev.shift(-1).to_numpy()                  # ATR14 through day t-1, aligned at t-1
    pos_of = {d: i for i, d in enumerate(dd.index)}
    out = []
    for day, d in _days(bars):
        i = pos_of.get(day)
        if i is None or i < 8:
            continue
        p = i - 1
        is_nr7 = r[p] < r[p - 6:p].min()
        is_idnr4 = hi[p] < hi[p - 1] and lo[p] > lo[p - 1] and r[p] < r[p - 3:p].min()
        ok = is_nr7 or (include_idnr4 and is_idnr4)
        if atr_floor > 0:
            ok = ok and np.isfinite(atr_incl[p]) and r[p] >= atr_floor * atr_incl[p]
        if not ok:
            continue
        H, L = hi[p], lo[p]
        A = r[p - 6:p + 1].mean()
        o0 = d.open.iloc[0]
        side, entry, j0 = 0, None, None
        if o0 > H:
            if o0 >= H + A:
                continue
            side, entry, j0 = 1, o0, 0
        elif o0 < L:
            if o0 <= L - A:
                continue
            side, entry, j0 = -1, o0, 0
        else:
            for j in range(len(d)):
                if d.hm.iloc[j] > hm(15, 10):
                    break
                hb, lb = d.high.iloc[j] >= H, d.low.iloc[j] <= L
                if hb and lb:
                    break
                if hb or lb:
                    side = 1 if hb else -1
                    entry = max(d.open.iloc[j], H) if side > 0 else min(d.open.iloc[j], L)
                    j0 = j
                    break
        if not side:
            continue
        stop = L if side > 0 else H
        tgt = (H + A) if side > 0 else (L - A)
        px, why, _ = _walk(d, j0, side, stop, tgt)
        out.append(_trade(day, side, entry, px, abs(entry - stop), why))
    return out


# ---------------- S6: filtered "Oops" gap reversal ----------------
def oops(bars: pd.DataFrame, vix: pd.Series, gap: float = 0.0015, vix_min: float = 15.0, tick: float = 0.05) -> list[dict]:
    dd = daily(bars)
    vday = vix.groupby(vix.index.tz_convert("Asia/Kolkata").normalize()).last()
    prev = dd.shift(1)
    out = []
    for day, d in _days(bars):
        if day not in prev.index or not np.isfinite(prev.loc[day].high):
            continue
        p = prev.loc[day]
        pv = vday[vday.index < day]
        if pv.empty or pv.iloc[-1] < vix_min:
            continue
        o0 = d.open.iloc[0]
        if o0 <= p.low - gap * p.close:
            side, level = 1, p.low
        elif o0 >= p.high + gap * p.close:
            side, level = -1, p.high
        else:
            continue
        ext = None
        for j in range(len(d)):
            mj = d.hm.iloc[j]
            if mj > hm(11, 15):
                break
            if mj >= hm(9, 20) and ((side > 0 and d.high.iloc[j] >= level) or (side < 0 and d.low.iloc[j] <= level)):
                entry = max(d.open.iloc[j], level) if side > 0 else min(d.open.iloc[j], level)
                stop = (ext - tick) if side > 0 else (ext + tick)
                if (entry - stop) * side <= 0:
                    break
                px, why, _ = _walk(d, j, side, stop, (p.high + p.low) / 2)
                out.append(_trade(day, side, entry, px, abs(entry - stop), why))
                break
            bl, bh = d.low.iloc[j], d.high.iloc[j]
            ext = (bl if ext is None else min(ext, bl)) if side > 0 else (bh if ext is None else max(ext, bh))
    return out


# ---------------- S7: post-weekend / post-holiday opening-range breakout ----------------
def weekend_holiday_orb(bars: pd.DataFrame) -> list[dict]:
    days = list(_days(bars))
    out = []
    for k in range(1, len(days)):
        day, d = days[k]
        prev_day = days[k - 1][0]
        gap_days = (day - prev_day).days
        missing_weekdays = sum(1 for x in range(1, gap_days) if (prev_day + pd.Timedelta(days=x)).weekday() < 5)
        if missing_weekdays >= 1:
            last_sig, exit_hm = hm(9, 35), hm(9, 40)              # holiday: signal close <= 09:40, exit at the 09:45 close
        elif gap_days >= 3:
            last_sig, exit_hm = hm(10, 5), hm(10, 10)             # weekend: signal close <= 10:10, exit at the 10:15 close
        else:
            continue
        orr = d[d.hm < hm(9, 30)]
        if len(orr) < 3:
            continue
        H, L = orr.high.max(), orr.low.min()
        cl, o, m = d.close.to_numpy(), d.open.to_numpy(), d.hm.to_numpy()
        for i in range(len(d) - 1):
            if m[i] < hm(9, 30):
                continue
            if m[i] > last_sig:
                break
            side = 1 if cl[i] > H else -1 if cl[i] < L else 0
            if side:
                entry = o[i + 1]
                stop = L if side > 0 else H
                if (entry - stop) * side <= 0:
                    break
                px, why, _ = _walk(d, i + 1, side, stop, None, exit_hm)
                out.append(_trade(day, side, entry, px, abs(entry - stop), why))
                break
    return out


# ---------------- S8: morning +-0.5% continuation (underlying signal) ----------------
def morning_move(bars: pd.DataFrame, thr: float = 0.005) -> list[dict]:
    dd = daily(bars)
    out = []
    for day, d in _days(bars):
        a = dd.atr_prev.get(day, np.nan)
        s = d[d.hm == hm(9, 40)]
        e = d[d.hm == hm(9, 45)]
        if not np.isfinite(a) or s.empty or e.empty or d.hm.iloc[0] != hm(9, 15):
            continue
        r = s.close.iloc[0] / d.open.iloc[0] - 1
        if abs(r) <= thr:
            continue
        side = 1 if r > 0 else -1
        j = int(np.flatnonzero(d.hm.to_numpy() == hm(9, 45))[0])
        px, why, _ = _walk(d, j, side, None, None, hm(15, 10))
        out.append(_trade(day, side, e.open.iloc[0], px, 0.25 * a, why))
    return out


# ---------------- S9: late-session momentum without the NGE filter ----------------
def late_momentum(bars: pd.DataFrame, thr: float = 0.0065, stop_pct: float = 0.003) -> list[dict]:
    dd = daily(bars)
    prev_close = dd.close.shift(1)
    out = []
    for day, d in _days(bars):
        pc = prev_close.get(day, np.nan)
        a0945, a1500, e = d[d.hm == hm(9, 40)], d[d.hm == hm(14, 55)], d[d.hm == hm(15, 0)]
        if not np.isfinite(pc) or a0945.empty or a1500.empty or e.empty:
            continue
        onfh = a0945.close.iloc[0] / pc - 1
        rod = a1500.close.iloc[0] / pc - 1
        if np.sign(onfh) != np.sign(rod) or abs(rod) < thr:
            continue
        side = 1 if rod > 0 else -1
        j = int(np.flatnonzero(d.hm.to_numpy() == hm(15, 0))[0])
        entry = e.open.iloc[0]
        stop = entry * (1 - side * stop_pct)
        px, why, _ = _walk(d, j, side, stop, None)
        out.append(_trade(day, side, entry, px, abs(entry - stop), why))
    return out
