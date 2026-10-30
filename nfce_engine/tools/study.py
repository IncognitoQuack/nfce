"""Study engine: many intraday indicator rules at once, after costs, with multiple-testing control
(../evidence/study_engine_protocol.md).

  python tools/study.py train      [--workers 6]                      (2022-23, every rule)
  python tools/study.py validation [--workers 6]                      (2024, the train-chosen candidates only)
  python tools/study.py final --i-accept-one-shot [--workers 6]       (2025-01 .. 2026-10-21, validation survivors only)
  python tools/study.py report                                        (result .md + every rule's .csv)
  python tools/study.py costcheck                                     (live minute quotes vs the cost model)

No look-ahead: an indicator's value at bar t uses bars <= t; the entry is the open of bar t+1 (same day).
Costs, exits and the walk are the stock 3m research's (stock3m_research / wide_stop): futures fees at the current
schedule plus 0.02% friction per side on ~Rs 7 L notional; index futures at one lot plus 4 ticks per side.
"""
from __future__ import annotations

import argparse
import hashlib
import math
import pickle
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date
from multiprocessing import get_context
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce import costs  # noqa: E402
from nfce.research2 import daily  # noqa: E402

TZ = "Asia/Kolkata"
ROOT = Path(__file__).resolve().parents[2]
DATA = Path.home() / "Downloads" / "nfce_data"
HIST3M, HIST5M = DATA / "hist3m_fo", DATA / "hist5m_index"
WORK = DATA / "study_engine"
PROTOCOL = ROOT / "evidence" / "study_engine_protocol.md"
CSV = ROOT / "evidence" / "study_engine_rules.csv"
QUOTES = [ROOT / "nfce_bridge" / "data" / f"study_quotes_{d}.db" for d in ("20261022", "20261023")]

STAGES = {"train": (date(2022, 1, 1), date(2023, 12, 31)), "validation": (date(2024, 1, 1), date(2024, 12, 31)),
          "final": (date(2025, 1, 1), date(2026, 10, 21))}
NOTIONAL, FRICTION = 700_000, 0.0002                 # = stock3m_research
INDEX = {"NIFTY": (65, 0.1), "BANKNIFTY": (30, 0.2)}  # lot units, tick (= research_run.INDEX)
R_ATR = 0.25                                          # R = 0.25 x the prior days' daily ATR14
EXITS = (1, 2, 4)                                     # stop = target = k x R, all out (wide_stop.py)
WINDOWS = {"ALL": 14 * 60 + 30, "AM": 11 * 60}        # the signal bar must CLOSE by this time
REGIMES = ("ALL", "VIXHI", "VIXLO")
OPEN = 9 * 60 + 15
MIN_TRAIN, MIN_VAL = 100, 30
ALPHA, DSR_MIN = 0.05, 0.95


# ---------------------------------------------------------------- the per-instrument frame
def frame(b: pd.DataFrame, tf: int) -> pd.DataFrame:
    """Regular-session bars with helper columns. Daily values (prev_*, atr_prev, nr7, inside) use days < t only."""
    d = b[["open", "high", "low", "close", "volume"]].astype(float).copy()
    d.index = pd.DatetimeIndex(d.index).tz_convert(TZ)
    d = d[~d.index.duplicated(keep="first")].sort_index()
    hm = d.index.hour * 60 + d.index.minute
    d = d[(hm >= OPEN) & (hm <= 15 * 60 + 30 - tf)]
    d["volume"] = d["volume"].fillna(0.0)
    key = d.index.normalize()
    cnt = pd.Series(1, index=d.index).groupby(key).transform("size")
    d = d[cnt.to_numpy() >= 0.5 * (375 // tf)]          # drops special (Muhurat-type) and broken sessions
    key = d.index.normalize()
    d["hm"] = d.index.hour * 60 + d.index.minute
    d["slot"] = (d["hm"] - OPEN) // tf
    d["day"] = key.tz_localize(None)
    dd = daily(d)
    rng = dd["high"] - dd["low"]
    dd["prev_high"], dd["prev_low"], dd["prev_close"] = dd["high"].shift(1), dd["low"].shift(1), dd["close"].shift(1)
    dd["nr7"] = (rng <= rng.rolling(7, min_periods=7).min()).shift(1, fill_value=False).astype(bool)
    dd["inside"] = ((dd["high"] < dd["high"].shift(1)) & (dd["low"] > dd["low"].shift(1))).shift(1, fill_value=False)
    for c in ("open", "prev_high", "prev_low", "prev_close", "atr_prev", "nr7", "inside"):
        d["day_open" if c == "open" else c] = dd[c].reindex(key).to_numpy()
    d["first"] = np.r_[True, d["day"].to_numpy()[1:] != d["day"].to_numpy()[:-1]]
    tp = (d["high"] + d["low"] + d["close"]) / 3
    cv = d["volume"].groupby(key).cumsum()
    d["vwap"] = ((tp * d["volume"]).groupby(key).cumsum() / cv.where(cv > 0)).to_numpy()
    return d


# ---------------------------------------------------------------- indicator maths (pure, causal)
def ema(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(span=n, adjust=False).mean()


def rma(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(alpha=1 / n, adjust=False).mean()


def rsi(c: pd.Series, n: int) -> pd.Series:
    dl = c.diff()
    up, dn = rma(dl.clip(lower=0), n), rma(-dl.clip(upper=0), n)
    return 100 - 100 / (1 + up / dn)


def true_range(d: pd.DataFrame) -> pd.Series:
    pc = d["close"].shift(1)
    return pd.concat([d["high"] - d["low"], (d["high"] - pc).abs(), (d["low"] - pc).abs()], axis=1).max(axis=1)


def supertrend_dir(d: pd.DataFrame, n: int, m: float) -> np.ndarray:
    a = rma(true_range(d), n).to_numpy()
    h, l, c = d["high"].to_numpy(), d["low"].to_numpy(), d["close"].to_numpy()
    mid = (h + l) / 2
    ub, lb = mid + m * a, mid - m * a
    out = np.zeros(len(c), dtype=np.int8)
    fu, fl, dr = np.nan, np.nan, 1
    for i in range(len(c)):
        if i == 0 or not np.isfinite(a[i]):
            fu, fl = ub[i], lb[i]
            out[i] = dr
            continue
        fu = ub[i] if (ub[i] < fu or c[i - 1] > fu or not np.isfinite(fu)) else fu
        fl = lb[i] if (lb[i] > fl or c[i - 1] < fl or not np.isfinite(fl)) else fl
        if dr == 1 and c[i] < fl:
            dr = -1
        elif dr == -1 and c[i] > fu:
            dr = 1
        out[i] = dr
    return out


def dmi(d: pd.DataFrame, n: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    up, dn = d["high"].diff(), -d["low"].diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=d.index)
    mdm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=d.index)
    tr = rma(true_range(d), n)
    pdi, mdi = 100 * rma(pdm, n) / tr, 100 * rma(mdm, n) / tr
    adx = rma(100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan), n)
    return pdi, mdi, adx


def xup(a: pd.Series, b) -> np.ndarray:
    """a crosses above b at this bar (b a series: its own previous value; a scalar: the level)."""
    bp = b.shift(1) if isinstance(b, pd.Series) else b
    return ((a > b) & (a.shift(1) <= bp)).to_numpy()


def xdn(a: pd.Series, b) -> np.ndarray:
    bp = b.shift(1) if isinstance(b, pd.Series) else b
    return ((a < b) & (a.shift(1) >= bp)).to_numpy()


def level_up(c: pd.Series, lvl: pd.Series) -> np.ndarray:
    """close crosses above a level that is fixed for the day (judged against today's level for both bars)."""
    return ((c > lvl) & (c.shift(1) <= lvl)).to_numpy()


def level_dn(c: pd.Series, lvl: pd.Series) -> np.ndarray:
    return ((c < lvl) & (c.shift(1) >= lvl)).to_numpy()


def opening_range(d: pd.DataFrame, minutes: int) -> tuple[pd.Series, pd.Series, np.ndarray]:
    inr = d["hm"] < OPEN + minutes
    hi = d["high"].where(inr).groupby(d["day"]).transform("max")
    lo = d["low"].where(inr).groupby(d["day"]).transform("min")
    return hi, lo, (~inr).to_numpy()


# ---------------------------------------------------------------- signals: fn(frame, *params) -> (long, short)
def s_rsi_mr(d, n, lo):
    r = rsi(d["close"], n)
    return xup(r, lo), xdn(r, 100 - lo)


def s_rsi_tr(d, n, hi):
    r = rsi(d["close"], n)
    return xup(r, hi), xdn(r, 100 - hi)


def s_macd(d, f, s, g):
    m = ema(d["close"], f) - ema(d["close"], s)
    sg = ema(m, g)
    return xup(m, sg), xdn(m, sg)


def _bb(d, n, k):
    ma = d["close"].rolling(n).mean()
    sd = d["close"].rolling(n).std(ddof=0)
    return ma + k * sd, ma - k * sd


def s_bb_brk(d, n, k):
    up, lo = _bb(d, n, k)
    return xup(d["close"], up), xdn(d["close"], lo)


def s_bb_fade(d, n, k):
    up, lo = _bb(d, n, k)
    return xup(d["close"], lo), xdn(d["close"], up)


def s_st(d, n, m):
    dr = supertrend_dir(d, n, m)
    prev = np.r_[dr[0], dr[:-1]]
    return (dr == 1) & (prev == -1), (dr == -1) & (prev == 1)


def s_vwap_x(d, b):
    nf = ~d["first"].to_numpy()
    c, v = d["close"], d["vwap"]
    return xup(c, v * (1 + b)) & nf, xdn(c, v * (1 - b)) & nf


def s_vwap_mr(d, k):
    nf = ~d["first"].to_numpy()
    c, v = d["close"], d["vwap"]
    return xdn(c, v * (1 - k)) & nf, xup(c, v * (1 + k)) & nf


def s_orb(d, minutes):
    hi, lo, after = opening_range(d, minutes)
    return after & (d["close"] > hi).to_numpy(), after & (d["close"] < lo).to_numpy()


def s_ema_x(d, f, s):
    a, b = ema(d["close"], f), ema(d["close"], s)
    return xup(a, b), xdn(a, b)


def s_adx(d, th):
    pdi, mdi, adx = dmi(d, 14)
    strong = (adx > th).to_numpy()
    return xup(pdi, mdi) & strong, xup(mdi, pdi) & strong


def rvol(d: pd.DataFrame, days: int = 10) -> np.ndarray:
    """Bar volume / the mean volume of the same time slot over the previous `days` sessions."""
    pv = d.pivot_table(index="day", columns="slot", values="volume", aggfunc="sum")
    base = pv.rolling(days, min_periods=days).mean().shift(1)
    di = base.index.get_indexer(d["day"])
    si = base.columns.get_indexer(d["slot"])
    v = base.to_numpy()[di, si]
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(v > 0, d["volume"].to_numpy() / v, np.nan)


def s_rvol(d, k):
    surge = rvol(d) >= k
    return surge & (d["close"] > d["open"]).to_numpy(), surge & (d["close"] < d["open"]).to_numpy()


def _gap(d):
    return (d["day_open"] / d["prev_close"] - 1).to_numpy(), d["first"].to_numpy()


def s_gap_cont(d, g):
    gp, f = _gap(d)
    return f & (gp >= g), f & (gp <= -g)


def s_gap_fade(d, g):
    gp, f = _gap(d)
    return f & (gp <= -g), f & (gp >= g)


def s_pdhl(d, b):
    return level_up(d["close"], d["prev_high"] * (1 + b)), level_dn(d["close"], d["prev_low"] * (1 - b))


def s_nr_orb(d, kind):
    flag = d[kind].astype(bool).to_numpy()
    lg, sh = s_orb(d, 15)
    return lg & flag, sh & flag


@dataclass(frozen=True)
class Ind:
    fn: object
    params: tuple
    volume: bool = False          # needs real volume (not on the index files)
    open_only: bool = False       # fires on the first bar only: one time window


INDICATORS: dict[str, Ind] = {
    "RSI_MR": Ind(s_rsi_mr, ((14, 30), (14, 25), (7, 20))),
    "RSI_TR": Ind(s_rsi_tr, ((14, 60), (14, 70), (7, 70))),
    "MACD": Ind(s_macd, ((12, 26, 9), (6, 13, 5))),
    "BB_BRK": Ind(s_bb_brk, ((20, 2.0), (20, 2.5))),
    "BB_FADE": Ind(s_bb_fade, ((20, 2.0), (20, 2.5))),
    "ST": Ind(s_st, ((10, 3.0), (10, 2.0))),
    "VWAP_X": Ind(s_vwap_x, ((0.0,), (0.002,)), volume=True),
    "VWAP_MR": Ind(s_vwap_mr, ((0.0075,), (0.015,)), volume=True),
    "ORB": Ind(s_orb, ((15,), (30,))),
    "EMA_X": Ind(s_ema_x, ((9, 21), (5, 13), (20, 50))),
    "ADX_DI": Ind(s_adx, ((20,), (25,))),
    "RVOL": Ind(s_rvol, ((3.0,), (5.0,)), volume=True),
    "GAP_CONT": Ind(s_gap_cont, ((0.005,), (0.01,), (0.02,)), open_only=True),
    "GAP_FADE": Ind(s_gap_fade, ((0.005,), (0.01,), (0.02,)), open_only=True),
    "PDHL": Ind(s_pdhl, ((0.0,), (0.0025,))),
    "NR_ORB": Ind(s_nr_orb, (("nr7",), ("inside",))),
}


# ---------------------------------------------------------------- the rule grid
@dataclass(frozen=True)
class Rule:
    ind: str
    param: tuple
    side: int
    k: int
    window: str
    regime: str
    univ: str

    @property
    def id(self) -> str:
        return f"{self.family}|{','.join(map(str, self.param))}"

    @property
    def family(self) -> str:
        return f"{self.ind}|{'L' if self.side > 0 else 'S'}|K{self.k}|{self.window}|{self.regime}|{self.univ}"


def grid() -> list[Rule]:
    out = []
    for univ in ("STK", "IDX"):
        for name, ind in INDICATORS.items():
            if univ == "IDX" and ind.volume:
                continue
            for p in ind.params:
                for side in (1, -1):
                    for k in EXITS:
                        for w in (("ALL",) if ind.open_only else tuple(WINDOWS)):
                            for rg in REGIMES:
                                out.append(Rule(name, p, side, k, w, rg, univ))
    return out


# ---------------------------------------------------------------- entries, the walk, costs
def entries(d: pd.DataFrame, sig: np.ndarray, tf: int, cutoff: int) -> np.ndarray:
    """Positions of entry bars: the bar after the day's FIRST qualifying signal bar, on the same day."""
    day = d["day"].to_numpy()
    nxt_same = np.r_[day[1:] == day[:-1], False]
    ok = sig & nxt_same & (d["hm"].to_numpy() + tf <= cutoff)
    idx = np.flatnonzero(ok)
    if not len(idx):
        return idx
    _, first = np.unique(day[idx], return_index=True)
    return idx[first] + 1


@dataclass
class Grid:
    """Day x slot matrices of one instrument, for a vectorised walk."""
    O: np.ndarray
    H: np.ndarray
    L: np.ndarray
    C: np.ndarray
    eodj: np.ndarray
    row: np.ndarray          # bar position -> day row
    slot: np.ndarray         # bar position -> slot


def make_grid(d: pd.DataFrame, tf: int) -> Grid:
    days, row = np.unique(d["day"].to_numpy(), return_inverse=True)
    S = 375 // tf
    slot = d["slot"].to_numpy().astype(int)
    mats = []
    for c in ("open", "high", "low", "close"):
        m = np.full((len(days), S), np.nan)
        m[row, slot] = d[c].to_numpy()
        mats.append(m)
    E = (15 * 60 + 15 - tf - OPEN) // tf                  # the bar closing 15:15
    valid = np.isfinite(mats[3][:, :E + 1])
    eodj = np.where(valid.any(1), E - np.argmax(valid[:, ::-1], axis=1), -1)
    return Grid(*mats, eodj, row, slot)


def walk(g: Grid, pos: np.ndarray, side: int, stop: np.ndarray, tgt: np.ndarray):
    """research2._walk, vectorised: from the entry bar (inclusive), stop before target in one bar, else the 15:15 close.
    Returns (exit price, reason 0 stop / 1 target / 2 eod)."""
    r, j0 = g.row[pos], g.slot[pos]
    je = g.eodj[r]
    S = g.O.shape[1]
    cols = np.arange(S)
    act = (cols >= j0[:, None]) & (cols <= je[:, None])
    H, L = g.H[r], g.L[r]
    if side > 0:
        hs, ht = (L <= stop[:, None]) & act, (H >= tgt[:, None]) & act
    else:
        hs, ht = (H >= stop[:, None]) & act, (L <= tgt[:, None]) & act
    big = S + 1
    js = np.where(hs.any(1), hs.argmax(1), big)
    jt = np.where(ht.any(1), ht.argmax(1), big)
    reason = np.where((js <= jt) & (js <= je), 0, np.where(jt <= je, 1, 2))
    jx = np.where(reason == 0, js, np.where(reason == 1, jt, je))
    ox = g.O[r, np.minimum(jx, S - 1)]
    sp = np.where(jx == j0, stop, np.minimum(ox, stop) if side > 0 else np.maximum(ox, stop))
    px = np.where(reason == 0, sp, np.where(reason == 1, tgt, g.C[r, np.minimum(jx, S - 1)]))
    return px, reason


def cost_points(entry: np.ndarray, px: np.ndarray, side: int, units, friction) -> np.ndarray:
    """costs.futures_cost_points on arrays (the function is plain arithmetic once `side` is one scalar)."""
    return np.asarray(costs.futures_cost_points(entry, px, side, costs.CURRENT, units, 1, 2, friction), dtype=float)


# ---------------------------------------------------------------- one instrument -> per (rule, day) sums
FIELDS = ("n", "net", "gross", "win", "pos_inr", "neg_inr", "stop", "target", "share")


def vix_regime(vix: pd.DataFrame) -> pd.Series:
    """Per day: 'VIXHI' if the previous close of INDIA VIX is above the median of the 20 closes before it."""
    v = vix["close"].groupby(pd.DatetimeIndex(vix.index).tz_convert(TZ).normalize().tz_localize(None)).last()
    prev = v.shift(1)
    med = v.shift(2).rolling(20, min_periods=20).median()
    out = pd.Series(np.where(prev > med, "VIXHI", "VIXLO"), index=v.index)
    return out[prev.notna() & med.notna()]


def instrument(d: pd.DataFrame, tf: int, univ: str, rules: dict, days: pd.DatetimeIndex, regime: pd.Series,
               lot: tuple | None = None, acc: np.ndarray | None = None) -> np.ndarray:
    """Simulate every wanted rule of `univ` on one instrument; add its trades into acc[rule, day, field].
    rules: {Rule: row index in acc}. Only trades whose day is in `days` (the stage) are kept."""
    if acc is None:
        acc = np.zeros((max(rules.values(), default=-1) + 1, len(days), len(FIELDS)))
    g = make_grid(d, tf)
    dayv = d["day"].to_numpy()
    R_all = R_ATR * d["atr_prev"].to_numpy()
    opn = d["open"].to_numpy()
    dpos = days.get_indexer(pd.DatetimeIndex(dayv))
    reg = regime.reindex(pd.DatetimeIndex(dayv)).to_numpy()
    wanted: dict = {}
    for r, i in rules.items():
        if r.univ == univ:
            wanted.setdefault((r.ind, r.param), []).append((r, i))
    for (name, p), lst in wanted.items():
        lg, sh = INDICATORS[name].fn(d, *p)
        for side, sig in ((1, np.asarray(lg, bool)), (-1, np.asarray(sh, bool))):
            for w in {r.window for r, _ in lst if r.side == side}:
                pos = entries(d, sig, tf, WINDOWS[w])
                pos = pos[(dpos[pos] >= 0) & np.isfinite(R_all[pos]) & (R_all[pos] > 0) & np.isfinite(opn[pos])]
                if not len(pos):
                    continue
                entry, R0, di = opn[pos], R_all[pos], dpos[pos]
                units = np.maximum(1, np.round(NOTIONAL / entry)) if lot is None else float(lot[0])
                fric = FRICTION * entry if lot is None else 4 * lot[1]
                for k in {r.k for r, _ in lst if r.side == side and r.window == w}:
                    R = k * R0
                    px, why = walk(g, pos, side, entry - side * R, entry + side * R)
                    c = cost_points(entry, px, side, units, fric)
                    gross = side * (px - entry)
                    inr = (gross - c) * units
                    vals = np.stack([np.ones_like(R), (gross - c) / R, gross / R, (gross - c > 0).astype(float),
                                     np.where(inr > 0, inr, 0.0), np.where(inr < 0, -inr, 0.0),
                                     (why == 0).astype(float), (why == 1).astype(float), c / R], axis=1)
                    for r, i in lst:
                        if r.side != side or r.window != w or r.k != k:
                            continue
                        m = np.ones(len(pos), bool) if r.regime == "ALL" else (reg[pos] == r.regime)
                        if m.any():
                            np.add.at(acc[i], di[m], vals[m])
    return acc


def load_bars(path: Path) -> pd.DataFrame:
    return pd.read_pickle(path)


def _work(job):
    files, rules, days, regime = job
    acc = np.zeros((len(rules), len(days), len(FIELDS)))
    idx = {r: i for i, r in enumerate(rules)}
    for path, univ, tf, lot in files:
        d = frame(load_bars(path), tf)
        instrument(d, tf, univ, idx, days, regime, lot, acc)
    return acc


def run_stage(rules: list[Rule], stage: str, workers: int) -> dict:
    a, b = STAGES[stage]
    vix = load_bars(HIST3M / "INDIAVIX_3m.pkl")
    vday = pd.DatetimeIndex(frame(vix, 3)["day"].unique())
    days = vday[(vday >= pd.Timestamp(a)) & (vday <= pd.Timestamp(b))]
    regime = vix_regime(vix)
    files = []
    if any(r.univ == "STK" for r in rules):
        files += [(f, "STK", 3, None) for f in sorted(HIST3M.glob("*_3m.pkl")) if f.stem != "INDIAVIX_3m"]
    if any(r.univ == "IDX" for r in rules):
        files += [(HIST5M / f"{ix}_5m.pkl", "IDX", 5, INDEX[ix]) for ix in INDEX]
    jobs = [(files[i::workers], rules, days, regime) for i in range(workers)]
    with get_context("spawn").Pool(workers) as pool:
        acc = sum(pool.map(_work, jobs))
    return {"stage": stage, "rules": rules, "days": days, "acc": acc, "protocol_sha": protocol_sha(),
            "instruments": len(files)}


# ---------------------------------------------------------------- statistics
def rule_stats(t: np.ndarray, days: pd.DatetimeIndex) -> dict:
    """t: (days, FIELDS) sums of one rule. Day-level t-test on the day means (house p(day))."""
    from scipy.stats import t as student
    n = t[:, 0]
    N = n.sum()
    if N == 0:
        return {"n": 0}
    has = n > 0
    dm = t[has, 1] / n[has]
    sd = dm.std(ddof=1) if len(dm) > 1 else 0.0
    tt = dm.mean() / (sd / math.sqrt(len(dm))) if sd > 0 else 0.0
    neg = t[:, 5].sum()
    years = {}
    for y in sorted(set(days.year)):
        m = days.year == y
        if n[m].sum():
            years[int(y)] = float(t[m, 1].sum() / n[m].sum())
    return {"n": int(N), "days": int(has.sum()), "win": float(t[:, 3].sum() / N), "gross_r": float(t[:, 2].sum() / N),
            "net_r": float(t[:, 1].sum() / N), "t_day": float(tt),
            "p_day": float(student.sf(tt, len(dm) - 1)) if len(dm) > 1 else 1.0,
            "pf": float(t[:, 4].sum() / neg) if neg > 0 else math.inf, "inr": float(t[:, 4].sum() - neg),
            "stop": float(t[:, 6].sum() / N), "target": float(t[:, 7].sum() / N), "share": float(t[:, 8].sum() / N),
            "years": years}


def day_series(t: np.ndarray) -> np.ndarray:
    """Daily mean net R per trade (one unit of risk a day, split over the day's trades); 0 on days with no trade."""
    n = t[:, 0]
    return np.where(n > 0, t[:, 1] / np.where(n > 0, n, 1), 0.0)


def block_ci(t: np.ndarray, b: int = 2000, seed: int = 7) -> tuple[float, float]:
    """95% interval of the per-trade mean, resampling whole trade days (= nfce.stats.block_bootstrap_mean)."""
    has = t[:, 0] > 0
    s, n = t[has, 1], t[has, 0]
    if not len(s):
        return (math.nan, math.nan)
    idx = np.random.default_rng(seed).integers(0, len(s), (b, len(s)))
    m = np.sort(s[idx].sum(1) / n[idx].sum(1))
    return float(m[int(0.025 * b)]), float(m[int(0.975 * b) - 1])


def holm_adjust(p: np.ndarray, m: int | None = None) -> np.ndarray:
    """Holm step-down adjusted p-values; m = the family size (>= len(p): untested members count as p = 1)."""
    p = np.asarray(p, float)
    m = len(p) if m is None else m
    o = np.argsort(p)
    adj = np.minimum(1.0, np.maximum.accumulate((m - np.arange(len(p))) * p[o]))
    out = np.empty_like(adj)
    out[o] = adj
    return out


def stationary_indices(n: int, b: int, block: float, seed: int) -> np.ndarray:
    """Politis-Romano stationary bootstrap: b resamples of n day indices, mean block length `block`."""
    rng = np.random.default_rng(seed)
    idx = np.empty((b, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, b)
    new = rng.random((b, n)) < 1 / block
    starts = rng.integers(0, n, (b, n))
    for j in range(1, n):
        idx[:, j] = np.where(new[:, j], starts[:, j], (idx[:, j - 1] + 1) % n)
    return idx


def spa(X: np.ndarray, b: int = 1000, block: float = 5.0, seed: int = 11) -> dict:
    """White's reality check and Hansen's SPA (consistent) for H0: no rule beats zero (= not trading).
    X: (days, rules) daily performance. Rules with no variation are left out."""
    X = X[:, X.std(0) > 0]
    n, K = X.shape
    if K == 0:
        return {"rules": 0, "rc_p": 1.0, "spa_p": 1.0, "best": None}
    mu = X.mean(0)
    idx = stationary_indices(n, b, block, seed)
    boot = np.stack([X[i].mean(0) for i in idx])                     # (b, K)
    omega = np.sqrt(n * boot.var(0))
    omega = np.where(omega > 0, omega, np.inf)
    v_rc = math.sqrt(n) * mu.max()
    rc = np.sqrt(n) * (boot - mu).max(1)
    t_spa = max(float((math.sqrt(n) * mu / omega).max()), 0.0)
    keep = mu >= -omega / math.sqrt(n) * math.sqrt(2 * math.log(math.log(n)))
    z = boot - np.where(keep, mu, 0.0)
    t_b = np.maximum((math.sqrt(n) * z / omega).max(1), 0.0)
    return {"rules": int(K), "rc_p": float((rc >= v_rc).mean()), "spa_p": float((t_b >= t_spa).mean()),
            "best": int(np.argmax(mu))}


def expected_max_sr(var_sr: float, n_trials: int) -> float:
    """Bailey & Lopez de Prado: the expected maximum Sharpe of n_trials skill-less trials."""
    from scipy.stats import norm
    g = 0.5772156649
    if n_trials < 2 or var_sr <= 0:
        return 0.0
    return math.sqrt(var_sr) * ((1 - g) * norm.ppf(1 - 1 / n_trials) + g * norm.ppf(1 - 1 / (n_trials * math.e)))


def deflated_sharpe(x: np.ndarray, var_sr: float, n_trials: int) -> float:
    """Probability that the true (per-day) Sharpe of x exceeds the best of n_trials lucky ones."""
    from scipy.stats import kurtosis, norm, skew
    x = np.asarray(x, float)
    T = len(x)
    if T < 3 or x.std(ddof=1) == 0:
        return 0.0
    sr = x.mean() / x.std(ddof=1)
    sr0 = expected_max_sr(var_sr, n_trials)
    den = 1 - skew(x) * sr + (kurtosis(x, fisher=False) - 1) / 4 * sr ** 2
    return float(norm.cdf((sr - sr0) * math.sqrt(T - 1) / math.sqrt(max(den, 1e-12))))


def pbo_cscv(X: np.ndarray, S: int = 16) -> dict:
    """Probability of backtest overfitting by combinatorially symmetric cross-validation (Bailey, Borwein,
    Lopez de Prado, Zhu; SSRN 2326253). X: (days, trials). The days are cut into S contiguous blocks; for every way
    of choosing S/2 blocks as in-sample, the in-sample best trial (per-day Sharpe) is ranked out of sample.
    PBO = the share of splits where it lands at or below the out-of-sample median (logit <= 0)."""
    from itertools import combinations
    X = X[:, X.std(0) > 0]
    T, N = X.shape
    if N < 2 or T < 2 * S:
        return {"pbo": math.nan, "splits": 0, "trials": int(N)}
    T = T - T % S
    blocks = X[:T].reshape(S, T // S, N)
    s1, s2, n = blocks.sum(1), (blocks ** 2).sum(1), T // S         # (S, N) block sums, sums of squares
    tot1, tot2 = s1.sum(0), s2.sum(0)
    logits, degr = [], []
    for ins in combinations(range(S), S // 2):
        i = list(ins)
        a1, a2 = s1[i].sum(0), s2[i].sum(0)
        m_in = n * S // 2
        b1, b2 = tot1 - a1, tot2 - a2
        sr_in = (a1 / m_in) / np.sqrt(np.maximum(a2 / m_in - (a1 / m_in) ** 2, 1e-18))
        sr_out = (b1 / m_in) / np.sqrt(np.maximum(b2 / m_in - (b1 / m_in) ** 2, 1e-18))
        k = int(np.argmax(sr_in))
        rank = (sr_out < sr_out[k]).sum() + 0.5 * ((sr_out == sr_out[k]).sum() - 1) + 1   # 1 = worst, N = best
        w = rank / (N + 1)
        logits.append(math.log(w / (1 - w)))
        degr.append((sr_in[k], sr_out[k]))
    lg = np.array(logits)
    d = np.array(degr)
    return {"pbo": float((lg <= 0).mean()), "splits": len(lg), "trials": int(N), "logit_median": float(np.median(lg)),
            "is_best_sr": float(d[:, 0].mean()), "oos_sr_of_is_best": float(d[:, 1].mean()),
            "oos_loss_share": float((d[:, 1] < 0).mean())}


def sharpe(x: np.ndarray) -> float:
    s = np.std(x, ddof=1)
    return float(np.mean(x) / s) if s > 0 else 0.0


# ---------------------------------------------------------------- stage logic
def select(train: dict) -> list[Rule]:
    """Per family (everything but the parameter setting): the setting with the best train net R per trade among
    those with >= MIN_TRAIN trades; a candidate only if that net R is above zero."""
    best: dict = {}
    for r, t in zip(train["rules"], train["acc"]):
        s = rule_stats(t, train["days"])
        if s["n"] < MIN_TRAIN:
            continue
        if r.family not in best or s["net_r"] > best[r.family][1]:
            best[r.family] = (r, s["net_r"])
    return [r for r, v in best.values() if v > 0]


def judge_validation(val: dict, n_total: int, var_sr: float) -> list[dict]:
    rows = []
    for r, t in zip(val["rules"], val["acc"]):
        s = rule_stats(t, val["days"])
        x = day_series(t)
        rows.append({"rule": r, **s, "dsr": deflated_sharpe(x, var_sr, n_total) if s["n"] else 0.0})
    p = np.array([x.get("p_day", 1.0) for x in rows])
    adj = holm_adjust(p, max(n_total, len(p))) if len(p) else p
    adj_c = holm_adjust(p) if len(p) else p
    for x, a, ac in zip(rows, adj, adj_c):
        x["holm_all"], x["holm_cand"] = float(a), float(ac)
        x["pass"] = bool(x["n"] >= MIN_VAL and x["net_r"] > 0 and a < ALPHA and x["dsr"] >= DSR_MIN)
    return rows


def judge_final(fin: dict, n_total: int, var_sr: float) -> list[dict]:
    rows = []
    k = max(1, len(fin["rules"]))
    for r, t in zip(fin["rules"], fin["acc"]):
        s = rule_stats(t, fin["days"])
        ok = s["n"] > 0
        rows.append({"rule": r, **s, "dsr": deflated_sharpe(day_series(t), var_sr, n_total) if ok else 0.0,
                     "ci": block_ci(t) if ok else (math.nan, math.nan),
                     "pass": bool(ok and s["net_r"] > 0 and s["p_day"] < ALPHA / k)})
    return rows


def protocol_sha() -> str | None:
    return hashlib.sha256(PROTOCOL.read_bytes()).hexdigest() if PROTOCOL.exists() else None


def _load(stage: str) -> dict | None:
    f = WORK / f"{stage}.pkl"
    return pickle.loads(f.read_bytes()) if f.exists() else None


def _save(stage: str, res: dict) -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / f"{stage}.pkl").write_bytes(pickle.dumps(res))


def train_trials(train: dict) -> tuple[np.ndarray, float]:
    """Per-day Sharpe of every rule with trades on train, and its variance across rules (the DSR's V[SR])."""
    srs = np.array([sharpe(day_series(t)) for t in train["acc"] if t[:, 0].sum() >= MIN_TRAIN])
    return srs, float(srs.var(ddof=1)) if len(srs) > 1 else 0.0


# ---------------------------------------------------------------- cost-model check (live quotes; never selects rules)
def cost_check(dbs: list[Path]) -> dict:
    """Quoted half-spread of stock and index futures in the recorded minute quotes vs the model's friction:
    stocks 0.02% of price per side, NIFTY 0.4 / BANKNIFTY 0.8 points per side. Also: can one ~Rs 7 L stock lot fill
    at the touch?"""
    rows = []
    for db in dbs:
        if not db.exists():
            continue
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        q = pd.read_sql_query("select ts, symbol, bid, ask, bid_qty, ask_qty from q "
                              "where symbol like 'NSE_FO:%FUT' and bid > 0 and ask >= bid", con)
        con.close()
        q["db"] = db.name
        rows.append(q)
    if not rows:
        return {"quotes": 0}
    q = pd.concat(rows, ignore_index=True)
    q["mid"] = (q["bid"] + q["ask"]) / 2
    q["half"] = (q["ask"] - q["bid"]) / 2
    q["half_rel"] = q["half"] / q["mid"]
    q["hm"] = pd.to_datetime(q["ts"].str[11:16], format="%H:%M").dt.hour * 60 + pd.to_datetime(
        q["ts"].str[11:16], format="%H:%M").dt.minute
    q["und"] = q["symbol"].str.slice(7).str.replace(r"\d{2}[A-Z]{3}FUT$", "", regex=True)
    ix = q[q["und"].isin(INDEX)]
    st = q[~q["und"].isin(INDEX) & (q["und"] != "SENSEX")]
    per = st.groupby("und")["half_rel"].median()
    early = st[st["hm"] < 9 * 60 + 30].groupby("und")["half_rel"].median()
    units = np.maximum(1, np.round(NOTIONAL / st["mid"]))
    out = {"quotes": int(len(q)), "dbs": sorted(q["db"].unique().tolist()), "stocks": int(len(per)),
           "model_stock_per_side": FRICTION,
           "stock_half_median": float(per.median()), "stock_half_p75": float(per.quantile(.75)),
           "stock_half_p90": float(per.quantile(.9)),
           "stock_over_model": float((per > FRICTION).mean()),
           "stock_half_open_median": float(early.median()) if len(early) else math.nan,
           "touch_fills_lot": float(((st["ask_qty"] >= units) & (st["bid_qty"] >= units)).mean()),
           "index": {}}
    for u, (lot, tick) in INDEX.items():
        x = ix[ix["und"] == u]
        if len(x):
            out["index"][u] = {"quotes": int(len(x)), "half_median_pts": float(x["half"].median()),
                               "half_p90_pts": float(x["half"].quantile(.9)), "model_pts": 4 * tick}
    return out


# ---------------------------------------------------------------- report
def _fmt(x, f="+.3f"):
    return "–" if x is None or (isinstance(x, float) and not math.isfinite(x)) else format(x, f)


def report(cc: dict | None = None) -> str:
    tr, va, fi = _load("train"), _load("validation"), _load("final")
    if tr is None:
        sys.exit("run the train stage first")
    n_total = len(tr["rules"])
    srs, var_sr = train_trials(tr)
    tstats = {r.id: rule_stats(t, tr["days"]) for r, t in zip(tr["rules"], tr["acc"])}
    X = np.stack([day_series(t) for t in tr["acc"]], 1)
    sp_tr = spa(X)
    cands = select(tr)
    vrows = judge_validation(va, n_total, var_sr) if va else []
    frows = judge_final(fi, n_total, var_sr) if fi else []
    sp_va = spa(np.stack([day_series(t) for t in va["acc"]], 1)) if va and len(va["rules"]) else None
    vby = {x["rule"].id: x for x in vrows}
    fby = {x["rule"].id: x for x in frows}
    cset = {r.id for r in cands}
    # every rule's numbers
    recs = []
    for r in tr["rules"]:
        s, v, f = tstats[r.id], vby.get(r.id, {}), fby.get(r.id, {})
        recs.append({"rule": r.id, "indicator": r.ind, "param": ",".join(map(str, r.param)),
                     "side": "L" if r.side > 0 else "S", "exit": f"K{r.k}", "window": r.window, "regime": r.regime,
                     "universe": r.univ, "train_n": s["n"], "train_win": s.get("win"), "train_gross_r": s.get("gross_r"),
                     "train_net_r": s.get("net_r"), "train_p_day": s.get("p_day"), "train_cost_share": s.get("share"),
                     "r_2022": s.get("years", {}).get(2022), "r_2023": s.get("years", {}).get(2023),
                     "candidate": r.id in cset, "val_n": v.get("n"), "r_2024": v.get("net_r"), "val_p_day": v.get("p_day"),
                     "val_holm_all": v.get("holm_all"), "val_dsr": v.get("dsr"), "val_pass": v.get("pass"),
                     "final_n": f.get("n"), "r_2025": f.get("years", {}).get(2025), "r_2026": f.get("years", {}).get(2026),
                     "final_net_r": f.get("net_r"), "final_p_day": f.get("p_day"), "final_pass": f.get("pass")})
    pd.DataFrame(recs).to_csv(CSV, index=False)
    ok = [x for x in recs if x["train_n"]]
    top = sorted((x for x in ok if x["train_n"] >= MIN_TRAIN), key=lambda x: -x["train_net_r"])[:25]
    survivors = [x for x in frows if x["pass"]]
    L = []
    L.append("# Study engine: result\n")
    L.append(f"**Protocol:** `study_engine_protocol.md`, SHA-256 `{tr['protocol_sha']}`.")
    L.append("**Code:** `nfce_engine/tools/study.py` (tests `nfce_engine/tests/test_study.py`). "
             f"**Every rule's numbers:** `{CSV.name}`.\n")
    L.append("## Scale")
    L.append(f"- Rules tried: **{n_total}** ({sum(r.univ == 'STK' for r in tr['rules'])} on {tr['instruments'] - 2} F&O "
             f"stocks, {sum(r.univ == 'IDX' for r in tr['rules'])} on NIFTY/BANKNIFTY futures); "
             f"{len(INDICATORS)} indicators, {sum(len(i.params) for i in INDICATORS.values())} settings.")
    L.append(f"- Train trades (2022–23), summed over rules: {sum(x['train_n'] for x in ok):,}; rules with ≥ {MIN_TRAIN} trades: {len(srs)}; "
             f"train net R > 0: {sum(x['train_net_r'] > 0 for x in ok if x['train_n'] >= MIN_TRAIN)}.")
    L.append(f"- Candidates (best setting per family, train net R > 0): **{len(cands)}**; passed validation: "
             f"**{sum(x['pass'] for x in vrows)}**; passed the one-shot final: **{len(survivors)}**.\n")
    L.append("## Multiple-testing verdict")
    L.append(f"- Train, all {sp_tr['rules']} rules with trades: White reality check p = {sp_tr['rc_p']:.3f}, "
             f"Hansen SPA p = {sp_tr['spa_p']:.3f} (H0: no rule beats not trading).")
    if sp_va:
        L.append(f"- Validation, the {sp_va['rules']} candidates: reality check p = {sp_va['rc_p']:.3f}, SPA p = {sp_va['spa_p']:.3f}.")
    keep = [i for i, t in enumerate(tr["acc"]) if t[:, 0].sum() >= MIN_TRAIN]
    pb = pbo_cscv(X[:, keep])
    L.append(f"- PBO (CSCV, 16 blocks, {pb['splits']:,} splits) over the {pb['trials']} train rules with ≥ {MIN_TRAIN} trades: "
             f"**{pb['pbo']:.2f}**; the in-sample best has a mean per-day Sharpe of {pb['is_best_sr']:+.3f} in sample and "
             f"{pb['oos_sr_of_is_best']:+.3f} out of sample (negative in {pb['oos_loss_share'] * 100:.0f}% of splits).")
    L.append(f"- Deflated Sharpe: N = {n_total} trials, V[per-day Sharpe] across train rules = {var_sr:.5f}; the expected "
             f"best per-day Sharpe of {n_total} skill-less rules = {expected_max_sr(var_sr, n_total):.3f}.\n")
    L.append(f"## Top 25 rules on train (2022–23), after costs (rules with ≥ {MIN_TRAIN} trades)")
    L.append("| Rule | n | Win % | Gross R | Net R | 2022 | 2023 | p(day) | Cost/R | Candidate | 2024 (val) |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for x in top:
        L.append(f"| `{x['rule']}` | {x['train_n']:,} | {x['train_win'] * 100:.1f} | {_fmt(x['train_gross_r'])} | "
                 f"**{_fmt(x['train_net_r'])}** | {_fmt(x['r_2022'])} | {_fmt(x['r_2023'])} | {x['train_p_day']:.4f} | "
                 f"{x['train_cost_share']:.2f} | {'yes' if x['candidate'] else ''} | {_fmt(x['r_2024'])} |")
    if vrows:
        L.append("\n## Validation 2024: the candidates, ranked")
        L.append("| Rule | Train net R | n | Win % | Net R | p(day) | Holm (all rules) | DSR | Pass |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        for x in sorted(vrows, key=lambda x: -(x.get("net_r") or -9)):
            if not x["n"]:
                L.append(f"| `{x['rule'].id}` | {_fmt(tstats[x['rule'].id]['net_r'])} | 0 | | | | | | FAIL |")
                continue
            L.append(f"| `{x['rule'].id}` | {_fmt(tstats[x['rule'].id]['net_r'])} | {x['n']:,} | {x['win'] * 100:.1f} | "
                     f"**{_fmt(x['net_r'])}** | {x['p_day']:.4f} | {x['holm_all']:.3f} | {x['dsr']:.3f} | "
                     f"{'PASS' if x['pass'] else 'FAIL'} |")
    if frows:
        L.append("\n## Final 2025-01 .. 2026-10-21 (one shot)")
        L.append("| Rule | n | Win % | Net R | 2025 | 2026 | 95% day-block | p(day) | DSR | Pass |")
        L.append("|---|---|---|---|---|---|---|---|---|---|")
        for x in frows:
            L.append(f"| `{x['rule'].id}` | {x['n']:,} | {x.get('win', 0) * 100:.1f} | **{_fmt(x.get('net_r'))}** | "
                     f"{_fmt(x.get('years', {}).get(2025))} | {_fmt(x.get('years', {}).get(2026))} | "
                     f"{_fmt(x['ci'][0])}..{_fmt(x['ci'][1])} | {x.get('p_day', 1):.4f} | {x['dsr']:.3f} | "
                     f"{'PASS' if x['pass'] else 'FAIL'} |")
    elif va:
        L.append("\n## Final\nNot run: no rule passed validation, so there was nothing to test once.")
    if cc:
        L.append("\n## Cost-model check (live minute quotes; used for nothing else)")
        L.append(cost_lines(cc))
    return "\n".join(L) + "\n"


def cost_lines(cc: dict) -> str:
    if not cc.get("quotes"):
        return "No quote files found."
    L = [f"- {cc['quotes']:,} futures quotes from {', '.join(cc['dbs'])}; {cc['stocks']} stock futures.",
         f"- Stock futures quoted half-spread (per stock, median over the day): median {cc['stock_half_median'] * 1e4:.2f} bp, "
         f"75% {cc['stock_half_p75'] * 1e4:.2f} bp, 90% {cc['stock_half_p90'] * 1e4:.2f} bp; first 15 minutes "
         f"{cc['stock_half_open_median'] * 1e4:.2f} bp. **Model: {cc['model_stock_per_side'] * 1e4:.1f} bp per side** "
         f"(half-spread + slippage). Stocks whose median half-spread alone exceeds the model: {cc['stock_over_model'] * 100:.0f}%.",
         f"- One ~₹7 L lot fits inside the touch (both sides) in {cc['touch_fills_lot'] * 100:.0f}% of stock quotes."]
    for u, x in cc["index"].items():
        L.append(f"- {u} futures half-spread: median {x['half_median_pts']:.2f} pts, 90% {x['half_p90_pts']:.2f} pts; "
                 f"model {x['model_pts']:.1f} pts per side.")
    return "\n".join(L)


# ---------------------------------------------------------------- CLI
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["train", "validation", "final", "report", "costcheck"])
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--i-accept-one-shot", action="store_true")
    x = ap.parse_args()
    if x.cmd in STAGES and protocol_sha() is None:
        sys.exit(f"register the protocol first: {PROTOCOL}")
    if x.cmd == "train":
        res = run_stage(grid(), "train", x.workers)
    elif x.cmd == "validation":
        tr = _load("train")
        if tr is None or tr["protocol_sha"] != protocol_sha():
            sys.exit("train missing, or the protocol changed since train")
        if _load("validation") is not None:
            sys.exit("validation already run")
        cands = select(tr)
        print(f"{len(cands)} candidates from train")
        res = run_stage(cands, "validation", x.workers) if cands else {"stage": "validation", "rules": [], "acc": np.zeros((0, 0, 9)),
                                                                        "days": pd.DatetimeIndex([]), "protocol_sha": protocol_sha()}
    elif x.cmd == "final":
        if not x.i_accept_one_shot:
            sys.exit("the final stage is one-shot: pass --i-accept-one-shot")
        if _load("final") is not None:
            sys.exit("the final stage has already been run once")
        tr, va = _load("train"), _load("validation")
        if va is None or va["protocol_sha"] != protocol_sha():
            sys.exit("validation missing, or the protocol changed since")
        surv = [y["rule"] for y in judge_validation(va, len(tr["rules"]), train_trials(tr)[1]) if y["pass"]]
        print(f"{len(surv)} validation survivors")
        if not surv:
            sys.exit("no survivors: the final stage is not run")
        res = run_stage(surv, "final", x.workers)
    elif x.cmd == "costcheck":
        cc = cost_check(QUOTES)
        _save("costcheck", cc)
        print(cost_lines(cc))
        return
    else:
        txt = report(_load("costcheck"))           # tables only; the result file adds the reading of them
        (WORK / "result_tables.md").write_text(txt)
        print(txt)
        return
    _save(x.cmd, res)
    print(f"{x.cmd}: {len(res['rules'])} rules saved to {WORK / (x.cmd + '.pkl')}")


if __name__ == "__main__":
    main()
