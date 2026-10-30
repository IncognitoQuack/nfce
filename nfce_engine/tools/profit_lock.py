"""Profit lock on the stock 3m signals (../evidence/profit_lock_protocol.md).

  python tools/profit_lock.py <hist3m folder> --stage train [--cache rows_lock.pkl]
  python tools/profit_lock.py <hist3m folder> --stage validation --configs P2 ...   (only configs that passed)
"""
from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import scanner_research as sr  # noqa: E402
from tools import stock3m_research as s3  # noqa: E402

K, P_MAX = 4, 0.05 / 2


def walk_lock(d, j0: int, side: int, entry: float, R0: float, mode: str | None, exit_hm: int = s3.EOD):
    """K4 stop/target; mode 'P1' moves the stop to the entry, 'P2' trails it at half the best favourable excursion,
    once the excursion reaches 1 x R0. Same conventions as research2._walk: stop before target within a bar, a gap
    beyond the stop fills at the open, the entry bar's stop fills at the stop, a new stop applies from the next bar."""
    o, h, l, c, m = (d[k].to_numpy() for k in ("open", "high", "low", "close", "hm"))
    stop, target, best, moved = entry - side * K * R0, entry + side * K * R0, 0.0, False
    for j in range(j0, len(d)):
        if (side > 0 and l[j] <= stop) or (side < 0 and h[j] >= stop):
            px = stop if j == j0 else (min(o[j], stop) if side > 0 else max(o[j], stop))
            return float(px), ("lock" if moved else "stop"), K * R0
        if (side > 0 and h[j] >= target) or (side < 0 and l[j] <= target):
            return float(target), "target", K * R0
        if m[j] >= exit_hm:
            return float(c[j]), "eod", K * R0
        best = max(best, (h[j] - entry) if side > 0 else (entry - l[j]))
        if mode and best >= R0:
            new = entry if mode == "P1" else entry + side * 0.5 * best
            if (side > 0 and new > stop) or (side < 0 and new < stop):
                stop, moved = new, True
    return float(c[-1]), "eod_incomplete", K * R0


WALKERS = {"K4": lambda d, j0, s, e, r: walk_lock(d, j0, s, e, r, None),
           "P1": lambda d, j0, s, e, r: walk_lock(d, j0, s, e, r, "P1"),
           "P2": lambda d, j0, s, e, r: walk_lock(d, j0, s, e, r, "P2")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--stage", choices=list(s3.SPLITS), required=True)
    ap.add_argument("--configs", nargs="*")
    ap.add_argument("--cache", type=Path)
    ap.add_argument("--i-accept-one-shot", action="store_true")
    x = ap.parse_args()
    if x.stage != "train" and not x.configs:
        sys.exit("later stages run only the configs that passed the stage before: pass --configs")
    if x.stage == "final" and not x.i_accept_one_shot:
        sys.exit("the final stage is one-shot: pass --i-accept-one-shot")
    if x.cache and x.cache.exists():
        rows = pickle.loads(x.cache.read_bytes())
    else:
        rows = s3.trades(x.folder, mults=(), walkers=WALKERS)
        if x.cache:
            x.cache.write_bytes(pickle.dumps(rows))
    a, b = s3.SPLITS[x.stage]
    print(f"stage {x.stage} ({a}..{b}); Bonferroni p < {P_MAX:.3f}")
    for name in ["K4"] + (x.configs or ["P1", "P2"]):
        sel = [r for r in rows[name] if a <= r["day"] <= b]
        s = sr.stats(sel)
        win = [r["net_r"] for r in sel if r["net_r"] > 0]
        loss = [r["net_r"] for r in sel if r["net_r"] <= 0]
        reasons = {}
        for r in sel:
            reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
        ok = s["n"] and s["net_r"] > 0 and s["ci"][0] > 0 and s["p_day"] < P_MAX
        print(f"{name:3s} n={s['n']} win {s['win'] * 100:.1f}% gross {s['gross_r']:+.3f} net {s['net_r']:+.3f}R "
              f"CI {s['ci'][0]:+.3f}..{s['ci'][1]:+.3f} p {s['p_day']:.4f} PF {s['pf']:.2f} Rs {s['net_inr']:+,.0f} "
              f"avg win {sum(win) / max(len(win), 1):+.3f} avg loss {sum(loss) / max(len(loss), 1):+.3f} exits {reasons}"
              + ("" if name == "K4" else ("  PASS" if ok else "  FAIL")), flush=True)


if __name__ == "__main__":
    main()
