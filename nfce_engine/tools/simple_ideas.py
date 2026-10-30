"""Test the pre-registered simple hypotheses (nfce/simple.py) on real 60-minute index data.

  python tools/fetch_yahoo.py --interval 60m      # once; Yahoo serves at most ~730 calendar days of 60m bars
  python tools/simple_ideas.py [--data DIR]

Every variant is reported: all trades, first 70% of sessions (in-sample), last 30% (out-of-sample), by year, under
dated historical costs (the fee schedule in force on each trade's date), the current-cost stress (18 Oct 2026
schedule on every trade) and the v1 "legacy" flat model for comparison with PHASE6. One lot, two orders a trade,
4 ticks friction per side. p-values are two-sided t-tests on net points; Holm controls the family of 8 tests.
Spot index prices are used as a proxy for futures (no basis, no roll): that is a limitation, not a cost.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce.data import load_csv  # noqa: E402
from nfce.simple import momentum, orb, stats  # noqa: E402
from nfce.stats import holm  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data" / "yahoo"
INDICES = [("NSEI", "NIFTY", 65, 0.1), ("NSEBANK", "BANKNIFTY", 30, 0.2)]


def line(s: dict) -> str:
    if s["n"] == 0:
        return "n=0"
    lo, hi = s["ci_week"]
    return (f"n={s['n']:3d} win={s['win'] * 100:3.0f}% gross {s['gross_pts']:+6.1f} cost {s['cost_pts']:5.1f} "
            f"net {s['net_pts']:+6.1f} pts [week-block 95% {lo:+.1f}, {hi:+.1f}] t={s['t']:+.2f} p={s['p']:.2f} "
            f"net Rs {s['net_inr']:,.0f}/lot maxDD Rs {s['max_dd_inr']:,.0f}")


def main(data: Path) -> None:
    pvals, results = {}, []
    for file, instr, pv, tick in INDICES:
        b, info = load_csv(data / f"{file}_60m.csv", 60)
        days = sorted(set(b.index.normalize()))
        cut = days[int(len(days) * 0.7)]
        print(f"\n=== {instr} ({file}_60m.csv sha256 {info['sha256'][:12]}): {info['rows']} bars, {info['sessions']} sessions "
              f"{info['first'][:10]} .. {info['last'][:10]}; out-of-sample from {cut:%Y-%m-%d}; "
              f"short sessions {info['short_sessions']}")
        for label, tr in [("H1 ORB stop=opposite", orb(b, "opposite")), ("H1 ORB stop=mid", orb(b, "mid")),
                          ("H2 momentum all", momentum(b, "all")), ("H2 momentum big", momentum(b, "big"))]:
            key = f"{instr} {label}"
            sd = stats(tr, pv, tick, cost_mode="dated")
            pvals[key] = sd["p"] if sd["n"] > 1 else 1.0
            results.append((key, sd))
            print(f"{label:22s} dated   {line(sd)}")
            print(f"{'':22s} current {line(stats(tr, pv, tick, cost_mode='current'))}")
            print(f"{'':22s} legacy  {line(stats(tr, pv, tick, cost_mode='legacy'))}")
            is_, oos = [t for t in tr if t.date < cut], [t for t in tr if t.date >= cut]
            print(f"{'':22s} IS  (dated) {line(stats(is_, pv, tick, cost_mode='dated'))}")
            print(f"{'':22s} OOS (dated) {line(stats(oos, pv, tick, cost_mode='dated'))}")
            years: dict = {}
            for t in tr:
                years.setdefault(t.date.year, []).append(t)
            print(f"{'':22s} by year (dated net pts/trade): "
                  + " | ".join(f"{y}: n{len(v)} {stats(v, pv, tick, cost_mode='dated')['net_pts']:+.1f}"
                               for y, v in sorted(years.items())))
    keep, net = holm(pvals), dict(results)
    sig = [f"{k} ({'LOSES money' if net[k]['net_pts'] < 0 else 'positive'}, t={net[k]['t']:+.2f})" for k, v in keep.items() if v]
    print("\nHolm, two-sided, family of 8, alpha 0.05, dated costs - significant: " + ("; ".join(sig) or "none"))
    print("Positive net after dated costs: " + (", ".join(k for k, s in results if s["n"] and s["net_pts"] > 0) or "none"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=DATA)
    main(ap.parse_args().data)
