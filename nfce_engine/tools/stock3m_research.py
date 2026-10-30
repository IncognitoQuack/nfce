"""3-minute NFCE on F&O stocks with a futures cost gate (../evidence/stock3m_protocol.md).

  python tools/stock3m_research.py HIST3M_DIR --stage train|validation|final [--i-accept-one-shot] [--out res.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce import Params, costs, prepare, run  # noqa: E402
from nfce.research import _days  # noqa: E402
from nfce.research2 import _walk  # noqa: E402
from tools.scanner_research import stats  # noqa: E402

TF = 3
HW = ["HDFCBANK", "ICICIBANK", "RELIANCE", "INFY", "BHARTIARTL"]
SPLITS = {"train": (date(2022, 1, 1), date(2024, 12, 31)), "validation": (date(2025, 1, 1), date(2025, 12, 31)),
          "final": (date(2026, 1, 1), date(2026, 10, 20))}
GATES = {"V0": None, "V1": 0.20, "V2": 0.10}
EARLY_GATES = {"E0": None, "E1": 0.20}
NOTIONAL, FRICTION = 700_000, 0.0002
EOD = 15 * 60 + 12                                   # the 3m bar closing 15:15


def load(folder: Path, sym: str) -> pd.DataFrame:
    d = pd.read_pickle(folder / f"{sym}_3m.pkl")
    d.index = pd.DatetimeIndex(d.index).tz_convert("Asia/Kolkata")
    return d


def trades(folder: Path, early: bool = False, mults: tuple = (1,), walkers: dict | None = None):
    """early=True: ../evidence/early3m_protocol.md (skip_open 0, entries on bars closing <= 09:30 only).
    mults: stop and target at k x the signal's R (../evidence/wide_stop_protocol.md); (1,) = the original exits and a
    plain list; several values return {k: rows} from ONE engine run.
    walkers: {name: fn(d, j0, side, entry, R0) -> (exit price, reason, risk)} adds exit rules to the same run
    (../evidence/profit_lock_protocol.md); their rows come back under their names."""
    vix = load(folder, "INDIAVIX")[["close"]]
    hw = {s: load(folder, s)[["open", "close"]] for s in HW}
    out = {k: [] for k in mults} | {n: [] for n in (walkers or {})}
    p = Params(instr="STOCK", skip_open=0) if early else Params(instr="STOCK")
    for f in sorted(folder.glob("*_3m.pkl")):
        sym = f.stem[:-3]
        if sym == "INDIAVIX":
            continue
        b = load(folder, sym)
        tr = run(prepare(b, TF, p, vix=vix.reindex(b.index).ffill().dropna(),
                         hw=[h.reindex(b.index).ffill().dropna() for h in hw.values()]), p)
        days = {day: d for day, d in _days(b)}
        for t in tr:
            if early and t.entry_time.hour * 60 + t.entry_time.minute > 9 * 60 + 30:
                continue
            day = t.entry_time.normalize()
            d = days.get(day)
            if d is None:
                continue
            nxt = np.flatnonzero(d.index >= t.entry_time)          # the first bar after the signal bar
            if not len(nxt):
                continue
            side = 1 if t.side == "L" else -1
            units = max(1, round(NOTIONAL / t.entry))
            for k in mults:
                R = k * t.R
                stop, tgt = t.entry - side * R, t.entry + side * R
                px, why, jx = _walk(d, int(nxt[0]), side, stop, tgt, EOD)
                c = costs.futures_cost_points(t.entry, px, side, costs.CURRENT, units, 1, 2, FRICTION * t.entry)
                gross = side * (px - t.entry)
                out[k].append({"day": day.date(), "time": t.entry_time, "exit_time": d.index[jx], "sym": sym,
                               "side": side, "entry": t.entry, "R": R,
                               "share": c / R, "gross_r": gross / R, "net_r": (gross - c) / R,
                               "net_inr": (gross - c) * units, "reason": why})
            for name, fn in (walkers or {}).items():
                px, why, R = fn(d, int(nxt[0]), side, t.entry, t.R)
                c = costs.futures_cost_points(t.entry, px, side, costs.CURRENT, units, 1, 2, FRICTION * t.entry)
                gross = side * (px - t.entry)
                out[name].append({"day": day.date(), "time": t.entry_time, "sym": sym, "side": side, "entry": t.entry,
                                  "R": R, "share": c / R, "gross_r": gross / R, "net_r": (gross - c) / R,
                                  "net_inr": (gross - c) * units, "reason": why})
    return out[1] if tuple(mults) == (1,) and not walkers else out


def main(folder: Path, stage: str, out: Path | None, one_shot: bool, early: bool = False) -> None:
    if stage == "final" and not one_shot:
        sys.exit("final stage is one-shot: pass --i-accept-one-shot")
    a, b = SPLITS[stage]
    rows = [r for r in trades(folder, early) if a <= r["day"] <= b]
    res = {}
    for name, gate in (EARLY_GATES if early else GATES).items():
        sel = [r for r in rows if gate is None or r["share"] <= gate]
        s = stats(sel)
        res[name] = s
        if s["n"]:
            print(f"{name} (cost share {'any' if gate is None else '<= ' + str(int(gate * 100)) + '%'}): n={s['n']} days {s['days']} "
                  f"win {s['win'] * 100:.1f}% gross {s['gross_r']:+.3f} net {s['net_r']:+.3f}R p(day) {s['p_day']:.3f} "
                  f"CI {s['ci'][0]:+.3f}..{s['ci'][1]:+.3f} PF {s['pf']:.2f} Rs {s['net_inr']:+,.0f}", flush=True)
        else:
            print(f"{name}: n=0", flush=True)
    sh = np.array([r["share"] for r in rows]) if rows else np.array([0.0])
    print(f"cost share of risk: median {np.median(sh):.0%}, 10% {np.quantile(sh, .1):.0%}, 90% {np.quantile(sh, .9):.0%}")
    if out:
        out.write_text(json.dumps({"stage": stage, "results": res}, indent=1, default=str))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--stage", choices=list(SPLITS), required=True)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--i-accept-one-shot", action="store_true")
    ap.add_argument("--early", action="store_true", help="early3m_protocol.md instead of stock3m_protocol.md")
    x = ap.parse_args()
    main(x.folder, x.stage, x.out, x.i_accept_one_shot, x.early)
