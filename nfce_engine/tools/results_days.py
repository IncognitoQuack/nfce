"""Results days and the stock 3m signals (../evidence/results_days_protocol.md).

  python tools/results_days.py <results_calendar.csv> <NIFTY_1d.pkl> --v0 rows213.pkl --k4 rows_k.pkl --stage train
"""
from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import scanner_research as sr  # noqa: E402
from tools import stock3m_research as s3  # noqa: E402


def event_days(cal_csv: Path, trading_days: pd.DatetimeIndex) -> set:
    """{(symbol, date)} for each results meeting day D and the next trading day."""
    c = pd.read_csv(cal_csv, parse_dates=["date"])
    c = c[c.results == 1]
    days = trading_days.normalize()
    out = set()
    for sym, d in zip(c.symbol, c.date):
        out.add((sym, d.date()))
        k = days.searchsorted(d, side="right")
        if k < len(days):
            out.add((sym, days[k].date()))
    return out


def diff_p(e: list[dict], n: list[dict], seed: int = 0) -> tuple[float, float]:
    """Mean(E) - mean(N) and the one-sided p that E is NOT worse, from a day-block bootstrap."""
    rng = np.random.default_rng(seed)
    by_e, by_n = {}, {}
    for r in e:
        by_e.setdefault(r["day"], []).append(r["net_r"])
    for r in n:
        by_n.setdefault(r["day"], []).append(r["net_r"])
    de, dn = list(by_e.values()), list(by_n.values())
    obs = np.mean([x for v in de for x in v]) - np.mean([x for v in dn for x in v])
    boots = []
    for _ in range(5000):
        se = [x for i in rng.integers(0, len(de), len(de)) for x in de[i]]
        sn = [x for i in rng.integers(0, len(dn), len(dn)) for x in dn[i]]
        boots.append(np.mean(se) - np.mean(sn))
    boots = np.array(boots)
    return float(obs), float((boots >= 0).mean())          # p = share of resamples where E is not worse


def report(name: str, rows: list[dict], ev: set) -> None:
    e = [r for r in rows if (r["sym"], r["day"]) in ev]
    n = [r for r in rows if (r["sym"], r["day"]) not in ev]
    for label, sel in (("results window", e), ("other days    ", n)):
        s = sr.stats(sel)
        sd = float(np.std([r["net_r"] for r in sel])) if sel else float("nan")
        worst = sorted(r["net_r"] for r in sel)[:3]
        print(f"  {name} {label}: n={s['n']} win {s['win'] * 100:.1f}% net {s['net_r']:+.3f}R sd {sd:.3f} "
              f"worst {[round(w, 2) for w in worst]} Rs {s['net_inr']:+,.0f}")
    d, p = diff_p(e, n)
    print(f"  {name}: difference E-N {d:+.3f}R, p (E not worse) {p:.4f} -> H_R {'HOLDS' if p < 0.05 and d < 0 else 'fails'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("calendar", type=Path)
    ap.add_argument("nifty_daily", type=Path)
    ap.add_argument("--v0", type=Path, required=True)
    ap.add_argument("--k4", type=Path, required=True)
    ap.add_argument("--stage", choices=list(s3.SPLITS), required=True)
    x = ap.parse_args()
    cal = pd.read_pickle(x.nifty_daily).index
    ev = event_days(x.calendar, pd.DatetimeIndex(cal))
    a, b = s3.SPLITS[x.stage]
    v0 = [r for r in pickle.loads(x.v0.read_bytes()) if a <= r["day"] <= b]
    k4 = [r for r in pickle.loads(x.k4.read_bytes())[4] if a <= r["day"] <= b]
    print(f"stage {x.stage} ({a}..{b}); {len(ev)} stock-days in results windows")
    report("V0", v0, ev)
    report("K4", k4, ev)


if __name__ == "__main__":
    main()
