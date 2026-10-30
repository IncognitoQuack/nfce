"""Day-level profit booking (../evidence/day_rules_protocol.md).

  python tools/day_rules.py <rows_kt.pkl> --stage train [--configs DT-V0 DG-K4 ...]
"""
from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import stock3m_research as s3  # noqa: E402

P_MAX = 0.05 / 4


def day_total(trades: list[dict], rule: str | None) -> float:
    """Sum of net R of the trades taken that day. A trade is taken if it entered before the rule triggered;
    the trigger is judged on CLOSED trades only (exit_time <= now), so it reacts late (conservative)."""
    trades = sorted(trades, key=lambda r: (r["time"], r["sym"]))
    if rule is None:
        return float(sum(r["net_r"] for r in trades))
    events = sorted(((r["exit_time"], r["net_r"]) for r in trades), key=lambda e: e[0])
    trigger, run, peak = None, 0.0, 0.0
    for t, x in events:
        run += x
        peak = max(peak, run)
        if (rule == "DT" and run >= 3.0) or (rule == "DG" and peak >= 2.0 and run <= 0.5 * peak):
            trigger = t
            break
    return float(sum(r["net_r"] for r in trades if trigger is None or r["time"] < trigger))


def evaluate(rows: list[dict], rule: str, seed: int = 0) -> dict:
    days: dict = {}
    for r in rows:
        days.setdefault(r["day"], []).append(r)
    keys = sorted(days)
    base = np.array([day_total(days[k], None) for k in keys])
    new = np.array([day_total(days[k], rule) for k in keys])
    diff = new - base
    rng = np.random.default_rng(seed)
    blocks = [diff[i:i + 5] for i in range(0, len(diff), 5)]
    boots = np.array([np.concatenate([blocks[j] for j in rng.integers(0, len(blocks), len(blocks))]).mean()
                      for _ in range(5000)])
    eq = np.cumsum(new)
    return {"days": len(keys), "base": float(base.mean()), "new": float(new.mean()), "diff": float(diff.mean()),
            "p": float((boots <= 0).mean()), "worst": float(new.min()), "base_worst": float(base.min()),
            "p5": float(np.quantile(new, .05)), "maxdd": float(np.max(np.maximum.accumulate(np.r_[0, eq])[1:] - eq)),
            "changed": int((diff != 0).sum())}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("rows", type=Path)
    ap.add_argument("--stage", choices=list(s3.SPLITS), required=True)
    ap.add_argument("--configs", nargs="*")
    x = ap.parse_args()
    data = pickle.loads(x.rows.read_bytes())
    a, b = s3.SPLITS[x.stage]
    print(f"stage {x.stage} ({a}..{b}); Bonferroni p < {P_MAX}")
    for exits, k in (("V0", 1), ("K4", 4)):
        rows = [r for r in data[k] if a <= r["day"] <= b]
        for rule in ("DT", "DG"):
            name = f"{rule}-{exits}"
            if x.configs and name not in x.configs:
                continue
            s = evaluate(rows, rule)
            better = s["diff"] > 0 and s["p"] < P_MAX
            verdict = "PASS" if better and s["new"] > 0 else ("risk control only (still negative)" if better else "FAIL")
            print(f"{name}: days {s['days']} (changed {s['changed']}) mean/day {s['base']:+.3f} -> {s['new']:+.3f}R "
                  f"(diff {s['diff']:+.3f}, p {s['p']:.4f}) worst {s['base_worst']:+.2f} -> {s['worst']:+.2f}R "
                  f"p5 {s['p5']:+.2f}R maxDD {s['maxdd']:.1f}R  {verdict}")


if __name__ == "__main__":
    main()
