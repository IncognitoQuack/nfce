"""Simple, pre-registered intraday hypotheses. Rules are fixed in code BEFORE evaluation; every variant is reported.

H1  Opening-range breakout (ORB) on 60-minute bars (09:15, 10:15, ..., 14:15, 15:15)
    Range = the 09:15-10:15 bar. Long on the first later bar (opening 10:15 .. 13:15) that CLOSES above the range
    high, short on a close below the range low. Entry at that close. One trade per day. Stop: opposite side of the
    range ("opposite") or the midpoint ("mid"). Exit at the 15:15 bar close (15:30), or at the stop.
H2  First-hour intraday momentum (after Gao, Han, Li & Zhou 2018; NOT a literal replication: 60-minute bars)
    r1 = 10:15 close / previous COMPLETE session close - 1. Trade in the direction of r1 from the 14:15 bar open to
    the 15:15 bar close. Variant "big": only when |r1| > median |r1| of the previous 60 sessions.
HA  Volatility-gated 15-minute ORB, single exit (independent audit, pre-registered hypothesis H-A)
    Range = 09:15-09:30 bar. Trade only if 0.25 x ATR14(daily, previous days) <= range <= 0.60 x ATR14 and the 09:15
    bar's volume >= 1.5 x the median 09:15-bar volume of the previous 20 sessions. Entry: first 15-minute close
    beyond the range on a bar CLOSING 09:45..11:15. Stop: opposite side of the range; skip if R < min_R
    (NIFTY 60 points as specified; BANKNIFTY 135 = 60 scaled by the index ratio, an interpretation). Exit: target
    2.0R, the stop, or the 15:15 close. One trade a day, one lot, two orders.

Missing data is handled causally (independent review): a session without its 15:15 bar is NOT dropped after the
fact; an open trade exits at the last available bar close (reason "eod_incomplete"). A previous session that was
incomplete is not used as "previous close" (that is knowable at decision time).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import costs
from .stats import _t_pvalue, block_bootstrap_mean

HA_MIN_R = {"NIFTY": 60.0, "BANKNIFTY": 135.0}


@dataclass
class SimpleTrade:
    date: pd.Timestamp
    side: int           # +1 long, -1 short
    entry: float
    exit: float
    risk: float         # entry-to-stop distance (points); for H2 the first-hour move size
    reason: str
    entry_time: pd.Timestamp | None = None
    exit_time: pd.Timestamp | None = None
    orders: int = 2

    @property
    def pnl(self) -> float:
        return self.side * (self.exit - self.entry)


def _sessions(bars: pd.DataFrame):
    b = bars.sort_index()
    ist = b.index.tz_convert("Asia/Kolkata")
    for day, d in b.groupby(ist.normalize()):
        hhmm = d.index.tz_convert("Asia/Kolkata").strftime("%H:%M")
        yield day, d.assign(hhmm=hhmm)


def orb(bars: pd.DataFrame, stop: str = "opposite") -> list[SimpleTrade]:
    out = []
    for day, d in _sessions(bars):
        first = d[d.hhmm == "09:15"]
        if first.empty:
            continue                                     # no opening bar: the range cannot be defined (known at 10:15)
        hi, lo = float(first.high.iloc[0]), float(first.low.iloc[0])
        mid = (hi + lo) / 2
        rest = d[d.index > first.index[0]]
        pos, entry, sl, entry_t = 0, 0.0, 0.0, None
        for t, r in rest.iterrows():
            if pos == 0:
                if r.hhmm <= "13:15":
                    if r.close > hi:
                        pos, entry, sl, entry_t = 1, float(r.close), (lo if stop == "opposite" else mid), t
                    elif r.close < lo:
                        pos, entry, sl, entry_t = -1, float(r.close), (hi if stop == "opposite" else mid), t
                continue
            if (pos == 1 and r.low <= sl) or (pos == -1 and r.high >= sl):
                fill = min(r.open, sl) if pos == 1 else max(r.open, sl)       # gap-through fills at the open
                out.append(SimpleTrade(day, pos, entry, float(fill), abs(entry - sl), "stop", entry_t, t))
                pos = 0
                break
            if r.hhmm == "15:15":
                out.append(SimpleTrade(day, pos, entry, float(r.close), abs(entry - sl), "eod", entry_t, t))
                pos = 0
                break
        if pos != 0:                                       # session ended without a 15:15 bar
            last_t = d.index[-1]
            out.append(SimpleTrade(day, pos, entry, float(d.close.iloc[-1]), abs(entry - sl), "eod_incomplete",
                                   entry_t, last_t))
    return out


def momentum(bars: pd.DataFrame, variant: str = "all") -> list[SimpleTrade]:
    rows = []
    prev_close, prev_complete = np.nan, False
    for day, d in _sessions(bars):
        def get(hm, col):
            m = d.hhmm == hm
            return float(d.loc[m, col].iloc[0]) if m.any() else np.nan
        after = d[d.hhmm >= "14:15"]
        exit_px = get("15:15", "close")
        exit_reason = "eod"
        if np.isnan(exit_px) and len(after) and (after.hhmm == "14:15").any():
            exit_px, exit_reason = float(after.close.iloc[-1]), "eod_incomplete"
        rows.append((day, prev_close if prev_complete else np.nan, get("09:15", "close"), get("14:15", "open"),
                     exit_px, exit_reason))
        prev_close = float(d.close.iloc[-1])
        prev_complete = (d.hhmm == "15:15").any() and (d.hhmm == "09:15").any()
    df = pd.DataFrame(rows, columns=["day", "pc", "c1", "o_entry", "c_exit", "why"]).set_index("day")
    df["r1"] = df.c1 / df.pc - 1
    df["med"] = df.r1.abs().shift(1).rolling(60, min_periods=60).median()   # past sessions only
    out = []
    for day, r in df.iterrows():
        if np.isnan(r.r1) or np.isnan(r.o_entry) or np.isnan(r.c_exit) or r.r1 == 0:
            continue
        if variant == "big" and not (r.med > 0 and abs(r.r1) > r.med):
            continue
        side = 1 if r.r1 > 0 else -1
        out.append(SimpleTrade(day, side, r.o_entry, r.c_exit, abs(r.c1 - r.pc), r.why))
    return out


def daily_atr(bars: pd.DataFrame, n: int = 14) -> pd.Series:
    """ATR14 of DAILY bars built from the intraday bars, indexed by session date, shifted so day t sees t-1."""
    ist = bars.index.tz_convert("Asia/Kolkata")
    d = bars.groupby(ist.normalize()).agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    pc = d.close.shift(1)
    tr = pd.concat([d.high - d.low, (d.high - pc).abs(), (d.low - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return atr.shift(1)


def orb15_ha(bars15: pd.DataFrame, instr: str = "NIFTY") -> list[SimpleTrade]:
    """Pre-registered H-A on 15-minute bars. See module docstring. Needs real (futures) volume."""
    if "volume" not in bars15.columns or not (bars15["volume"].fillna(0) > 0).any():
        raise ValueError("H-A needs volume for its opening-volume gate (use futures bars; spot index bars have none)")
    atr_prev = daily_atr(bars15)
    min_r = HA_MIN_R.get(instr, 60.0)
    first_vols: list[float] = []
    out = []
    for day, d in _sessions(bars15):
        first = d[d.hhmm == "09:15"]
        if first.empty:
            continue
        f = first.iloc[0]
        rng = float(f.high - f.low)
        med = float(np.median(first_vols[-20:])) if len(first_vols) >= 20 else 0.0
        vol_ok = med > 0 and f.volume >= 1.5 * med          # FIX v2: 0 >= 1.5 x 0 used to pass the gate
        first_vols.append(float(f.volume))
        a = atr_prev.get(day, np.nan)
        if not (vol_ok and np.isfinite(a) and 0.25 * a <= rng <= 0.60 * a):
            continue
        hi, lo = float(f.high), float(f.low)
        pos, entry, sl, tgt, entry_t = 0, 0.0, 0.0, 0.0, None
        for t, r in d[d.index > first.index[0]].iterrows():
            close_hhmm = (t.tz_convert("Asia/Kolkata") + pd.Timedelta(minutes=15)).strftime("%H:%M")
            if pos == 0:
                if "09:45" <= close_hhmm <= "11:15":
                    s = 1 if r.close > hi else -1 if r.close < lo else 0
                    if s:
                        stop = lo if s > 0 else hi
                        risk = abs(float(r.close) - stop)
                        if risk < min_r:
                            break                          # one decision per day: a too-small R means no trade today
                        pos, entry, sl, entry_t = s, float(r.close), stop, t
                        tgt = entry + s * 2.0 * risk
                elif close_hhmm > "11:15":
                    break
                continue
            if (pos > 0 and r.low <= sl) or (pos < 0 and r.high >= sl):
                fill = min(r.open, sl) if pos > 0 else max(r.open, sl)
                out.append(SimpleTrade(day, pos, entry, float(fill), abs(entry - sl), "stop", entry_t, t))
                pos = 0
                break
            if (pos > 0 and r.high >= tgt) or (pos < 0 and r.low <= tgt):
                out.append(SimpleTrade(day, pos, entry, float(tgt), abs(entry - sl), "target", entry_t, t))
                pos = 0
                break
            if close_hhmm >= "15:15":
                out.append(SimpleTrade(day, pos, entry, float(r.close), abs(entry - sl), "eod", entry_t, t))
                pos = 0
                break
        if pos != 0:
            out.append(SimpleTrade(day, pos, entry, float(d.close.iloc[-1]), abs(entry - sl), "eod_incomplete",
                                   entry_t, d.index[-1]))
    return out


def stats(trades: list[SimpleTrade], point_value: float, mintick: float, comm_side: float = 0.0003,
          slip_ticks: int = 4, cost_mode: str = "legacy", lot_units: int | None = None) -> dict:
    """Net results per trade.

    cost_mode "legacy"  : 0.03% of notional per side + 4 ticks per side (the Phase 6 v1 model)
              "dated"   : dated fee schedule on each trade's date (nfce.costs) + 4 ticks per side friction
              "current" : today's fee schedule applied to every trade (current-cost stress)
    """
    if not trades:
        return {"n": 0}
    gross = np.array([t.pnl for t in trades])
    if cost_mode == "legacy":
        cost = np.array([comm_side * 2 * t.entry + 2 * slip_ticks * mintick for t in trades])
    else:
        lu = lot_units or int(point_value)
        cost = np.array([costs.futures_cost_points(
            t.entry, t.exit, t.side, costs.CURRENT if cost_mode == "current" else pd.Timestamp(t.date).date(),
            lu, 1, t.orders, slip_ticks * mintick) for t in trades])
    net = gross - cost
    eq = np.cumsum(net * point_value)
    dd = float(np.max(np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]))
    sd = net.std(ddof=1) if len(net) > 1 else 0.0
    tstat = float(net.mean() / (sd / np.sqrt(len(net)))) if sd > 0 else 0.0
    weeks = [tuple(pd.Timestamp(t.date).isocalendar()[:2]) for t in trades]
    return {
        "n": len(trades), "win": float((net > 0).mean()), "gross_pts": float(gross.mean()), "cost_pts": float(cost.mean()),
        "net_pts": float(net.mean()), "sd_pts": float(sd), "t": tstat, "p": _t_pvalue(tstat, max(len(net) - 1, 1)),
        "ci_week": block_bootstrap_mean(list(net), weeks),     # trades are one a day: weeks are the coarser block
        "pf": float(net[net > 0].sum() / -net[net < 0].sum()) if (net < 0).any() else float("inf"),
        "net_inr": float(eq[-1]), "max_dd_inr": dd,
        "incomplete": int(sum(t.reason == "eod_incomplete" for t in trades)),
    }


def fmt(s: dict) -> str:
    if s["n"] == 0:
        return "n=0"
    return (f"n={s['n']:4d} win={s['win'] * 100:3.0f}% gross {s['gross_pts']:+6.1f} cost {s['cost_pts']:5.1f} "
            f"net {s['net_pts']:+6.1f} pts (t={s['t']:+.2f}) PF={s['pf']:.2f} net ₹{s['net_inr']:,.0f}/lot maxDD ₹{s['max_dd_inr']:,.0f}")
