"""SMART-EXIT-2: small profit target with a TIGHT stop, the owner's rule (../evidence/smart_exit_2_protocol.md).

  python tools/smart_exit2.py <hist3m folder> --stage train [--cache rows_smart2.pkl]
"""
from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import scanner_research as sr  # noqa: E402
from tools import stock3m_research as s3  # noqa: E402

P_MAX = 0.05 / 4
CONFIGS = {"T1": (0.5, 0.25, None), "T2": (0.3, 0.15, None), "T3": (0.5, 0.5, None), "T4": (0.5, 0.25, 0.25)}


def walk_tight(d, j0: int, side: int, entry: float, R0: float, book: float, stop_r: float, be_at: float | None,
               exit_hm: int = s3.EOD):
    """(exit price, reason, R0). Reason carries "|both" when the exit bar touched both the stop and the profit level."""
    o, h, l, c, m = (d[k].to_numpy() for k in ("open", "high", "low", "close", "hm"))
    tgt = entry + side * book * R0
    stop = entry - side * stop_r * R0
    for j in range(j0, len(d)):
        hit_stop = (side > 0 and l[j] <= stop) or (side < 0 and h[j] >= stop)
        hit_tgt = (side > 0 and h[j] >= tgt) or (side < 0 and l[j] <= tgt)
        if hit_stop:
            px = stop if j == j0 else (min(o[j], stop) if side > 0 else max(o[j], stop))
            return float(px), ("stop" if side * (stop - entry) < 0 else "scratch") + ("|both" if hit_tgt else ""), R0
        if hit_tgt:
            return float(tgt), "book", R0
        if m[j] >= exit_hm:
            return float(c[j]), "eod", R0
        fav = (h[j] - entry) if side > 0 else (entry - l[j])
        if be_at is not None and fav >= be_at * R0 and side * (entry - stop) > 0:
            stop = entry
    return float(c[-1]), "eod_incomplete", R0


WALKERS = {n: (lambda b, s, e: lambda d, j0, sd, en, r: walk_tight(d, j0, sd, en, r, b, s, e))(*cfg)
           for n, cfg in CONFIGS.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--stage", choices=list(s3.SPLITS), required=True)
    ap.add_argument("--configs", nargs="*")
    ap.add_argument("--cache", type=Path)
    x = ap.parse_args()
    if x.stage != "train" and not x.configs:
        sys.exit("later stages run only the configs that passed the stage before: pass --configs")
    if x.cache and x.cache.exists():
        rows = pickle.loads(x.cache.read_bytes())
    else:
        rows = s3.trades(x.folder, mults=(), walkers=WALKERS)
        if x.cache:
            x.cache.write_bytes(pickle.dumps(rows))
    a, b = s3.SPLITS[x.stage]
    print(f"stage {x.stage} ({a}..{b}); Bonferroni p < {P_MAX:.4f}")
    for name in x.configs or list(CONFIGS):
        sel = [r for r in rows[name] if a <= r["day"] <= b]
        s = sr.stats(sel)
        win = [r["net_r"] for r in sel if r["net_r"] > 0]
        loss = [r["net_r"] for r in sel if r["net_r"] <= 0]
        reasons = {}
        for r in sel:
            k = r["reason"].split("|")[0]
            reasons[k] = reasons.get(k, 0) + 1
        both = sum("|both" in r["reason"] for r in sel)
        ok = s["n"] and s["net_r"] > 0 and s["ci"][0] > 0 and s["p_day"] < P_MAX
        print(f"{name} n={s['n']} win {s['win'] * 100:.1f}% gross {s['gross_r']:+.3f} net {s['net_r']:+.3f}R "
              f"CI {s['ci'][0]:+.3f}..{s['ci'][1]:+.3f} p {s['p_day']:.4f} PF {s['pf']:.2f} Rs {s['net_inr']:+,.0f} "
              f"avg win {sum(win) / max(len(win), 1):+.3f} avg loss {sum(loss) / max(len(loss), 1):+.3f} "
              f"cost/trade {s['gross_r'] - s['net_r']:.3f}R exits {reasons} both-touched {both / max(len(sel), 1):.1%}"
              + ("  PASS" if ok else "  FAIL"), flush=True)


if __name__ == "__main__":
    main()
