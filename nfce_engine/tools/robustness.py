"""Robustness study on real 5-minute data (run tools/fetch_yahoo.py first).

  python tools/robustness.py NSEI    [--data DIR] [--seeds 10]
  python tools/robustness.py NSEBANK [--data DIR] [--seeds 10]

1. Baseline: v2 defaults (spec presets) on spot index prices; volume proxy = summed volume of the instrument's
   heavyweights (spot indices carry no volume). Costs: dated schedule, 10 lots, 4 ticks friction per side.
2. Noise (review M09): bounded, tick-rounded perturbations (nfce/robust.py). "shift k" moves every price of a
   bar by the same k-bounded number of ticks (geometry kept); "jitter k" moves O/H/L/C independently and repairs
   high/low (geometry changes; mean range change shown). Similarity to the baseline signal set: precision, recall,
   Jaccard at timing tolerance 0 and 1 bar, plus the net-R distribution (P&L sensitivity).
3. Parameters: each filter threshold x0.8 / x1.0 / x1.2.
FIX v2 (review H06): the instrument is set per index. v1 ran BANKNIFTY with Params.instr = "NIFTY", which applied
Nifty's weekly-expiry rules to Bank Nifty.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce import Params, prepare, run  # noqa: E402
from nfce.data import load_csv  # noqa: E402
from nfce.robust import jitter, mean_range_change, shift, similarity  # noqa: E402
from nfce.stats import CostModel, report  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data" / "yahoo"
SETUP = {  # index file: (instrument, lot units, futures tick, heavyweights)
    "NSEI": ("NIFTY", 65, 0.1, ["HDFCBANK", "ICICIBANK", "RELIANCE", "INFY", "BHARTIARTL"]),
    "NSEBANK": ("BANKNIFTY", 30, 0.2, ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK"]),
}
BAR = pd.Timedelta(minutes=5)


def main(index_name: str, data: Path, seeds: int) -> None:
    instr, lot, tick, hw_names = SETUP[index_name]
    load = lambda n: load_csv(data / f"{n}_5m.csv", 5)  # noqa: E731
    (idx, info), (vix, _) = load(index_name), load("INDIAVIX")
    hws = [load(s)[0] for s in hw_names]
    base = idx[["open", "high", "low", "close"]].copy()
    base["volume"] = sum(h["volume"].reindex(idx.index).fillna(0) for h in hws)
    start = idx.index.min() + pd.Timedelta(days=14)          # indicator warm-up (RVOL needs ~10 sessions)
    cm = CostModel("dated", lot_units=lot, lots=10, friction_pts_per_side=4 * tick)
    p0 = Params(instr=instr)

    def go(bars, p):
        return [t for t in run(prepare(bars, 5, p, vix=vix, hw=hws), p) if t.entry_time >= start]

    def r(tr):
        return report(tr, cm)["net_r"] if tr else float("nan")

    ref = go(base, p0)
    keys = [(t.entry_time, t.side) for t in ref]
    s = report(ref, cm)
    print(f"[{instr}] {index_name}_5m.csv sha256 {info['sha256'][:12]} {info['first'][:10]}..{info['last'][:10]} "
          f"({info['sessions']} sessions)")
    if not ref:
        print("  baseline: no trades")
        return
    print(f"  baseline v2 defaults: n={s['n']} win={s['win'] * 100:.0f}% gross {s['gross_r']:+.3f}R "
          f"net {s['net_r']:+.3f}R [day-block {s['ci_day'][0]:+.2f}, {s['ci_day'][1]:+.2f}] p={s['p']:.2f}")
    print("  perturbation        | ranges   | tol0 P/R/J        | tol1 P/R/J        | net R mean [min..max] (base "
          f"{s['net_r']:+.3f})")
    for kind, fn in (("shift", shift), ("jitter", jitter)):
        for k in (1, 5, 20):
            sims0, sims1, nets, dr = [], [], [], []
            for seed in range(seeds):
                b = fn(base, k, tick, seed)
                tr = go(b, p0)
                pk = [(t.entry_time, t.side) for t in tr]
                sims0.append(similarity(keys, pk, 0, BAR))
                sims1.append(similarity(keys, pk, 1, BAR))
                nets.append(r(tr))
                dr.append(mean_range_change(base, b))
            m = lambda xs, f: np.nanmean([x[f] for x in xs])  # noqa: E731
            nets = np.array(nets)
            print(f"  {kind:6s} ±{k:2d} ticks ({k * tick:4.1f} pt) | {np.mean(dr):+5.2f}pt | "
                  f"{m(sims0, 'precision'):.2f}/{m(sims0, 'recall'):.2f}/{m(sims0, 'jaccard'):.2f}    | "
                  f"{m(sims1, 'precision'):.2f}/{m(sims1, 'recall'):.2f}/{m(sims1, 'jaccard'):.2f}    | "
                  f"{np.nanmean(nets):+.3f} [{np.nanmin(nets):+.3f} .. {np.nanmax(nets):+.3f}]")
    print("  parameters (n, net R dated):")
    for name in ("body_atr", "max_risk_atr", "room_r", "chop_max", "min_risk_atr", "sl_buf_atr"):
        cells = []
        for mult in (0.8, 1.0, 1.2):
            tr = go(base, replace(p0, **{name: getattr(p0, name) * mult}))
            cells.append(f"x{mult}: n{len(tr)} {r(tr):+.2f}R")
        print(f"   {name:12s} " + " | ".join(cells))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("index", choices=sorted(SETUP))
    ap.add_argument("--data", type=Path, default=DATA)
    ap.add_argument("--seeds", type=int, default=10)
    a = ap.parse_args()
    main(a.index, a.data, a.seeds)
