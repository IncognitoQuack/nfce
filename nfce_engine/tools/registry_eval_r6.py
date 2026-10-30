"""Score registered experiment R6 (../evidence/r6_protocol.md): the live forward benchmark of the range forecasts.

  python tools/registry_eval_r6.py --db ../nfce_bridge/data/nfce.db
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date

import numpy as np
import pandas as pd

QS = (0.1, 0.5, 0.9)
MIN_ROWS, MIN_SESSIONS, SEAS_N = 600, 40, 20
DEADLINE = date(2027, 3, 31)


def pinball_rows(y: np.ndarray, q: np.ndarray) -> np.ndarray:
    q = np.sort(q, axis=1)
    return np.mean([np.maximum(a * (y - q[:, k]), (a - 1) * (y - q[:, k])) for k, a in enumerate(QS)], axis=0)


def load(db) -> pd.DataFrame:
    con = db if isinstance(db, sqlite3.Connection) else sqlite3.connect(db)
    d = pd.read_sql("SELECT root, bar_close, model, q10, q50, q90, realized FROM range_forecasts "
                    "WHERE realized IS NOT NULL", con)
    t = pd.to_datetime(d.bar_close, utc=True).dt.tz_convert("Asia/Kolkata")
    d["day"], d["tod"] = t.dt.date, t.dt.hour * 60 + t.dt.minute
    return d


def seasonal(d: pd.DataFrame) -> pd.DataFrame:
    """SEAS: per index and decision time, quantiles of the previous 20 sessions' realised values."""
    base = d[d.model == "M1"][["root", "bar_close", "day", "tod", "realized"]].sort_values("day")
    out = []
    for _, g in base.groupby(["root", "tod"]):
        r = g.realized.shift(1).rolling(SEAS_N, min_periods=SEAS_N)
        out.append(g.assign(model="SEAS", q10=r.quantile(0.1).to_numpy(), q50=r.quantile(0.5).to_numpy(),
                            q90=r.quantile(0.9).to_numpy()))
    s = pd.concat(out) if out else base.assign(model="SEAS", q10=np.nan, q50=np.nan, q90=np.nan)
    return s.dropna(subset=["q10"])


def paired(d: pd.DataFrame, a: str, b: str, n_boot: int = 2000, seed: int = 11) -> dict:
    x = d[d.model == a].set_index(["root", "bar_close"])
    y = d[d.model == b].set_index(["root", "bar_close"])
    j = x.join(y[["q10", "q50", "q90"]], rsuffix="_b", how="inner")
    if j.empty:
        return {"n": 0}
    la = pinball_rows(j.realized.to_numpy(), j[["q10", "q50", "q90"]].to_numpy())
    lb = pinball_rows(j.realized.to_numpy(), j[["q10_b", "q50_b", "q90_b"]].to_numpy())
    g = pd.Series(la - lb).groupby(j.day.to_numpy()).agg(["sum", "count"])
    rng = np.random.default_rng(seed)
    k = len(g)
    boots = [g["sum"].to_numpy()[i].sum() / g["count"].to_numpy()[i].sum()
             for i in (rng.integers(0, k, k) for _ in range(n_boot))]
    return {"n": int(len(j)), "a": float(la.mean()), "b": float(lb.mean()), "diff": float((la - lb).mean()),
            "ci": [float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975))]}


def judge(d: pd.DataFrame, today: date | None = None) -> tuple[str, list[str]]:
    lines = []
    ready = True
    for root in ("NIFTY", "BANKNIFTY"):
        for m in ("M1", "HAR", "ENS"):
            g = d[(d.root == root) & (d.model == m)]
            lines.append(f"{root} {m}: {len(g)} scored forecasts over {g.day.nunique()} sessions")
            ready &= len(g) >= MIN_ROWS and g.day.nunique() >= MIN_SESSIONS
    if not ready:
        late = (today or date.today()) > DEADLINE
        return ("INCONCLUSIVE" if late else "NOT YET (minimum sample not reached)"), lines
    claims = {}
    cov = {}
    for root in ("NIFTY", "BANKNIFTY"):
        g = d[(d.root == root) & (d.model == "M1")]
        cov[root] = float(((g.realized >= g.q10) & (g.realized <= g.q90)).mean())
    claims["C1 calibrated"] = all(0.75 <= c <= 0.85 for c in cov.values())
    lines.append("M1 coverage: " + ", ".join(f"{k} {v:.1%}" for k, v in cov.items()))
    full = pd.concat([d, seasonal(d)])
    seas_keys = set(zip(*[full[full.model == "SEAS"][c] for c in ("root", "bar_close")]))
    sub = full[[k in seas_keys for k in zip(full.root, full.bar_close)]]
    for name, a, b, frame in (("C2 skill (M1 vs SEAS)", "M1", "SEAS", sub), ("C3 ML vs linear (M1 vs HAR)", "M1", "HAR", d)):
        r = paired(frame, a, b)
        claims[name] = r.get("n", 0) > 0 and r["ci"][1] < 0
        lines.append(f"{name}: {r}")
    better = "M1" if paired(d, "M1", "HAR").get("diff", 0) <= 0 else "HAR"
    r = paired(d, "ENS", better)
    claims["C4 ensemble"] = r.get("n", 0) > 0 and r["diff"] < 0 and r["ci"][1] < 0
    lines.append(f"C4 ensemble (ENS vs {better}): {r}")
    lines += [f"{k}: {'HOLDS' if v else 'does not hold'}" for k, v in claims.items()]
    return "JUDGED", lines


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    v, lines = judge(load(ap.parse_args().db))
    print(f"R6 live range benchmark: {v}")
    print("\n".join("  " + x for x in lines))
    sys.exit(0)
