"""NFCE engine: a bar-by-bar Python port of nfce_strategy.pine (sections 1-10), v2.

Inputs are pandas DataFrames indexed by bar-OPEN time in Asia/Kolkata:
  bars : open, high, low, close, volume[, oi]   (continuous futures, 1-15 minute bars)
  vix  : optional, SAME timeframe as bars, column close  (India VIX)
  hw   : optional list of up to 5 DataFrames, SAME timeframe, with open, close (heavyweight stocks)
Context series on another timeframe are rejected: forward-filling an hourly bar's close into 5-minute bars would
leak future data (independent review finding M04).

v2 trade-management semantics (identical in nfce_indicator.pine / nfce_strategy.pine v2):
  * entry at the signal bar's close; SL checked first (the stop active when the bar opened);
  * targets 40% / 30% / rest; after T1 the stop moves to entry, after T2 to T1;
  * the moved stop is enforced INSIDE the same bar when the bar's close is beyond it (then it was certainly
    crossed after the target was touched, because the close is the last price of the bar);
  * no new entry on the bar where a trade exited (no same-bar reversal);
  * entry cut-offs (last entry, expiry-day cut) use the bar CLOSE time, i.e. the actual entry time; the opening
    skip excludes bars that START in the first N minutes; the lunch filter excludes bars overlapping 12:30-13:30;
  * daily stop (spec section 6): no new entries after N losing trades or a cumulative -X R day (gross R).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from . import ta

MAXSLOT = 400
FACTORS = ("volume", "directional", "trend", "adx", "htf", "cvd", "oi", "heavyweights", "vix")
# FIX (review round 3, M06): every input that changes prepared columns is in the fingerprint (extra_expiry_dates too)
PREP_FIELDS = ("instr", "tf_preset", "use_oi", "oi_len", "or_mins", "rvol_days", "z_len", "expiry_dates",
               "extra_expiry_dates")


@dataclass(frozen=True)
class Params:
    instr: str = "NIFTY"
    tf_preset: str = "Auto"
    min_score_in: int = 0
    rvol_thr_in: float = 0.0
    brk_len_in: int = 0
    a_plus: int = 80
    use_oi: bool = True
    oi_len: int = 3
    skip_open: int = 15
    use_lunch: bool = True
    last_entry: int = 1445
    sq_off: int = 1515
    exp_cut: int = 1330
    exp_boost: int = 10
    max_trades: int = 4
    rvol_days: int = 10
    z_len: int = 20
    req_vol: bool = False
    body_atr: float = 0.5
    chop_max: float = 61.8
    room_r: float = 1.0
    or_mins: int = 15
    sl_buf_atr: float = 0.1
    min_risk_atr: float = 0.5
    max_risk_atr: float = 2.0
    r1m: float = 1.0
    r2m: float = 2.0
    r3m: float = 3.0
    vix_hi: float = 20.0
    weights: tuple = (20, 15, 15, 10, 10, 5, 10, 10, 5)
    expiry_dates: frozenset | None = None   # explicit expiry dates (holiday shifts); None = calendar rule
    extra_expiry_dates: frozenset = frozenset()   # added to the calendar rule (e.g. a holiday-shifted Monday)
    # v2 semantics (defaults = v2 behaviour; set the legacy values to reproduce the Phase 2-3 runs)
    allow_same_bar_reentry: bool = False
    intrabar_stop_after_target: bool = True
    close_time_cutoffs: bool = True
    daily_max_losses: int = 2         # 0 = off
    daily_max_loss_r: float = 2.0     # 0 = off
    # research setting (not in Pine): the stop must be at least this % of price, so costs stay a small share of R
    min_risk_pct: float = 0.0         # 0 = off

    def ablate(self, factor: str) -> "Params":
        w = list(self.weights)
        w[FACTORS.index(factor)] = 0.0
        return replace(self, weights=tuple(w))

    def fingerprint(self) -> tuple:
        return tuple((k, getattr(self, k)) for k in PREP_FIELDS)


# Phase 1-3 behaviour, to reproduce the v1 TradingView runs exactly.
LEGACY_V1 = dict(allow_same_bar_reentry=True, intrabar_stop_after_target=False, close_time_cutoffs=False,
                 daily_max_losses=0, daily_max_loss_r=0.0)


def strict_phase3(tf_min: int) -> dict:
    """The Phase-3 'stricter' setting (score +10, RVOL x1.2). NOT validated: kept only as a labelled option."""
    return dict(min_score_in=75 if tf_min <= 5 else 70, rvol_thr_in=1.8 if tf_min <= 5 else 1.56)


@dataclass
class Trade:
    entry_time: pd.Timestamp
    side: str
    score: float
    expiry: bool
    entry: float
    R: float
    pnl: float          # points per unit, 40/30/30 weighted, before costs
    exit: str           # S = stop, B = breakeven/trail stop, 3 = T3, Q = square-off, U = unresolved (data ended)
    bars: int
    exit_time: pd.Timestamp | None = None
    grade: str = "A"
    orders: int = 2     # executed orders (1 entry + exit legs), for brokerage

    @property
    def r(self) -> float:
        return self.pnl / self.R if self.R else 0.0


def _preset(p: str, a, b, c, d):
    return {"1m": a, "3m": b, "5m": c}.get(p, d)


def _hm(x: int) -> int:
    return (x // 100) * 60 + x % 100


@dataclass
class Prepared:
    """All per-bar series that do not depend on the parameters being optimised."""
    idx: pd.DatetimeIndex
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    vol: np.ndarray
    tf_min: int
    preset: str
    cols: dict = field(default_factory=dict)
    fingerprint: tuple = ()


def _interval_minutes(index: pd.DatetimeIndex) -> float:
    if len(index) < 3:
        return math.nan
    d = pd.Series(index).diff().dropna()
    d = d[d <= pd.Timedelta(hours=2)]                      # ignore overnight gaps
    return d.dt.total_seconds().median() / 60 if len(d) else math.nan


def _check_context(df: pd.DataFrame, tf_min: int, name: str) -> pd.DataFrame:
    if df.index.tz is None:
        raise ValueError(f"{name}: index must be timezone-aware")
    m = _interval_minutes(df.index)
    if not math.isnan(m) and abs(m - tf_min) > 1e-6:
        raise ValueError(f"{name}: bars are {m:g}-minute but the chart is {tf_min}-minute; supply the same timeframe "
                         "(forward-filling a longer bar's close into shorter bars would use future data)")
    return df.sort_index()


def prepare(bars: pd.DataFrame, tf_min: int, params: Params = Params(), vix: pd.DataFrame | None = None,
            hw: list[pd.DataFrame] | None = None, daily: pd.DataFrame | None = None) -> Prepared:
    """daily: optional daily bars (high, low, close; index = session date) for PDH/PDL/PDC, as Pine's
    request.security(..., "D", [high[1], low[1], close[1]]). For futures TradingView's daily close is the official
    settlement, which differs from the last intraday trade; without `daily` the levels come from the bars."""
    b = bars.sort_index()
    idx = b.index
    if idx.tz is None:
        raise ValueError("bars index must be timezone-aware (Asia/Kolkata)")
    if idx.has_duplicates:
        raise ValueError("bars index has duplicate timestamps")
    o, h, l, c = (b[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    vol = np.nan_to_num(b["volume"].to_numpy(float))
    n = len(b)
    preset = params.tf_preset if params.tf_preset != "Auto" else (
        "1m" if tf_min <= 1 else "3m" if tf_min <= 3 else "5m" if tf_min <= 5 else "15m")
    P = lambda a, b_, c_, d: _preset(preset, a, b_, c_, d)  # noqa: E731
    cols: dict = {}
    if vix is not None and len(vix):
        vix = _check_context(vix, tf_min, "vix")
    hw = [_check_context(d, tf_min, f"heavyweight {k + 1}") for k, d in enumerate(hw or [])]

    # ---- time & expiry ----
    ist = idx.tz_convert("Asia/Kolkata")
    mins_now = (ist.hour * 60 + ist.minute).to_numpy()
    close_t = ist + pd.Timedelta(minutes=tf_min)
    mins_close = (close_t.hour * 60 + close_t.minute).to_numpy()
    dates = ist.normalize()
    new_day = np.r_[True, dates[1:] != dates[:-1]]
    mins_from_open = mins_now - (9 * 60 + 15)
    exp_dow = 3 if params.instr == "SENSEX" else 1
    dow = ist.dayofweek.to_numpy()
    last_week = ((ist + pd.Timedelta(days=7)).month != ist.month)
    if params.expiry_dates is not None:
        is_exp = np.array([d.date() in params.expiry_dates for d in dates])
    else:
        weekly = (params.instr in ("NIFTY", "SENSEX")) & (dow == exp_dow)
        is_exp = weekly | ((dow == exp_dow) & last_week)
    if params.extra_expiry_dates:
        is_exp = np.asarray(is_exp) | np.array([d.date() in params.extra_expiry_dates for d in dates])
    cols.update(mins_now=mins_now, mins_close=mins_close, mins_from_open=mins_from_open, new_day=new_day,
                is_exp=np.asarray(is_exp), dates=dates)

    # ---- HTF trend: [close[1], ema(close,20)[1]] on 15m/60m with lookahead_on = last COMPLETED HTF bar ----
    htf_min = P(15, 15, 60, 60)
    bucket = pd.Series(np.floor(np.maximum(mins_from_open, 0) / htf_min), index=idx).astype(int)
    key = pd.Series(dates.strftime("%Y%m%d"), index=idx) + "-" + bucket.astype(str)
    grp = pd.Series(c, index=idx).groupby(key.values, sort=False).last()
    htf_close = grp.to_numpy()
    htf_ema = ta.ema(htf_close, 20)
    pos = pd.Index(grp.index).get_indexer(key.values)
    prev = pos - 1
    cols["htf_c"] = np.where(prev >= 0, htf_close[np.maximum(prev, 0)], np.nan)
    cols["htf_e"] = np.where(prev >= 0, htf_ema[np.maximum(prev, 0)], np.nan)
    cols["htf_warning"] = tf_min >= htf_min

    # ---- previous-day levels ----
    if daily is not None and len(daily):
        dd = daily.copy()
        di = pd.DatetimeIndex(dd.index)
        dd.index = (di.tz_localize("Asia/Kolkata") if di.tz is None else di.tz_convert("Asia/Kolkata")).normalize()
        day = dd.rename(columns={"high": "h", "low": "l", "close": "c"})[["h", "l", "c"]].sort_index()
        dpos = np.searchsorted(day.index.values, dates.values, side="left") - 1     # last daily bar BEFORE the session
    else:
        day = pd.DataFrame({"h": h, "l": l, "c": c}, index=idx).groupby(dates.values).agg({"h": "max", "l": "min", "c": "last"})
        dpos = pd.Index(day.index).get_indexer(dates.values) - 1
    for k, src in (("pdh", "h"), ("pdl", "l"), ("pdc", "c")):
        arr = day[src].to_numpy()
        cols[k] = np.where(dpos >= 0, arr[np.maximum(dpos, 0)], np.nan)
    pdh, pdl, pdc = cols["pdh"], cols["pdl"], cols["pdc"]
    pp = (pdh + pdl + pdc) / 3
    bc = (pdh + pdl) / 2
    tc = 2 * pp - bc
    cols.update(pp=pp, bc=bc, tc=tc, r1=2 * pp - pdl, s1=2 * pp - pdh)

    # ---- opening range ----
    orh, orl = np.full(n, np.nan), np.full(n, np.nan)
    cur_h = cur_l = np.nan
    for i in range(n):
        if new_day[i]:
            cur_h, cur_l = h[i], l[i]
        elif 0 <= mins_from_open[i] < params.or_mins:
            cur_h, cur_l = max(cur_h, h[i]), min(cur_l, l[i])   # max/min with NaN stays NaN, as in Pine
        orh[i], orl[i] = cur_h, cur_l
    cols.update(orh=orh, orl=orl)

    # ---- session VWAP from volume ----
    hlc3 = (h + l + c) / 3
    gkey = dates.values
    cpv = pd.Series(hlc3 * vol).groupby(gkey).cumsum().to_numpy()
    cpv2 = pd.Series(hlc3 * hlc3 * vol).groupby(gkey).cumsum().to_numpy()
    cv = pd.Series(vol).groupby(gkey).cumsum().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        vw = np.where(cv > 0, cpv / cv, hlc3)
        vsd = np.where(cv > 0, np.sqrt(np.maximum(cpv2 / cv - vw * vw, 0)), 0.0)
    cols.update(vw=vw, vwu2=vw + 2 * vsd, vwl2=vw - 2 * vsd, no_volume=bool(cv[-1] == 0) if n else True)

    # ---- time-of-day RVOL (same ring buffer as the Pine matrix) ----
    rows = params.rvol_days + 1
    mat = np.full((rows, MAXSLOT), np.nan)
    day_row = -1
    tod = np.full(n, np.nan)
    for i in range(n):
        if new_day[i]:
            day_row = (day_row + 1) % rows
            mat[day_row, :] = np.nan
        slot = int(max(0, min(MAXSLOT - 1, math.floor(mins_from_open[i] / max(tf_min, 1)))))
        if day_row >= 0:
            col = np.delete(mat[:, slot], day_row)
            ok = ~np.isnan(col)
            if ok.sum() >= 3:
                tod[i] = col[ok].sum() / ok.sum()
            mat[day_row, slot] = vol[i]
    sma_v = ta.sma(vol, params.z_len)
    with np.errstate(invalid="ignore", divide="ignore"):
        rvol = np.where(~np.isnan(tod) & (tod > 0), vol / tod, np.where(sma_v > 0, vol / sma_v, np.nan))
        sd = ta.stdev(vol, params.z_len)
        volz = np.where(sd > 0, (vol - sma_v) / sd, np.nan)
    cols.update(rvol=rvol, volz=volz)

    # ---- approximate CVD ----
    rng = h - l
    with np.errstate(invalid="ignore", divide="ignore"):
        bdelta = np.where(rng > 0, vol * ((c - l) - (h - c)) / rng, 0.0)
    cvd = pd.Series(bdelta).groupby(gkey).cumsum().to_numpy()
    cols["cvd_slope"] = cvd - ta.shift(cvd, 3)

    # ---- trend & regime ----
    atrv = ta.atr(h, l, c, 14)
    e9, e21, e50 = ta.ema(c, 9), ta.ema(c, 21), ta.ema(c, 50)
    dip, dim, adx = ta.dmi(h, l, c, 14, 14)
    _, st_dir = ta.supertrend(h, l, c, 3.0, 10)
    with np.errstate(invalid="ignore", divide="ignore"):
        lr_slope = (ta.linreg(c, 20, 0) - ta.linreg(c, 20, 1)) / atrv
    hh = ta.shift(h)
    hl = ta.shift(l)
    up_cnt = ta.rolling_sum(((h > hh) & (l > hl)).astype(float), 5)
    dn_cnt = ta.rolling_sum(((h < hh) & (l < hl)).astype(float), 5)
    with np.errstate(invalid="ignore", divide="ignore"):
        chop = 100 * np.log10(ta.rolling_sum(ta.true_range(h, l, c, True), 14)
                              / (ta.highest(h, 14) - ta.lowest(l, 14))) / np.log10(14)
    cols.update(atr=atrv, e9=e9, e21=e21, e50=e50, dip=dip, dim=dim, adx=adx, adx_up=adx > ta.shift(adx),
                st_dir=st_dir, lr_slope=lr_slope, up_cnt=up_cnt, dn_cnt=dn_cnt, chop=chop)

    # ---- futures OI ----
    if params.use_oi and "oi" in b.columns:
        oi = b["oi"].to_numpy(float)
        dpx = c - ta.shift(c, params.oi_len)
        doi = oi - ta.shift(oi, params.oi_len)
        oi_ok = ~np.isnan(oi) & ~np.isnan(doi)
    else:
        dpx = doi = np.full(n, np.nan)
        oi_ok = np.zeros(n, bool)
    state = np.full(n, "n/a", dtype=object)
    state[oi_ok & (dpx > 0) & (doi > 0)] = "LB"
    state[oi_ok & (dpx < 0) & (doi > 0)] = "SB"
    state[oi_ok & (dpx > 0) & (doi < 0)] = "SC"
    state[oi_ok & (dpx < 0) & (doi < 0)] = "LU"
    state[oi_ok & (state == "n/a")] = "N"
    cols.update(oi_ok=oi_ok, oi_state=state)

    # ---- India VIX ----
    if vix is not None and len(vix):
        v = vix["close"]
        cols["vix_now"] = v.reindex(idx, method="ffill").to_numpy()
        cols["vix_chg"] = (v - v.shift(5)).reindex(idx, method="ffill").to_numpy()
    else:
        cols["vix_now"] = cols["vix_chg"] = np.full(n, np.nan)

    # ---- heavyweights: % change from the day's open on each stock's own bars ----
    chg = []
    for d in hw[:5]:
        dd = d.index.tz_convert("Asia/Kolkata").normalize()
        day_open = d["open"].groupby(dd.values).transform("first")
        chg.append(((d["close"] - day_open) / day_open * 100).reindex(idx, method="ffill").to_numpy())
    if chg:
        m = np.vstack(chg)
        cols["hw_up"] = (np.nan_to_num(m) > 0).sum(0).astype(float)
        cols["hw_dn"] = (np.nan_to_num(m) < 0).sum(0).astype(float)
        cols["hw_n"] = (~np.isnan(m)).sum(0).astype(float)
    else:
        cols["hw_up"] = cols["hw_dn"] = cols["hw_n"] = np.zeros(n)

    return Prepared(idx=idx, o=o, h=h, l=l, c=c, vol=vol, tf_min=tf_min, preset=preset, cols=cols,
                    fingerprint=params.fingerprint())


def _score(w, a, b, c, d, e, f, g, h_, i):
    num = w[0] * a + w[1] * b + w[2] * c + w[3] * d + w[4] * e + w[5] * f
    den = w[0] + w[1] + w[2] + w[3] + w[4] + w[5]
    if not math.isnan(g):
        num += w[6] * g
        den += w[6]
    if not math.isnan(h_):
        num += w[7] * h_
        den += w[7]
    if not math.isnan(i):
        num += w[8] * i
        den += w[8]
    return 100 * num / den if den > 0 else 0.0


def _gt(a, b) -> bool:   # Pine comparison: false when either side is na
    return not (math.isnan(a) or math.isnan(b)) and a > b


def _lt(a, b) -> bool:
    return not (math.isnan(a) or math.isnan(b)) and a < b


def run(pr: Prepared, params: Params = Params(), trace: dict | None = None, mtm: list | None = None,
        open_out: list | None = None) -> list[Trade]:
    """Backtest.

    trace    = {bar_index: {}} fills in, for those bars, which gate passed or blocked the signal.
    mtm      = [] receives one mark-to-market equity value per bar (gross points per unit: realised + open P&L).
    open_out = [] receives the position still open after the last bar (a Trade with exit "" and pnl so far), so a
               live caller sees a trade entered on the latest bar: trades are only listed once they exit.
    """
    if pr.fingerprint and pr.fingerprint != params.fingerprint():
        raise ValueError("Prepared was built with different preparation parameters "
                         f"({dict(pr.fingerprint)} vs {dict(params.fingerprint())}); call prepare() again")
    cl = pr.cols
    P = lambda a, b, c, d: _preset(pr.preset, a, b, c, d)  # noqa: E731
    rvol_thr = params.rvol_thr_in if params.rvol_thr_in > 0 else P(2.0, 1.8, 1.5, 1.3)
    z_thr = P(2.0, 1.8, 1.5, 1.3)
    brk_len = params.brk_len_in if params.brk_len_in > 0 else P(10, 8, 6, 4)
    swing = P(5, 5, 4, 3)
    pre_score = params.min_score_in if params.min_score_in > 0 else P(75, 70, 65, 60)
    adx_min = P(22.0, 20.0, 20.0, 18.0)
    cooldown = P(10, 5, 4, 2)
    h, l, c, o = pr.h, pr.l, pr.c, pr.o
    atrv = cl["atr"]
    brk_hi = ta.shift(ta.highest(h, brk_len))
    brk_lo = ta.shift(ta.lowest(l, brk_len))
    sl_lraw = ta.lowest(l, swing) - params.sl_buf_atr * atrv
    sl_sraw = ta.highest(h, swing) + params.sl_buf_atr * atrv
    w = params.weights
    n = len(c)
    sq, last_e, exp_cut = _hm(params.sq_off), _hm(params.last_entry), _hm(params.exp_cut)

    trades: list[Trade] = []
    pos = 0
    eP = sP = t1P = t2P = t3P = R = rem = pnl = sc = 0.0
    t1hit = t2hit = e_exp = False
    trades_today = losses_today = 0
    r_today = 0.0
    realised = 0.0
    last_sig = -100000
    e_bar = 0
    legs = 0
    e_time = None
    e_grade = "A"

    for i in range(n):
        if cl["new_day"][i] and pos != 0 and i > 0:
            # FIX (review round 3, H13): the session ended (missing square-off bars) with a position. Close it at the
            # last observed price as UNRESOLVED ("U"), never as a normal next-day exit; stats.report excludes it.
            pnl += rem * pos * (c[i - 1] - eP)
            legs += 1
            trades.append(Trade(e_time, "L" if pos == 1 else "S", sc, e_exp, eP, R, pnl, "U", i - 1 - e_bar,
                                pr.idx[i - 1] + pd.Timedelta(minutes=pr.tf_min), e_grade, 1 + legs))
            realised += pnl
            pos = 0
        if cl["new_day"][i]:
            trades_today = losses_today = 0
            r_today = 0.0
        # ---------- manage ----------
        ex = ""
        if pos == 1:
            if l[i] <= sP:
                pnl += rem * (min(o[i], sP) - eP)
                legs += 1
                ex = "B" if t1hit else "S"
            else:
                hit = False
                if not t1hit and h[i] >= t1P:
                    t1hit, pnl, rem, sP, hit, legs = True, pnl + 0.4 * (t1P - eP), rem - 0.4, eP, True, legs + 1
                if not t2hit and h[i] >= t2P:
                    t2hit, pnl, rem, sP, hit, legs = True, pnl + 0.3 * (t2P - eP), rem - 0.3, t1P, True, legs + 1
                if h[i] >= t3P:
                    pnl += rem * (t3P - eP)
                    legs += 1
                    ex = "3"
                elif hit and params.intrabar_stop_after_target and c[i] <= sP:
                    pnl += rem * (sP - eP)            # the close proves the new stop was crossed after the target
                    legs += 1
                    ex = "B"
        elif pos == -1:
            if h[i] >= sP:
                pnl += rem * (eP - max(o[i], sP))
                legs += 1
                ex = "B" if t1hit else "S"
            else:
                hit = False
                if not t1hit and l[i] <= t1P:
                    t1hit, pnl, rem, sP, hit, legs = True, pnl + 0.4 * (eP - t1P), rem - 0.4, eP, True, legs + 1
                if not t2hit and l[i] <= t2P:
                    t2hit, pnl, rem, sP, hit, legs = True, pnl + 0.3 * (eP - t2P), rem - 0.3, t1P, True, legs + 1
                if l[i] <= t3P:
                    pnl += rem * (eP - t3P)
                    legs += 1
                    ex = "3"
                elif hit and params.intrabar_stop_after_target and c[i] >= sP:
                    pnl += rem * (eP - sP)
                    legs += 1
                    ex = "B"
        if pos != 0 and ex == "" and (cl["mins_close"][i] >= sq or cl["new_day"][i]):
            pnl += rem * pos * (c[i] - eP)
            legs += 1
            ex = "Q"
        exited_now = bool(ex)
        if ex:
            trades.append(Trade(e_time, "L" if pos == 1 else "S", sc, e_exp, eP, R, pnl, ex, i - e_bar,
                                pr.idx[i] + pd.Timedelta(minutes=pr.tf_min), e_grade, 1 + legs))
            r = pnl / R if R else 0.0
            losses_today += r < 0
            r_today += r
            realised += pnl
            pos = 0
        if mtm is not None:
            mtm.append(realised + (pnl + rem * pos * (c[i] - eP) if pos else 0.0))

        # ---------- signal ----------
        tr_i = trace.get(i) if trace is not None else None
        if pos != 0:
            if tr_i is not None:
                tr_i["blocked"] = "already in a trade"
            continue
        if exited_now and not params.allow_same_bar_reentry:
            if tr_i is not None:
                tr_i["blocked"] = "a trade exited on this bar"
            continue
        if (params.daily_max_losses and losses_today >= params.daily_max_losses) or \
                (params.daily_max_loss_r and r_today <= -params.daily_max_loss_r):
            if tr_i is not None:
                tr_i["blocked"] = "daily stop"
            continue
        mfo, mn, mc = cl["mins_from_open"][i], cl["mins_now"][i], cl["mins_close"][i]
        is_exp = bool(cl["is_exp"][i])
        t_entry = mc if params.close_time_cutoffs else mn
        lunch = (mn < 810 and mc > 750) if params.close_time_cutoffs else (750 <= mn < 810)
        time_ok = (mfo >= params.skip_open and t_entry <= last_e
                   and not (params.use_lunch and lunch)
                   and not (is_exp and t_entry > exp_cut))
        if not (time_ok and trades_today < params.max_trades and i - last_sig >= cooldown):
            if tr_i is not None:
                tr_i["blocked"] = "time/cap/cooldown"
            continue
        a = atrv[i]
        if math.isnan(a) or not _lt(cl["chop"][i], params.chop_max) or not abs(c[i] - o[i]) >= params.body_atr * a:
            if tr_i is not None:
                tr_i["blocked"] = f"chop {cl['chop'][i]:.0f} / body {abs(c[i] - o[i]) / a:.2f} ATR"
            continue
        rv, vz = cl["rvol"][i], cl["volz"][i]
        rv0, vz0 = (0.0 if math.isnan(rv) else rv), (0.0 if math.isnan(vz) else vz)
        if params.req_vol and not (rv0 >= rvol_thr and vz0 >= z_thr):
            if tr_i is not None:
                tr_i["blocked"] = "volume hard filter"
            continue
        green, red = c[i] > o[i], c[i] < o[i]
        long_brk, short_brk = _gt(c[i], brk_hi[i]) and green, _lt(c[i], brk_lo[i]) and red
        if not (long_brk or short_brk):
            if tr_i is not None:
                tr_i["blocked"] = "no breakout"
            continue
        vp = max(0.0, min(1.0, 0.6 * rv0 / rvol_thr + 0.4 * vz0 / z_thr))
        e9, e21, e50, vw = cl["e9"][i], cl["e21"][i], cl["e50"][i], cl["vw"][i]
        adx, dip, dim = cl["adx"][i], cl["dip"][i], cl["dim"][i]
        adx_ok = not math.isnan(adx) and adx >= adx_min
        adx_up = bool(cl["adx_up"][i])
        st = cl["st_dir"][i]
        lrs = cl["lr_slope"][i]
        upc = cl["up_cnt"][i]
        dnc = cl["dn_cnt"][i]
        oi_ok, ost = bool(cl["oi_ok"][i]), cl["oi_state"][i]
        hw_n = cl["hw_n"][i]
        vchg, vnow = cl["vix_chg"][i], cl["vix_now"][i]
        cvd = cl["cvd_slope"][i]
        htf_bull, htf_bear = _gt(cl["htf_c"][i], cl["htf_e"][i]), _lt(cl["htf_c"][i], cl["htf_e"][i])

        dir_l = (min(upc, 3) / 3 * 0.4 if not math.isnan(upc) else math.nan) + (0.3 if _gt(lrs, 0.05) else 0.0) + (0.3 if st < 0 else 0.0)
        dir_s = (min(dnc, 3) / 3 * 0.4 if not math.isnan(dnc) else math.nan) + (0.3 if _lt(lrs, -0.05) else 0.0) + (0.3 if st > 0 else 0.0)
        tr_l = (0.5 if (_gt(e9, e21) and _gt(e21, e50)) else 0.25 if _gt(e9, e21) else 0.0) + (0.5 if _gt(c[i], vw) else 0.0)
        tr_s = (0.5 if (_lt(e9, e21) and _lt(e21, e50)) else 0.25 if _lt(e9, e21) else 0.0) + (0.5 if _lt(c[i], vw) else 0.0)
        ax_l = (1.0 if adx_up else 0.7) if adx_ok and _gt(dip, dim) else 0.0
        ax_s = (1.0 if adx_up else 0.7) if adx_ok and _gt(dim, dip) else 0.0
        oi_l = (1.0 if ost == "LB" else 0.6 if ost == "SC" else 0.0) if oi_ok else math.nan
        oi_s = (1.0 if ost == "SB" else 0.6 if ost == "LU" else 0.0) if oi_ok else math.nan
        hw_l = cl["hw_up"][i] / hw_n if hw_n > 0 else math.nan
        hw_s = cl["hw_dn"][i] / hw_n if hw_n > 0 else math.nan
        vx_l = math.nan if math.isnan(vchg) else (1.0 if vchg <= 0 else 0.4 if _lt(vnow, params.vix_hi) else 0.0)
        vx_s = math.nan if math.isnan(vchg) else (1.0 if vchg >= 0 else 0.4)
        sL = _score(w, vp if green else 0.0, dir_l, tr_l, ax_l, 1.0 if htf_bull else 0.0,
                    1.0 if _gt(cvd, 0) else 0.0, oi_l, hw_l, vx_l)
        sS = _score(w, vp if red else 0.0, dir_s, tr_s, ax_s, 1.0 if htf_bear else 0.0,
                    1.0 if _lt(cvd, 0) else 0.0, oi_s, hw_s, vx_s)
        min_score = pre_score + (params.exp_boost if is_exp else 0)

        sl_l = min(sl_lraw[i], c[i] - params.min_risk_atr * a)
        sl_s = max(sl_sraw[i], c[i] + params.min_risk_atr * a)
        risk_l, risk_s = c[i] - sl_l, sl_s - c[i]

        def near(levels, above):
            best = math.nan
            for lv in levels:
                if math.isnan(lv):
                    continue
                if above and lv > c[i] and (math.isnan(best) or lv < best):
                    best = lv
                if not above and lv < c[i] and (math.isnan(best) or lv > best):
                    best = lv
            return best

        go_l = go_s = False
        room = math.nan
        min_risk = params.min_risk_pct / 100 * c[i]
        if long_brk and min_risk <= risk_l <= params.max_risk_atr * a and _gt(sL, sS) and sL >= min_score:
            na_ = near([cl[k][i] for k in ("pdh", "pdc", "r1", "tc", "pp", "bc", "orh", "vwu2")], True)
            room = (na_ - c[i]) / risk_l if not math.isnan(na_) else math.inf
            go_l = math.isnan(na_) or (na_ - c[i]) >= params.room_r * risk_l
        if short_brk and min_risk <= risk_s <= params.max_risk_atr * a and _gt(sS, sL) and sS >= min_score:
            nb = near([cl[k][i] for k in ("pdl", "pdc", "s1", "bc", "pp", "tc", "orl", "vwl2")], False)
            room = (c[i] - nb) / risk_s if not math.isnan(nb) else math.inf
            go_s = math.isnan(nb) or (c[i] - nb) >= params.room_r * risk_s
        if tr_i is not None:
            tr_i.update(side="L" if long_brk else "S", sL=round(sL, 1), sS=round(sS, 1), min=min_score,
                        risk_atr=round((risk_l if long_brk else risk_s) / a, 2), room_R=room,
                        parts_L=[round(x, 2) if not math.isnan(x) else None for x in (vp if green else 0, dir_l, tr_l, ax_l, float(htf_bull), float(_gt(cvd, 0)), oi_l, hw_l, vx_l)],
                        parts_S=[round(x, 2) if not math.isnan(x) else None for x in (vp if red else 0, dir_s, tr_s, ax_s, float(htf_bear), float(_lt(cvd, 0)), oi_s, hw_s, vx_s)],
                        rvol=rv, volz=vz, blocked="" if (go_l or go_s) else "score/risk/room")
        if go_l or go_s:
            pos = 1 if go_l else -1
            eP = c[i]
            sP = sl_l if go_l else sl_s
            R = abs(eP - sP)
            t1P, t2P, t3P = eP + pos * params.r1m * R, eP + pos * params.r2m * R, eP + pos * params.r3m * R
            t1hit = t2hit = False
            rem, pnl, legs = 1.0, 0.0, 0
            trades_today += 1
            last_sig = i
            e_bar = i
            e_time = pr.idx[i] + pd.Timedelta(minutes=pr.tf_min)
            sc = sL if go_l else sS
            e_grade = "A+" if sc >= params.a_plus else "A"
            e_exp = is_exp
    if open_out is not None and pos != 0:
        open_out.append(Trade(e_time, "L" if pos == 1 else "S", sc, e_exp, eP, R, pnl, "", n - 1 - e_bar, None,
                              e_grade, 1 + legs))
    return trades
