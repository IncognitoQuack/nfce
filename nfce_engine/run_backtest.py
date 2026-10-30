"""Backtest NFCE on a CSV of bars.

CSV columns: time (bar open, e.g. 2026-10-16 09:15:00+05:30), open, high, low, close, volume[, oi]
Optional: --vix vix.csv (time, close), --hw a.csv b.csv ... (time, open, close)

  python run_backtest.py nifty_5m.csv --tf 5 --instr NIFTY
  python run_backtest.py bank_15m.csv --tf 15 --instr BANKNIFTY --ablate     # one factor off at a time
  python run_backtest.py nifty_5m.csv --tf 5 --legacy                       # v1 (Phase 2-3) trade management

Costs (v2): dated fee schedule on each trade's date and the current-cost stress, 10 lots, 4 ticks friction a side.
Lot size and tick come from the instrument (NIFTY 65 / 0.1, BANKNIFTY 30 / 0.2) unless overridden.
"""
from __future__ import annotations

import argparse

import pandas as pd

from nfce import FACTORS, Params, prepare, run
from nfce.engine import LEGACY_V1
from nfce.stats import CostModel, fmt, report

INSTR = {"NIFTY": (65, 0.1), "BANKNIFTY": (30, 0.2), "FINNIFTY": (60, 0.1), "MIDCPNIFTY": (120, 0.05), "SENSEX": (20, 0.2)}


def load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    t = pd.to_datetime(df.pop("time"))
    t = t.dt.tz_localize("Asia/Kolkata") if t.dt.tz is None else t.dt.tz_convert("Asia/Kolkata")
    return df.set_index(t)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("bars")
    ap.add_argument("--tf", type=int, required=True)
    ap.add_argument("--instr", default="NIFTY", choices=sorted(INSTR))
    ap.add_argument("--mintick", type=float, help="default: the instrument's futures tick")
    ap.add_argument("--lot", type=int, help="lot size in units (default: the instrument's current lot size)")
    ap.add_argument("--vix")
    ap.add_argument("--hw", nargs="*", default=[])
    ap.add_argument("--ablate", action="store_true")
    ap.add_argument("--legacy", action="store_true", help="v1 trade management (same-bar re-entry, no daily stop)")
    a = ap.parse_args()
    lot, tick = a.lot or INSTR[a.instr][0], a.mintick or INSTR[a.instr][1]
    params = Params(instr=a.instr, **(LEGACY_V1 if a.legacy else {}))
    pr = prepare(load(a.bars), a.tf, params, vix=load(a.vix) if a.vix else None, hw=[load(x) for x in a.hw])
    if pr.cols.get("no_volume"):
        print("WARNING: no volume in the bars: the volume factor is zero (use futures bars, not spot)")
    if pr.cols.get("htf_warning"):
        print("WARNING: chart timeframe >= the higher timeframe: the HTF factor is not a higher timeframe")
    cms = {m: CostModel(m, lot_units=lot, lots=10, friction_pts_per_side=4 * tick) for m in ("dated", "current")}
    base = run(pr, params)
    for m, cm in cms.items():
        print(f"base ({m:7s}) ", fmt(report(base, cm)))
    if a.ablate:
        for f in FACTORS:
            p = params.ablate(f)
            print(f"-{f:<12} (dated)  ", fmt(report(run(pr, p), cms["dated"])))


if __name__ == "__main__":
    main()
