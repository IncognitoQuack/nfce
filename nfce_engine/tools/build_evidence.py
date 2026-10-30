"""Build the evidence table the bridge attaches to every signal (nfce_bridge/bridge/evidence_table.json).

  python tools/build_evidence.py all_5m_60d.pkl split.json out.json

Source: the base system on the 28 HOLD-OUT sessions only (out-of-sample, ../evidence/holdout_protocol.md), plus the
TradingView v2 futures runs (../evidence/tv_v2_base_trades.txt). Buckets are the factors that the diagnosis showed matter:
  window  : "morning" (signal bar closes <= 11:15 IST) or "later"
  cost    : share of the risk (R) eaten by fees + friction: "low" < 15%, "mid" 15-30%, "high" > 30%
  kind    : "index" or "stock"
Each cell: n, win rate (net), mean gross R, mean net R and a day-block 95% interval of net R. Cells with fewer than 30
trades are marked thin; the bridge then falls back to the pooled cell (window x cost) and says so.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce.stats import block_bootstrap_mean  # noqa: E402
from tools.sim3d import VARIANTS, frames, simulate  # noqa: E402
from tools.tv_evidence import parse  # noqa: E402
from nfce.stats import CostModel  # noqa: E402

MIN_N = 30


def cost_bucket(share: float) -> str:
    return "low" if share < 0.15 else "mid" if share <= 0.30 else "high"


def cell(df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0:
        return {"n": 0}
    lo, hi = block_bootstrap_mean(list(df.net_r), list(df.day)) if df.day.nunique() > 1 else (float("nan"), float("nan"))
    ci = None if (np.isnan(lo) or np.isnan(hi)) else [round(float(lo), 3), round(float(hi), 3)]   # valid JSON: no NaN
    return {"n": n, "win": round(float((df.net_r > 0).mean()), 3), "gross_r": round(float(df.gross_r.mean()), 3),
            "net_r": round(float(df.net_r.mean()), 3), "ci": ci,
            "days": int(df.day.nunique()), "thin": n < MIN_N}


def index_cells(tv: Path) -> dict:
    """FIX (review round 3, M11): evidence for INDEX signals from index futures only, never from stock trades.
    TradingView v2 futures runs (NIFTY/BANKNIFTY, 5m/15m), CURRENT (2026) costs, 10 lots, 4 ticks per side;
    split by entry window like the bridge's cards."""
    rows = []
    for meta, trades in parse(str(tv)):
        cm = CostModel("current", lot_units=int(meta["pv"]), lots=10, friction_pts_per_side=4 * float(meta["mintick"]))
        for x in trades:
            t = x.entry_time
            rows.append({"day": str(t.date()), "gross_r": x.pnl / x.R, "net_r": (x.pnl - cm.points(x)) / x.R,
                         "window": "morning" if t.hour * 60 + t.minute <= 11 * 60 + 15 else "later"})
    df = pd.DataFrame(rows)
    out = {"tv|all": cell(df)}
    for w, g in df.groupby("window"):
        out[f"tv|{w}"] = cell(g)
    return out


def add_index_cells(table_path: Path, tv: Path) -> None:
    t = json.loads(table_path.read_text())
    t["index_cells"] = index_cells(tv)
    t["index_source"] = ("TradingView v2 runs on NIFTY1!/BANKNIFTY1! futures (Dec 2025 - Oct 2026), current costs; "
                         "the hold-out simulation's index trades are too few (24) to stand alone")
    table_path.write_text(json.dumps(t, indent=1))
    for k, v in t["index_cells"].items():
        print(k, v)


def main(pkl: Path, split: Path, out: Path, tv: Path) -> None:
    f = frames(pd.read_pickle(pkl))
    hold = {pd.Timestamp(d).date() for d in json.loads(split.read_text())["holdout"]}
    df = pd.DataFrame(simulate(f, hold, VARIANTS["V0 base"]))
    t = pd.to_datetime(df.entry_time).dt.tz_convert("Asia/Kolkata")
    df["window"] = np.where(t.dt.hour * 60 + t.dt.minute <= 11 * 60 + 15, "morning", "later")
    df["cost_share"] = (df.gross_r - df.net_r).clip(lower=0)
    df["cost"] = df.cost_share.map(cost_bucket)
    df["kind"] = np.where(df.sym.isin(["NIFTY", "BANKNIFTY"]), "index", "stock")
    cells = {}
    for (w, c, k), g in df.groupby(["window", "cost", "kind"]):
        cells[f"{w}|{c}|{k}"] = cell(g)
    for (w, c), g in df.groupby(["window", "cost"]):
        cells[f"{w}|{c}|all"] = cell(g)
    for w, g in df.groupby("window"):
        cells[f"{w}|all|all"] = cell(g)
    cells["all|all|all"] = cell(df)
    tv_rows = []
    for meta, trades in parse(str(tv)):
        cm = CostModel("dated", lot_units=int(meta["pv"]), lots=10, friction_pts_per_side=4 * float(meta["mintick"]))
        tv_rows += [{"day": str(x.entry_time.date()), "gross_r": x.pnl / x.R, "net_r": (x.pnl - cm.points(x)) / x.R}
                    for x in trades]
    table = {
        "built_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "base NFCE rules on 28 hold-out sessions (14 Aug - 14 Oct 2026), 50 Nifty stocks + NIFTY/BANKNIFTY spot, "
                  "5m+15m, dated costs + 4 ticks per side; plus TradingView v2 futures runs",
        "sessions": sorted(str(d) for d in hold), "min_n": MIN_N, "cells": cells,
        "tradingview_futures": cell(pd.DataFrame(tv_rows)),
        "validated_classes": [],   # filled ONLY when a registered experiment (REGISTRY.md) PASSES
    }
    table["index_cells"] = index_cells(tv)
    out.write_text(json.dumps(table, indent=1))
    for k, v in sorted(cells.items()):
        print(f"{k:24s} {v}")
    print("tradingview", table["tradingview_futures"])


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--index-only":          # python tools/build_evidence.py --index-only TABLE.json [TV.txt]
        add_index_cells(Path(a[1]), Path(a[2]) if len(a) > 2 else Path(__file__).resolve().parents[2] / "evidence" / "tv_v2_base_trades.txt")
        sys.exit(0)
    main(Path(a[0]), Path(a[1]), Path(a[2]),
         Path(a[3]) if len(a) > 3 else Path(__file__).resolve().parents[2] / "evidence" / "tv_v2_base_trades.txt")
