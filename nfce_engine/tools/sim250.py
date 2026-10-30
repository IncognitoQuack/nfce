"""Random-day paper simulation (../evidence/sim250_protocol.md): random session order (seeded), sessions added until
the BASE system has >= target trades, then V0 and V2 reported on exactly those sessions.

  python tools/sim250.py all_5m_60d.pkl [--seed 20261019] [--target 250] [--out result.json]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.sim3d import VARIANTS, frames, simulate, summary  # noqa: E402


def profit_factor(rows):
    w = sum(x["net_r"] for x in rows if x["net_r"] > 0)
    lo = -sum(x["net_r"] for x in rows if x["net_r"] < 0)
    return w / lo if lo > 0 else float("inf")


def main(pkl: Path, seed: int, target: int, out: Path | None) -> None:
    f = frames(pd.read_pickle(pkl))
    sess = sorted(set(f["^NSEI"].index.normalize().date))
    pool = [s for s in sess[15:] if s not in sess[-3:]]
    order = random.Random(seed).sample(pool, len(pool))
    base_rows = simulate(f, set(pool), VARIANTS["V0 base"])
    per_day = pd.Series([r["day"] for r in base_rows]).value_counts().to_dict()
    chosen, n = [], 0
    for d in order:                                        # stopping rule: trade COUNT only, never P&L
        chosen.append(d)
        n += per_day.get(str(d), 0)
        if n >= target:
            break
    keep = {str(d) for d in chosen}
    res = {"seed": seed, "sessions": sorted(keep), "variants": {}}
    for name in ("V0 base", "V2 lean volume+HTF"):
        rows = base_rows if name == "V0 base" else simulate(f, set(chosen), VARIANTS[name])
        rows = [r for r in rows if r["day"] in keep]
        s = summary(rows)
        s["pf"] = profit_factor(rows)
        s["by_day"] = {d: round(float(np.mean([r["net_r"] for r in rows if r["day"] == d])), 3)
                       for d in sorted(keep) if any(r["day"] == d for r in rows)}
        s["positive_days"] = sum(v > 0 for v in s["by_day"].values())
        s["index_trades"] = sum(r["sym"] in ("NIFTY", "BANKNIFTY") for r in rows)
        res["variants"][name] = s
        print(f"{name:22s} n={s['n']} win={s['win'] * 100:.1f}% gross {s['gross_r']:+.3f}R net {s['net_r']:+.3f}R "
              f"CI {s['ci_day'][0]:+.3f}..{s['ci_day'][1]:+.3f} PF {s['pf']:.2f} positive days {s['positive_days']}/{len(s['by_day'])} "
              f"exits {s['exits']} index trades {s['index_trades']} best {s['best']} worst {s['worst']} paper Rs {s['net_inr']:,.0f}")
    print("sessions used:", len(keep), sorted(keep))
    if out:
        out.write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("pkl", type=Path)
    ap.add_argument("--seed", type=int, default=20261019)
    ap.add_argument("--target", type=int, default=250)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    main(a.pkl, a.seed, a.target, a.out)
