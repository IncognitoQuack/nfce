"""Same-direction cap replay on the stock 3m trades (../evidence/cap_replay_protocol.md).

usage: python tools/cap_replay.py <hist3m folder> --stage train|validation [--cache rows.pkl]
"""
from __future__ import annotations

import argparse
import pickle
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.scanner_research import stats  # noqa: E402
from tools.stock3m_research import SPLITS, trades  # noqa: E402

CAP, WINDOW = 2, timedelta(minutes=30)


def capped(rows: list[dict]) -> list[dict]:
    """Skip a trade if CAP same-direction trades were already taken in the previous 30 minutes (any stock)."""
    taken: list[dict] = []
    for r in sorted(rows, key=lambda r: (r["time"], r["sym"])):
        recent = [t for t in taken[-200:] if t["side"] == r["side"] and r["time"] - WINDOW < t["time"] <= r["time"]]
        if len(recent) < CAP:
            taken.append(r)
    return taken


def daily(rows: list[dict]) -> dict:
    by = {}
    for r in rows:
        by[r["day"]] = by.get(r["day"], 0.0) + r["net_r"]
    days = np.array([by[d] for d in sorted(by)])
    cum = np.cumsum(days)
    dd = float(np.max(np.maximum.accumulate(np.concatenate([[0], cum]))[1:] - cum)) if len(cum) else 0.0
    return {"days": len(days), "mean_day": float(days.mean()), "worst_day": float(days.min()),
            "p5_day": float(np.quantile(days, 0.05)), "max_dd": dd, "total": float(days.sum())}


def report(name: str, rows: list[dict], base_n: int) -> dict:
    s, d = stats(rows), daily(rows)
    print(f"{name}: n={s['n']} (skipped {1 - s['n'] / base_n:.0%}) win {s['win'] * 100:.1f}% net {s['net_r']:+.3f}R/trade "
          f"CI {s['ci'][0]:+.3f}..{s['ci'][1]:+.3f} | per day: mean {d['mean_day']:+.2f}R worst {d['worst_day']:+.2f}R "
          f"p5 {d['p5_day']:+.2f}R | max DD {d['max_dd']:.1f}R | total {d['total']:+.1f}R | Rs {s['net_inr']:+,.0f}")
    return {**s, **d}


def verdict(v0: dict, cap: dict) -> bool:
    ok = (cap["worst_day"] >= 0.75 * v0["worst_day"] and cap["max_dd"] <= 0.75 * v0["max_dd"]
          and cap["p5_day"] > v0["p5_day"] and cap["net_r"] >= v0["net_r"] - 0.02)
    print(f"worst day {v0['worst_day']:+.2f} -> {cap['worst_day']:+.2f}R ({1 - cap['worst_day'] / v0['worst_day']:+.0%} better), "
          f"max DD {v0['max_dd']:.1f} -> {cap['max_dd']:.1f}R ({1 - cap['max_dd'] / v0['max_dd']:+.0%}), "
          f"p5 {v0['p5_day']:+.2f} -> {cap['p5_day']:+.2f}R, net/trade {v0['net_r']:+.3f} -> {cap['net_r']:+.3f}R")
    print("PASS" if ok else "FAIL")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--stage", choices=["train", "validation"], required=True)
    ap.add_argument("--cache", type=Path)
    x = ap.parse_args()
    if x.cache and x.cache.exists():
        rows = pickle.loads(x.cache.read_bytes())
    else:
        rows = trades(x.folder)
        if x.cache:
            x.cache.write_bytes(pickle.dumps(rows))
    a, b = SPLITS[x.stage]
    rows = [r for r in rows if a <= r["day"] <= b]
    v0 = report("V0 ", rows, len(rows))
    cap = report("CAP", capped(rows), len(rows))
    verdict(v0, cap)


if __name__ == "__main__":
    main()
