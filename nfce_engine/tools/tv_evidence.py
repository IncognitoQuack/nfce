"""Re-analyse the TradingView v2 base-variant trades (evidence/tv_v2_base_trades.txt) with the engine's own cost
schedule and statistics, independently of the in-browser script nfce_analysis_v2.js.

    python tools/tv_evidence.py ../evidence/tv_v2_base_trades.txt
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce.stats import CostModel, holm, report  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class TVTrade:
    entry_time: datetime
    side: str
    score: float
    entry: float
    R: float
    pnl: float
    exit: str
    bars: int
    orders: int


def parse(path: str) -> list[tuple[dict, list[TVTrade]]]:
    runs, meta = [], None
    for line in Path(path).read_text().splitlines():
        if line.startswith("NFCE|META|"):
            p = line.split("|")
            meta = {"sym": p[2], "tf": p[3], **dict(kv.split("=", 1) for kv in p[4:])}
        elif line.startswith("NFCE|V|0|"):
            p = line.split("|")
            trades = []
            for t in filter(None, p[9].split(";")):
                f = t.split(",")
                trades.append(TVTrade(datetime.fromtimestamp(int(f[0]) * 60, IST), f[1], float(f[2]), float(f[4]),
                                      float(f[5]), float(f[6]), f[7], int(f[8]), int(f[9])))
            if len(trades) != int(p[8]):
                raise ValueError(f"{meta['sym']} {meta['tf']}: {len(trades)} trades parsed, log says {p[8]}")
            runs.append((meta, trades))
    return runs


def main(path: str) -> None:
    runs = parse(path)
    pvals, rows = {}, []
    for meta, trades in runs:
        pv, tick = int(meta["pv"]), float(meta["mintick"])
        key = f"{meta['instr']} {meta['tf']}m"
        dated = report(trades, CostModel("dated", lot_units=pv, lots=10, friction_pts_per_side=4 * tick))
        cur = report(trades, CostModel("current", lot_units=pv, lots=10, friction_pts_per_side=4 * tick))
        pvals[key] = dated["p"]
        first, last = trades[0].entry_time.date(), trades[-1].entry_time.date()
        rows.append((key, first, last, meta, dated, cur))
    keep = holm(pvals)
    print("| Config | Trades (days) | Period | Win % net | Gross R | Cost R | Net R dated [day-block 95%] | Net R current | t | p | Holm | Net Rs lakh (10 lots) | mm |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for key, first, last, meta, d, c in rows:
        print(f"| {key} | {d['n']} ({d['days']}) | {first}..{last} | {d['win'] * 100:.0f} | {d['gross_r']:+.3f} | {d['cost_r']:.3f} | "
              f"{d['net_r']:+.3f} [{d['ci_day'][0]:+.2f}, {d['ci_day'][1]:+.2f}] | {c['net_r']:+.3f} | {d['t']:+.2f} | {d['p']:.2f} | "
              f"{'reject H0' if keep[key] else 'no'} | {d['net_inr'] * 10 / 1e5:+.2f} | "
              f"{meta['mmStateFlat']}/{meta['mmEmuFlat']}/{meta['mmQty']} |")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parents[2] / "evidence" / "tv_v2_base_trades.txt"))
