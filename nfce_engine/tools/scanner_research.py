"""F&O stock scanner rules (../evidence/scanner_protocol.md): gainer continuation, volume surge, reversal.

  python tools/scanner_research.py DATA_DIR --stage train
  python tools/scanner_research.py DATA_DIR --stage validation --configs "G1 10:15" ...
  python tools/scanner_research.py DATA_DIR --stage final --configs ... --i-accept-one-shot
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce import costs  # noqa: E402
from nfce.research import _days  # noqa: E402
from nfce.research2 import daily  # noqa: E402
from nfce.stats import block_bootstrap_mean  # noqa: E402
from tools.research_run import SPLITS, load  # noqa: E402

TIMES = {"10:15": 10 * 60 + 15, "11:15": 11 * 60 + 15, "13:15": 13 * 60 + 15}
RULES = ("G1", "G2", "G3")
TOP = 5
RVOL_MIN = 1.5
NOTIONAL = 700_000
FRICTION = 0.0002
EOD_START = 15 * 60 + 10                     # the bar closing at 15:15
SKIP = {"NIFTY", "BANKNIFTY", "INDIAVIX"}


def ladder(d: pd.DataFrame, side: int, entry: float, R: float) -> tuple[float, float, int, str]:
    """Walk from the entry bar (entry at its open). Returns (pnl per unit, avg exit, orders, reason)."""
    o, h, l, c, m = (d[k].to_numpy() for k in ("open", "high", "low", "close", "hm"))
    stop = entry - side * R
    tg = [entry + side * k * R for k in (1, 2, 3)]
    rem, pnl, exv, orders, hit = 1.0, 0.0, 0.0, 1, 0
    for j in range(len(d)):
        if (side > 0 and l[j] <= stop) or (side < 0 and h[j] >= stop):
            px = stop if j == 0 else (min(o[j], stop) if side > 0 else max(o[j], stop))
            pnl += rem * side * (px - entry); exv += rem * px
            return pnl, exv, orders + 1, "stop" if hit == 0 else "be_stop"
        moved = False
        while hit < 3 and ((side > 0 and h[j] >= tg[hit]) or (side < 0 and l[j] <= tg[hit])):
            part = rem if hit == 2 else 1 / 3
            pnl += part * side * (tg[hit] - entry); exv += part * tg[hit]; rem -= part; orders += 1
            hit += 1
            stop, moved = entry if hit == 1 else tg[hit - 2], True
            if rem <= 1e-9:
                return pnl, exv, orders, "T3"
        if moved and ((side > 0 and c[j] <= stop) or (side < 0 and c[j] >= stop)):
            pnl += rem * side * (stop - entry); exv += rem * stop          # the close proves the moved stop was hit
            return pnl, exv, orders + 1, "be_stop"
        if m[j] >= EOD_START:
            pnl += rem * side * (c[j] - entry); exv += rem * c[j]
            return pnl, exv, orders + 1, "eod"
    pnl += rem * side * (c[-1] - entry); exv += rem * c[-1]
    return pnl, exv, orders + 1, "eod_incomplete"


def panel(data: Path) -> tuple[pd.DataFrame, dict]:
    """Per stock and day: chg, rvol and the bars, at each decision time."""
    rows, bars = [], {}
    for p in sorted(data.glob("*_5m.pkl")):
        sym = p.stem[:-3]
        if sym in SKIP:
            continue
        b = load(data, sym)
        dd = daily(b)
        prev_close = dd.close.shift(1)
        days = list(_days(b))
        cum = {}
        for day, d in days:
            v = d.volume.fillna(0).to_numpy()
            cum[day] = pd.Series(np.cumsum(v), index=d.hm.to_numpy())
        cv = pd.DataFrame(cum).T.sort_index()
        avg10 = cv.rolling(10, min_periods=10).mean().shift(1)
        for day, d in days:
            bars[(sym, day)] = d
            pc, atr = prev_close.get(day, np.nan), dd.atr_prev.get(day, np.nan)
            if not (np.isfinite(pc) and np.isfinite(atr)):
                continue
            for name, t in TIMES.items():
                k = d.hm.to_numpy() == t - 5
                if not k.any():
                    continue
                close_t = float(d.close.to_numpy()[k][0])
                a = avg10.loc[day].get(t - 5, np.nan) if day in avg10.index else np.nan
                rows.append({"day": day, "sym": sym, "time": name, "chg": close_t / pc - 1, "open": float(d.open.iloc[0]),
                             "close_t": close_t, "rvol": float(cv.loc[day, t - 5] / a) if np.isfinite(a) and a > 0 else np.nan,
                             "atr": float(atr)})
    return pd.DataFrame(rows), bars


def picks(pn: pd.DataFrame, rule: str, time: str) -> list[tuple]:
    out = []
    for day, g in pn[pn.time == time].groupby("day"):
        if rule in ("G1", "G3"):
            up = g[g.chg > 0].nlargest(TOP, "chg")
            dn = g[g.chg < 0].nsmallest(TOP, "chg")
            s_up, s_dn = (1, -1) if rule == "G1" else (-1, 1)
            out += [(day, r.sym, s_up, r.atr) for r in up.itertuples()] + [(day, r.sym, s_dn, r.atr) for r in dn.itertuples()]
        else:
            v = g[g.rvol >= RVOL_MIN].nlargest(TOP, "rvol")
            out += [(day, r.sym, 1 if r.close_t > r.open else -1, r.atr) for r in v.itertuples() if r.close_t != r.open]
    return out


def trades(pn: pd.DataFrame, bars: dict, cfg: str) -> list[dict]:
    rule, time = cfg.split()
    t = TIMES[time]
    out = []
    for day, sym, side, atr in picks(pn, rule, time):
        d = bars[(sym, day)]
        d = d[d.hm >= t]
        if d.empty:
            continue
        entry, R = float(d.open.iloc[0]), 0.5 * atr
        if not R > 0:
            continue
        pnl, exv, orders, why = ladder(d, side, entry, R)
        units = max(1, round(NOTIONAL / entry))
        cost = costs.futures_cost_points(entry, exv, side, costs.CURRENT, units, 1, orders, FRICTION * entry)
        out.append({"day": day.date(), "sym": sym, "side": side, "entry": entry, "R": R, "gross_r": pnl / R,
                    "net_r": (pnl - cost) / R, "net_inr": (pnl - cost) * units, "reason": why})
    return out


def stats(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0}
    r = [x["net_r"] for x in rows]
    g: dict = {}
    for x in rows:
        g.setdefault(x["day"], []).append(x["net_r"])
    dm = [statistics.fmean(v) for v in g.values()]
    t = statistics.fmean(dm) / (statistics.stdev(dm) / math.sqrt(len(dm))) if len(dm) > 1 and statistics.stdev(dm) > 0 else 0.0
    try:
        from scipy.stats import t as student
        p = float(student.sf(t, len(dm) - 1))
    except ImportError:
        p = 0.5 * math.erfc(t / math.sqrt(2))
    lo, hi = block_bootstrap_mean(r, [x["day"] for x in rows])
    w = sum(x["net_inr"] for x in rows if x["net_inr"] > 0)
    ls = -sum(x["net_inr"] for x in rows if x["net_inr"] < 0)
    return {"n": len(rows), "days": len(dm), "win": sum(v > 0 for v in r) / len(r),
            "gross_r": statistics.fmean(x["gross_r"] for x in rows), "net_r": statistics.fmean(r),
            "t_day": t, "p_day": p, "ci": [lo, hi], "pf": w / ls if ls > 0 else math.inf,
            "net_inr": sum(x["net_inr"] for x in rows)}


def main(data: Path, stage: str, cfgs: list[str] | None, out: Path | None, one_shot: bool) -> None:
    if stage == "final" and not one_shot:
        sys.exit("final stage is one-shot: pass --i-accept-one-shot")
    pn, bars = panel(data)
    a, b = SPLITS[stage]
    res = {}
    for cfg in cfgs or [f"{r} {t}" for r in RULES for t in TIMES]:
        rows = [x for x in trades(pn, bars, cfg) if a <= x["day"] <= b]
        s = stats(rows)
        res[cfg] = s
        if s["n"]:
            print(f"{cfg:10s} n={s['n']:5d} days {s['days']:4d} win {s['win'] * 100:4.1f}% gross {s['gross_r']:+.3f} "
                  f"net {s['net_r']:+.3f}R p(day) {s['p_day']:.3f} CI {s['ci'][0]:+.3f}..{s['ci'][1]:+.3f} "
                  f"PF {s['pf']:.2f} Rs {s['net_inr']:+,.0f}", flush=True)
        else:
            print(f"{cfg:10s} n=0", flush=True)
    if out:
        out.write_text(json.dumps({"stage": stage, "results": res}, indent=1, default=str))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("--stage", choices=list(SPLITS), required=True)
    ap.add_argument("--configs", nargs="*")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--i-accept-one-shot", action="store_true")
    x = ap.parse_args()
    main(x.data, x.stage, x.configs, x.out, x.i_accept_one_shot)
