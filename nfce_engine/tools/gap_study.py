"""Opening gap / GIFT Nifty proxy (../evidence/gap_protocol.md).

  python tools/gap_study.py <NIFTY_1d.pkl> --v0 rows213.pkl --k4 rows_k.pkl --stage train
"""
from __future__ import annotations

import argparse
import pickle
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import scanner_research as sr  # noqa: E402

STAGES = {"train": ((date(2019, 1, 1), date(2024, 12, 31)), (date(2022, 1, 1), date(2024, 12, 31))),
          "validation": ((date(2025, 1, 1), date(2025, 12, 31)),) * 2,
          "final": ((date(2026, 1, 1), date(2026, 10, 20)),) * 2}
GAP_MIN, COST_RT, P_MAX = 0.003, 0.0008, 0.05 / 3


def gaps(nifty: pd.DataFrame) -> pd.Series:
    return (nifty["open"] / nifty["close"].shift(1) - 1).rename("gap")


def g1(nifty: pd.DataFrame, a: date, b: date, fade: bool = False) -> dict:
    g = gaps(nifty)
    oc = nifty["close"] / nifty["open"] - 1
    d = pd.DataFrame({"g": g, "oc": oc}).dropna()
    d = d[(d.index.date >= a) & (d.index.date <= b) & (d.g.abs() >= GAP_MIN)]
    s = np.sign(d.g) * (-1 if fade else 1)
    r = (s * d.oc - COST_RT).to_numpy()
    if len(r) < 10:
        return {"n": len(r)}
    from scipy.stats import t as student
    m, sd = r.mean(), r.std(ddof=1)
    rng = np.random.default_rng(0)
    blocks = [r[i:i + 20] for i in range(0, len(r), 20)]
    boots = [np.concatenate([blocks[j] for j in rng.integers(0, len(blocks), len(blocks))]).mean() for _ in range(5000)]
    return {"n": len(r), "mean": m, "p": float(student.sf(m / (sd / np.sqrt(len(r))), len(r) - 1)),
            "ci": (float(np.quantile(boots, .025)), float(np.quantile(boots, .975))), "win": float((r > 0).mean()),
            "total": float(r.sum()), "gross": float((s * d.oc).mean())}


def g2(rows: list[dict], gap_by_day: dict, a: date, b: date) -> tuple[dict, dict]:
    sel = [r for r in rows if a <= r["day"] <= b]
    keep = [r for r in sel if abs(gap_by_day.get(r["day"], 0.0)) >= GAP_MIN and r["side"] == np.sign(gap_by_day[r["day"]])]
    return sr.stats(keep), sr.stats(sel)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("nifty_daily", type=Path)
    ap.add_argument("--v0", type=Path, required=True)
    ap.add_argument("--k4", type=Path, required=True)
    ap.add_argument("--stage", choices=list(STAGES), required=True)
    x = ap.parse_args()
    nifty = pd.read_pickle(x.nifty_daily)
    (a1, b1), (a2, b2) = STAGES[x.stage]
    print(f"stage {x.stage}: G1 {a1}..{b1}, G2 {a2}..{b2}; Bonferroni p < {P_MAX:.4f}")
    for fade in (False, True):
        s = g1(nifty, a1, b1, fade)
        name = "G1 fade the gap (reported only)" if fade else "G1 follow the gap"
        ok = (not fade) and s["mean"] > 0 and s["ci"][0] > 0 and s["p"] < P_MAX
        print(f"{name:32s} days {s['n']} win {s['win'] * 100:.1f}% gross {s['gross'] * 100:+.3f}% net {s['mean'] * 100:+.3f}%/day "
              f"p {s['p']:.4f} CI {s['ci'][0] * 100:+.3f}..{s['ci'][1] * 100:+.3f}% total {s['total'] * 100:+.1f}%"
              + ("" if fade else ("  PASS" if ok else "  FAIL")))
    gd = {d.date(): v for d, v in gaps(nifty).dropna().items()}
    for name, path, key in (("G2-V0", x.v0, None), ("G2-K4", x.k4, 4)):
        rows = pickle.loads(path.read_bytes())
        rows = rows[key] if key else rows
        s, base = g2(rows, gd, a2, b2)
        ok = s["n"] and s["net_r"] > 0 and s["ci"][0] > 0 and s["p_day"] < P_MAX
        print(f"{name:32s} kept {s['n']} of {base['n']} win {s['win'] * 100:.1f}% net {s['net_r']:+.3f}R "
              f"(all trades {base['net_r']:+.3f}R) CI {s['ci'][0]:+.3f}..{s['ci'][1]:+.3f} p {s['p_day']:.4f} "
              f"Rs {s['net_inr']:+,.0f}  {'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
    main()
