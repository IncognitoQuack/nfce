"""CAL-1: turn-of-the-month and pre-holiday long NIFTY futures (../evidence/cal_1_protocol.md).

  python tools/cal_1.py --stage train|validation|final [--tests C1 C2] [--i-accept-one-shot]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce import costs  # noqa: E402

DATA = Path.home() / "Downloads" / "nfce_data"
SPLITS = {"train": (date(2006, 10, 23), date(2015, 12, 31)), "validation": (date(2016, 1, 1), date(2020, 12, 31)),
          "final": (date(2021, 1, 1), date(2026, 10, 28))}
GAP = (date(2016, 10, 22), date(2016, 10, 27))
CARRY, LOT, SLIP_BP, P_MAX, SEED = 0.062, 65, 2.0, 0.05 / 2, 20261028


def load() -> pd.Series:
    a = pd.read_pickle(DATA / "daily_2006" / "NIFTY_1d.pkl")["close"]
    b = pd.read_pickle(DATA / "daily" / "NIFTY_1d.pkl")["close"]
    s = pd.concat([a, b])
    s.index = pd.DatetimeIndex(s.index).normalize()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s[s.index.dayofweek < 5]


def holidays(days: pd.DatetimeIndex) -> set:
    allwd = pd.bdate_range(days[0], days[-1])
    have = set(days.date)
    return {d.date() for d in allwd if d.date() not in have and not (GAP[0] <= d.date() <= GAP[1])}


def trades(close: pd.Series) -> dict:
    """{'C1': [(buy_day, sell_day)], 'C2': [...]} as positions in the index (entry close i, exit close j)."""
    days = close.index
    ds = list(days.date)
    out = {"C1": [], "C2": []}
    month = pd.Series(range(len(days)), index=days).groupby([days.year, days.month])
    firsts = [g.iloc[0] for _, g in month]
    lasts = [g.iloc[-1] for _, g in month]
    for last, nxt_first in zip(lasts[:-1], firsts[1:]):     # day -1 = last; buy close of -2, sell close of +3
        i, j = last - 1, nxt_first + 2
        if i >= 0 and j < len(days):
            out["C1"].append((i, j))
    hol = holidays(days)
    for k in range(1, len(ds) - 1):                           # k = pre-holiday session: next weekday is a holiday
        nxt = (pd.Timestamp(ds[k]) + pd.offsets.BDay(1)).date()
        if nxt in hol:
            out["C2"].append((k - 1, k))
    return out


def score(close: pd.Series, pairs: list, a: date, b: date) -> list[dict]:
    rows = []
    for i, j in pairs:
        d0, d1 = close.index[i].date(), close.index[j].date()
        if not (a <= d0 and d1 <= b):
            continue
        e, x = float(close.iloc[i]), float(close.iloc[j])
        gross = (x / e - 1) * 1e4
        fee = costs.futures_cost_points(e, x, 1, costs.CURRENT, LOT, 1, 2, SLIP_BP / 1e4 * e) / e * 1e4
        carry = CARRY * (d1 - d0).days / 365 * 1e4
        rows.append({"buy": d0, "sell": d1, "gross_bp": gross, "net_bp": gross - fee - carry})
    return rows


def summary(rows: list[dict]) -> dict:
    from scipy import stats as st
    x = np.array([r["net_bp"] for r in rows])
    if len(x) < 3:
        return {"n": len(x)}
    rng = np.random.default_rng(SEED)
    boots = rng.choice(x, size=(10_000, len(x)), replace=True).mean(axis=1)
    t = st.ttest_1samp(x, 0.0, alternative="greater")
    years = pd.Series(x, index=[r["buy"].year for r in rows]).groupby(level=0).sum()
    return {"n": len(x), "win": float((x > 0).mean()), "gross": float(np.mean([r["gross_bp"] for r in rows])),
            "net": float(x.mean()), "ci": (float(np.quantile(boots, .025)), float(np.quantile(boots, .975))),
            "p": float(t.pvalue), "years_pos": f"{int((years > 0).sum())}/{len(years)}", "worst": float(x.min())}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=list(SPLITS), required=True)
    ap.add_argument("--tests", nargs="*", default=["C1", "C2"])
    ap.add_argument("--i-accept-one-shot", action="store_true")
    x = ap.parse_args()
    if x.stage == "final" and not x.i_accept_one_shot:
        sys.exit("the final stage is one-shot: pass --i-accept-one-shot")
    close = load()
    pairs = trades(close)
    a, b = SPLITS[x.stage]
    print(f"stage {x.stage} ({a}..{b}); NIFTY {close.index[0].date()}..{close.index[-1].date()} ({len(close)} days); "
          f"pass: net>0, CI>0, p<{P_MAX}")
    for name in x.tests:
        s = summary(score(close, pairs[name], a, b))
        if s["n"] < 3:
            print(f"{name}: n={s['n']}")
            continue
        ok = s["net"] > 0 and s["ci"][0] > 0 and s["p"] < P_MAX
        print(f"{name}: n={s['n']} win {s['win'] * 100:.1f}% gross {s['gross']:+.1f}bp net {s['net']:+.1f}bp "
              f"CI {s['ci'][0]:+.1f}..{s['ci'][1]:+.1f} p {s['p']:.4f} years+ {s['years_pos']} worst {s['worst']:+.0f}bp"
              + ("  PASS" if ok else "  FAIL"), flush=True)


if __name__ == "__main__":
    main()
