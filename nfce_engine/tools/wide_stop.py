"""Wider stops for the stock 3m signals (../evidence/wide_stop_protocol.md).

  python tools/wide_stop.py <hist3m folder> --stage train [--cache rows_k.pkl]
  python tools/wide_stop.py <hist3m folder> --stage validation --configs K2 ... (only configs that passed train)
  python tools/wide_stop.py <hist3m folder> --stage final --configs ... --i-accept-one-shot
"""
from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import scanner_research as sr  # noqa: E402
from tools import stock3m_research as s3  # noqa: E402

MULTS = (1, 2, 3, 4)
P_MAX = 0.05 / 3                                          # Bonferroni over K2, K3, K4


def passes(s: dict) -> bool:
    return bool(s.get("n")) and s["net_r"] > 0 and s["ci"][0] > 0 and s["p_day"] < P_MAX


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
        rows = s3.trades(x.folder, mults=MULTS)
        if x.cache:
            x.cache.write_bytes(pickle.dumps(rows))
    a, b = s3.SPLITS[x.stage]
    wanted = x.configs or [f"K{k}" for k in MULTS[1:]]
    print(f"stage {x.stage} ({a}..{b}); Bonferroni p < {P_MAX:.4f}")
    for k in MULTS:
        name = "V0 (k=1, reference)" if k == 1 else f"K{k}"
        if k > 1 and name not in wanted:
            continue
        sel = [r for r in rows[k] if a <= r["day"] <= b]
        s = sr.stats(sel)
        if not s["n"]:
            print(f"{name}: n=0")
            continue
        exits = {}
        for r in sel:
            exits[r["reason"]] = exits.get(r["reason"], 0) + 1
        share = sorted(r["share"] for r in sel)[len(sel) // 2]
        print(f"{name:20s} n={s['n']} days {s['days']} win {s['win'] * 100:.1f}% gross {s['gross_r']:+.3f} "
              f"net {s['net_r']:+.3f}R CI {s['ci'][0]:+.3f}..{s['ci'][1]:+.3f} p(day) {s['p_day']:.4f} PF {s['pf']:.2f} "
              f"median cost share {share:.0%} Rs {s['net_inr']:+,.0f} exits {exits}"
              + ("" if k == 1 else ("  PASS" if passes(s) else "  FAIL")), flush=True)


if __name__ == "__main__":
    main()
