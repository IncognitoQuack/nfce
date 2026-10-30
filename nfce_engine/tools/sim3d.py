"""Paper simulation over the last N sessions, following ../evidence/sim3d_protocol.md (fixed before any result).

  python tools/sim3d.py all_5m_60d.pkl [--sessions 3] [--out result.json]

Input: a pickle of yfinance 5m bars (group_by="ticker") for the 50 Nifty stocks (.NS), ^NSEI, ^NSEBANK, ^INDIAVIX.
Earlier sessions are warm-up only; only trades entered in the last N sessions count.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce import Params, prepare, run  # noqa: E402
from nfce.stats import CostModel, block_bootstrap_mean  # noqa: E402

TZ = "Asia/Kolkata"
NIFTY_HW = ["HDFCBANK", "ICICIBANK", "RELIANCE", "INFY", "BHARTIARTL"]
BANK_HW = ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK"]
EXTRA_EXPIRY = frozenset({dt.date(2026, 10, 19)})
LEAN = (20, 0, 0, 0, 10, 0, 0, 0, 0)          # volume + HTF only (FACTORS order)
VARIANTS = {
    "V0 base": {},
    "V1 single exit 2R": dict(r1m=2.0, r2m=2.0, r3m=2.0),
    "V2 lean volume+HTF": dict(weights=LEAN),
    "V3 volume hard filter": dict(req_vol=True),
    "V4 no entry after 13:30": dict(last_entry=1330),
}


def frames(d: pd.DataFrame) -> dict[str, pd.DataFrame]:
    out = {}
    for t in sorted({c[0] for c in d.columns}):
        x = d[t].dropna(subset=["Close"]).copy()
        x.index = x.index.tz_convert(TZ)
        x.columns = [c.lower() for c in x.columns]
        out[t.replace(".NS", "")] = x[["open", "high", "low", "close", "volume"]]
    return out


def r15(x: pd.DataFrame) -> pd.DataFrame:
    g = x.groupby(pd.Grouper(freq="15min", origin=pd.Timestamp("2026-01-01 09:15", tz=TZ)))
    o = g.agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])
    n = x.groupby(pd.Grouper(freq="15min", origin=pd.Timestamp("2026-01-01 09:15", tz=TZ))).size()
    return o[n.reindex(o.index).fillna(0) == 3]                     # complete 15m bars only


def universe(f: dict[str, pd.DataFrame]):
    """(name, instr, bars, heavyweight names, lot units, tick)."""
    items = []
    for name, src, hw, lot, tick in [("NIFTY", "^NSEI", NIFTY_HW, 65 * 10, 0.1), ("BANKNIFTY", "^NSEBANK", BANK_HW, 30 * 10, 0.2)]:
        b = f[src][["open", "high", "low", "close"]].copy()
        b["volume"] = sum(f[h]["volume"].reindex(b.index).fillna(0) for h in hw)     # spot indices: proxy volume
        items.append((name, name, b, hw, lot, tick))
    for s in sorted(k for k in f if not k.startswith("^")):
        b = f[s]
        units = max(1, round(700000 / float(b.close.iloc[0])))   # FIX (M08): sized at the FIRST price, never the future
        items.append((s, "STOCK", b, NIFTY_HW, units, 0.05))
    return items


def simulate(f, days: list, variant: dict) -> list[dict]:
    vix5 = f["^INDIAVIX"][["open", "high", "low", "close"]]
    rows = []
    for name, instr, b5, hw_names, units, tick in universe(f):
        base = Params(instr=instr, extra_expiry_dates=EXTRA_EXPIRY if instr == "NIFTY" else frozenset())
        p = replace(base, **variant)
        cm = CostModel("dated", lot_units=units, lots=1, friction_pts_per_side=4 * tick)
        for tf, b, vix, hw in [(5, b5, vix5, [f[h] for h in hw_names]),
                               (15, r15(b5), r15(vix5.assign(volume=0)), [r15(f[h]) for h in hw_names])]:
            pr = prepare(b, tf, p, vix=vix, hw=hw)
            for t in run(pr, p):
                d = t.entry_time.tz_convert(TZ).date()
                if d not in days:
                    continue
                net = t.pnl - cm.points(t)
                rows.append({"sym": name, "tf": tf, "day": str(d), "side": t.side, "entry_time": str(t.entry_time),
                             "entry": t.entry, "R": t.R, "exit": t.exit, "gross_r": t.pnl / t.R, "net_r": net / t.R,
                             "net_inr": net * units, "score": float(t.score)})
    return rows


def summary(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0}
    r = np.array([x["net_r"] for x in rows])
    lo, hi = block_bootstrap_mean(list(r), [x["day"] + x["sym"][:0] for x in rows])
    ex = pd.Series([x["exit"] for x in rows]).value_counts().to_dict()
    best = max(rows, key=lambda x: x["net_r"])
    worst = min(rows, key=lambda x: x["net_r"])
    return {"n": len(rows), "win": float((r > 0).mean()), "gross_r": float(np.mean([x["gross_r"] for x in rows])),
            "net_r": float(r.mean()), "ci_day": [lo, hi], "net_inr": float(sum(x["net_inr"] for x in rows)),
            "exits": {k: int(v) for k, v in ex.items()},
            "best": f"{best['sym']} {best['tf']}m {best['side']} {best['net_r']:+.2f}R",
            "worst": f"{worst['sym']} {worst['tf']}m {worst['side']} {worst['net_r']:+.2f}R"}


def main(pkl: Path, n_sessions: int, out: Path | None) -> None:
    d = pd.read_pickle(pkl)
    f = frames(d)
    sessions = sorted(set(f["^NSEI"].index.normalize().date))
    days = sessions[-n_sessions:]
    ins, oos = days[:-1], days[-1:]
    res = {"sessions": [str(x) for x in days], "variants": {}}
    for name, v in VARIANTS.items():
        rows = simulate(f, days, v)
        res["variants"][name] = {"all": summary(rows),
                                 "in_sample": summary([x for x in rows if x["day"] in map(str, ins)]),
                                 "out_of_sample": summary([x for x in rows if x["day"] in map(str, oos)]),
                                 "by_day": {str(dd): summary([x for x in rows if x["day"] == str(dd)]) for dd in days},
                                 "trades": rows if name == "V0 base" else None}
    v0 = res["variants"]["V0 base"]
    cands = [(k, v) for k, v in res["variants"].items() if k != "V0 base" and v["in_sample"].get("n", 0) >= 10]
    best = max(cands, key=lambda kv: kv[1]["in_sample"]["net_r"]) if cands else None
    verdict = "no candidate with >= 10 in-sample trades"
    if best:
        k, v = best
        beats_is = v["in_sample"]["net_r"] > v0["in_sample"].get("net_r", -math.inf)
        beats_oos = v["out_of_sample"].get("n", 0) > 0 and v["out_of_sample"]["net_r"] > v0["out_of_sample"].get("net_r", -math.inf)
        verdict = (f"{k}: in-sample {'beats' if beats_is else 'does not beat'} V0; out-of-sample "
                   f"{'beats' if beats_oos else 'does not beat'} V0 -> {'SURVIVES (candidate for registration)' if beats_is and beats_oos else 'NOT adopted'}")
    res["selection"] = verdict
    text = json.dumps(res, indent=1, default=str)
    if out:
        out.write_text(text)
    for k, v in res["variants"].items():
        a, i, o = v["all"], v["in_sample"], v["out_of_sample"]
        fmt = lambda s: f"n={s.get('n', 0):3d} net {s.get('net_r', float('nan')):+.3f}R" if s.get("n") else "n=  0"  # noqa: E731
        print(f"{k:24s} ALL {fmt(a)} win {a.get('win', 0) * 100:3.0f}% gross {a.get('gross_r', float('nan')):+.3f}R "
              f"CI {['%+.2f' % x for x in a.get('ci_day', [])]} | IS {fmt(i)} | OOS {fmt(o)} | exits {a.get('exits')}")
    print("selection:", verdict)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("pkl", type=Path)
    ap.add_argument("--sessions", type=int, default=3)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    main(a.pkl, a.sessions, a.out)
