"""Meta-labeling for the stock 3m signals (../evidence/meta_label_protocol.md).

  python tools/meta_label.py <hist3m folder> --nifty <NIFTY_5m.pkl> --cache rows.pkl [--final --i-accept-one-shot]

Fit 2022-23, threshold from 2024, ONE look at 2025; 2026 only with --final after a 2025 pass.
"""
from __future__ import annotations

import argparse
import sys
from collections import deque
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import scanner_research as sr  # noqa: E402
from tools.leads_2day import nifty_state, stock_rows  # noqa: E402

FEATURES = ["mins", "side", "stop_pct", "share", "nifty_aligned", "vix", "weekday", "cluster30"]
CUTS = [round(0.40 + 0.02 * i, 2) for i in range(16)]           # 0.40 .. 0.70


def add_features(rows: list[dict], nifty: pd.DataFrame, vix: pd.DataFrame) -> None:
    nifty_state(nifty, rows)
    vclose_t = vix.index + pd.Timedelta(minutes=3)               # a 3m bar labelled t closes at t + 3 min
    recent = {1: deque(), -1: deque()}
    for r in sorted(rows, key=lambda r: (r["time"], r["sym"])):
        t = r["time"]
        k = vclose_t.searchsorted(t, side="right") - 1
        r["vix"] = float(vix["close"].iloc[k]) if k >= 0 else np.nan
        q = recent[r["side"]]
        while q and q[0] <= t - timedelta(minutes=30):
            q.popleft()
        r["cluster30"] = sum(1 for x in q if x < t)               # earlier same-direction entries only
        q.append(t)
        r["mins"] = (t.hour * 60 + t.minute) - (9 * 60 + 15)
        r["stop_pct"] = r["R"] / r["entry"] * 100
        r["nifty_aligned"] = 0 if not r["nifty"] else (1 if r["nifty"] == r["side"] else -1)
        r["weekday"] = t.weekday()


def xy(rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    return (np.array([[r[f] for f in FEATURES] for r in rows], dtype=float),
            np.array([r["net_r"] > 0 for r in rows], dtype=int))


def period(rows, a: date, b: date) -> list[dict]:
    return [r for r in rows if a <= r["day"] <= b]


def report(name: str, rows: list[dict], p: np.ndarray, cut: float) -> dict:
    from sklearn.metrics import roc_auc_score
    _, y = xy(rows)
    auc = roc_auc_score(y, p) if len(set(y)) > 1 else float("nan")
    take = [r for r, pi in zip(rows, p) if pi >= cut]
    print(f"{name}: all n={len(rows)} base win {y.mean() * 100:.1f}% AUC {auc:.3f} | taken at p>={cut:.2f}:", end=" ")
    s = sr.stats(take)
    if s["n"]:
        print(f"n={s['n']} win {s['win'] * 100:.1f}% net {s['net_r']:+.3f}R CI {s['ci'][0]:+.3f}..{s['ci'][1]:+.3f} "
              f"p(day) {s['p_day']:.4f} PF {s['pf']:.2f} Rs {s['net_inr']:+,.0f}", flush=True)
    else:
        print("n=0", flush=True)
    return {**s, "auc": auc}


def main() -> None:
    from sklearn.ensemble import HistGradientBoostingClassifier
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--nifty", type=Path, required=True)
    ap.add_argument("--cache", type=Path)
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--i-accept-one-shot", action="store_true")
    x = ap.parse_args()
    nifty = pd.read_pickle(x.nifty)
    nifty.index = pd.DatetimeIndex(nifty.index).tz_convert("Asia/Kolkata")
    vix = pd.read_pickle(x.folder / "INDIAVIX_3m.pkl")
    vix.index = pd.DatetimeIndex(vix.index).tz_convert("Asia/Kolkata")
    rows = [r for r in stock_rows(x.folder, x.cache) if r["time"] < nifty.index[-1]]
    add_features(rows, nifty, vix)
    rows = [r for r in rows if not np.isnan(r["vix"])]
    fit, tune = period(rows, date(2022, 1, 1), date(2023, 12, 31)), period(rows, date(2024, 1, 1), date(2024, 12, 31))
    m = HistGradientBoostingClassifier(random_state=0).fit(*xy(fit))
    pt = m.predict_proba(xy(tune)[0])[:, 1]
    best = None
    print("2024 threshold search (mean net R of the trades taken):")
    for c in CUTS:
        take = [r for r, pi in zip(tune, pt) if pi >= c]
        if len(take) < 300:
            continue
        mean = float(np.mean([r["net_r"] for r in take]))
        print(f"  p>={c:.2f}: n={len(take)} net {mean:+.3f}R")
        if best is None or mean > best[1]:
            best = (c, mean)
    if best is None:
        print("no cut leaves 300 trades in 2024: FAIL")
        return
    cut = best[0]
    print(f"threshold fixed at {cut:.2f}")
    report("2024 (tuning) ", tune, pt, cut)
    val = period(rows, date(2025, 1, 1), date(2025, 12, 31))
    s = report("2025 VALIDATION", val, m.predict_proba(xy(val)[0])[:, 1], cut)
    ok = bool(s.get("n")) and s["net_r"] > 0 and s["ci"][0] > 0 and s["p_day"] < 0.05
    print("2025:", "PASS" if ok else "FAIL")
    if x.final:
        if not (ok and x.i_accept_one_shot):
            sys.exit("the 2026 test runs once, only after a 2025 pass, with --i-accept-one-shot")
        fin = period(rows, date(2026, 1, 1), date(2026, 12, 31))
        s = report("2026 FINAL     ", fin, m.predict_proba(xy(fin)[0])[:, 1], cut)
        print("2026:", "PASS" if s.get("n") and s["net_r"] > 0 and s["ci"][0] > 0 and s["p_day"] < 0.05 else "FAIL")


if __name__ == "__main__":
    main()
