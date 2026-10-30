"""15-minute NFCE on F&O stocks (../evidence/stock15m_protocol.md): the 3m study with one change, the timeframe.

  python tools/stock15m_research.py HIST3M_DIR --stage train|validation|final [--i-accept-one-shot] [--out res.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce import Params, costs, prepare, run  # noqa: E402
from nfce.research import _days  # noqa: E402
from nfce.research2 import _walk  # noqa: E402
from tools.scanner_research import stats  # noqa: E402
from tools.stock3m_research import FRICTION, HW, NOTIONAL, SPLITS, load  # noqa: E402

TF = 15
GATES = {"F0": None, "F1": 0.20}
EOD = 15 * 60                                        # the 15m bar closing 15:15
SPLITS = dict(SPLITS, final=(SPLITS["final"][0], pd.Timestamp("2026-10-19").date()))


def to15(d: pd.DataFrame) -> pd.DataFrame:
    """Complete 15m bars (five 3m bars) anchored at 09:15."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in d:
        agg["volume"] = "sum"
    g = d.resample("15min", label="left", closed="left")
    out = g.agg(agg)
    out = out[g["close"].count() == 5]
    return out.dropna(subset=["close"])


def trades(folder: Path) -> list[dict]:
    vix = to15(load(folder, "INDIAVIX"))[["close"]]
    hw = {s: to15(load(folder, s))[["open", "close"]] for s in HW}
    p = Params(instr="STOCK")
    out = []
    for f in sorted(folder.glob("*_3m.pkl")):
        sym = f.stem[:-3]
        if sym == "INDIAVIX":
            continue
        b = to15(load(folder, sym))
        tr = run(prepare(b, TF, p, vix=vix.reindex(b.index).ffill().dropna(),
                         hw=[h.reindex(b.index).ffill().dropna() for h in hw.values()]), p)
        days = {day: d for day, d in _days(b)}
        for t in tr:
            day = t.entry_time.normalize()
            d = days.get(day)
            if d is None:
                continue
            nxt = np.flatnonzero(d.index >= t.entry_time)
            if not len(nxt):
                continue
            side = 1 if t.side == "L" else -1
            px, why, _ = _walk(d, int(nxt[0]), side, t.entry - side * t.R, t.entry + side * t.R, EOD)
            units = max(1, round(NOTIONAL / t.entry))
            c = costs.futures_cost_points(t.entry, px, side, costs.CURRENT, units, 1, 2, FRICTION * t.entry)
            gross = side * (px - t.entry)
            out.append({"day": day.date(), "sym": sym, "side": side, "entry": t.entry, "R": t.R, "share": c / t.R,
                        "gross_r": gross / t.R, "net_r": (gross - c) / t.R, "net_inr": (gross - c) * units, "reason": why})
    return out


def main(folder: Path, stage: str, out: Path | None, one_shot: bool) -> None:
    if stage == "final" and not one_shot:
        sys.exit("final stage is one-shot: pass --i-accept-one-shot")
    a, b = SPLITS[stage]
    rows = [r for r in trades(folder) if a <= r["day"] <= b]
    res = {}
    for name, gate in GATES.items():
        sel = [r for r in rows if gate is None or r["share"] <= gate]
        s = stats(sel)
        res[name] = s
        if s["n"]:
            print(f"{name} (cost share {'any' if gate is None else '<= ' + str(int(gate * 100)) + '%'}): n={s['n']} "
                  f"days {s['days']} win {s['win'] * 100:.1f}% gross {s['gross_r']:+.3f} net {s['net_r']:+.3f}R "
                  f"p(day) {s['p_day']:.3f} CI {s['ci'][0]:+.3f}..{s['ci'][1]:+.3f} PF {s['pf']:.2f} "
                  f"Rs {s['net_inr']:+,.0f}", flush=True)
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
    x = ap.parse_args()
    main(x.folder, x.stage, x.out, x.i_accept_one_shot)
