"""NFCE-X phase 2, model M1 (../evidence/nfx_model_protocol.md, SHA-256 fc66f789…5881).

  python tools/nfx_model.py --stage train                      # walk-forward diagnostics inside 2022–24, then fit
  python tools/nfx_model.py --stage validation                 # ONE look at 2025
  python tools/nfx_model.py --stage final --i-accept-one-shot  # only for a model that passed validation

Each stage writes its JSON next to the store (_m1_<stage>.json); validation refuses to run twice.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce.stats import block_bootstrap_mean  # noqa: E402

STORE = Path.home() / "Downloads" / "nfce_data" / "nfx_features"
TRAIN = (date(2022, 1, 1), date(2024, 12, 31))
VALID = (date(2025, 1, 1), date(2025, 12, 31))
FINAL = (date(2026, 1, 1), date(2026, 10, 21))
FOLDS = [(date(2022, 12, 31), date(2023, 1, 1), date(2023, 6, 30)),
         (date(2023, 6, 30), date(2023, 7, 1), date(2023, 12, 31)),
         (date(2023, 12, 31), date(2024, 1, 1), date(2024, 12, 31))]
TRAIN_STARTS = ("09:42", "14:12")                     # bar starts whose close is 09:45 .. 14:15
DECIDE = {"10:12", "11:12", "12:12", "13:12", "14:12"}  # bars closing 10:15, 11:15, 12:15, 13:15, 14:15
TOP_K, COST_BP, CASH_COST_BP, MIN_EDGE_BP, CLIP = 5, 15.0, 12.0, 7.5, 0.05


def load(label: str = "y_20") -> tuple[pd.DataFrame, list[str]]:
    frames = []
    for p in sorted(STORE.glob("*.pkl")):
        f = pd.read_pickle(p)
        f = f[(f.index.strftime("%H:%M") >= TRAIN_STARTS[0]) & (f.index.strftime("%H:%M") <= TRAIN_STARTS[1])]
        f = f[f[label].notna()]
        f.insert(0, "sym", p.stem)
        frames.append(f)
    df = pd.concat(frames)
    df["ts"] = df.index
    df["day"] = df.index.date
    df["ret"] = df[label]                                # the label that trains the model AND books the P&L
    df["target"] = (df["ret"] - df.groupby("ts")["ret"].transform("mean")).clip(-CLIP, CLIP)
    feats = [c for c in df.columns if c not in ("sym", "ts", "day", "target", "ret") and not c.startswith("y_")]
    return df.reset_index(drop=True), feats


def models():
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return {"M1": lambda: HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=31,
                                                        min_samples_leaf=500, l2_regularization=1.0,
                                                        random_state=20261027),
            "B1": lambda: make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=10))}


def between(df, a, b):
    return df[(df["day"] >= a) & (df["day"] <= b)]


def embargo(train: pd.DataFrame, boundary: date) -> pd.DataFrame:
    days = sorted(train["day"].unique())
    return train[train["day"] < days[-1]] if days and days[-1] >= boundary else train   # drop the last day


def evaluate(test: pd.DataFrame, pred: np.ndarray) -> dict:
    t = test.assign(pred=pred)
    # IC per timestamp
    ic = t.groupby("ts").apply(lambda g: g["pred"].rank().corr(g["target"].rank()) if len(g) > 10 else np.nan,
                               include_groups=False).dropna()
    icd = ic.groupby(pd.Index(ic.index.date)).mean()
    ic_t = icd.mean() / (icd.std() / math.sqrt(len(icd))) if len(icd) > 1 else 0.0
    # trading rule at the non-overlapping decision bars
    d = t[t["ts"].dt.strftime("%H:%M").isin(DECIDE)]
    rows = []
    for ts, g in d.groupby("ts"):
        if len(g) < 2 * TOP_K:
            continue
        med = g["pred"].median()
        g = g.sort_values("pred")
        for side, part in ((1, g.tail(TOP_K)), (-1, g.head(TOP_K))):
            for _, r in part.iterrows():
                if side * (r["pred"] - med) * 1e4 < MIN_EDGE_BP:
                    continue
                gross = side * r["ret"] * 1e4
                rows.append({"day": ts.date(), "side": side, "gross": gross, "net": gross - COST_BP,
                             "cash_net": gross - CASH_COST_BP if side == 1 else np.nan})
    if not rows:
        return {"ic": float(ic.mean()) if len(ic) else None, "ic_t_day": ic_t, "trades": 0}
    r = pd.DataFrame(rows)
    dm = r.groupby("day")["net"].mean()
    tt = dm.mean() / (dm.std() / math.sqrt(len(dm))) if len(dm) > 1 and dm.std() > 0 else 0.0
    from scipy.stats import t as student
    p = float(student.sf(tt, len(dm) - 1))
    lo, hi = block_bootstrap_mean(r["net"].tolist(), r["day"].tolist())
    longs = r[r["side"] == 1]
    by_year = {str(y): round(float(g["net"].mean()), 2) for y, g in r.groupby(pd.Index([x.year for x in r["day"]]))}
    return {"ic": float(ic.mean()), "ic_t_day": float(ic_t), "trades": len(r), "days": int(len(dm)),
            "trades_per_day": round(len(r) / len(dm), 2), "hit": float((r["gross"] > 0).mean()),
            "gross_bp": float(r["gross"].mean()), "net_bp": float(r["net"].mean()), "ci": [lo, hi], "p_day": p,
            "worst_day_bp": float(dm.min()), "by_year": by_year,
            "cash_long_net_bp": float(longs["cash_net"].mean()) if len(longs) else None}


def passes(s: dict) -> bool:
    return (s.get("trades", 0) > 0 and s["net_bp"] > 0 and s["ci"][0] > 0 and s["p_day"] < 0.025
            and s["ic"] > 0 and s["ic_t_day"] > 2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=("train", "validation", "final"), required=True)
    ap.add_argument("--i-accept-one-shot", action="store_true")
    ap.add_argument("--target", choices=("20", "x1"), default="20",
                    help="20 = the original protocol; x1 = amendment 1, entry at the next bar's open")
    x = ap.parse_args()
    tag = "m1" if x.target == "20" else "m1a1"
    out = STORE / f"_{tag}_{x.stage}.json"
    if x.stage != "train" and out.exists():
        sys.exit(f"{x.stage} was already run ({out}); it is one look only")
    if x.stage == "final" and not x.i_accept_one_shot:
        sys.exit("the final stage is one-shot: pass --i-accept-one-shot")
    t0 = time.time()
    df, feats = load("y_20" if x.target == "20" else "y_x1")
    print(f"loaded {len(df):,} rows, {len(feats)} features, {time.time() - t0:.0f}s", flush=True)
    res = {"protocol_sha256": "fc66f7892dcc59ce57ee247e3849205751e7dd2e72f1edbad60fd0e13c955881",
           "amendment_sha256": None if x.target == "20" else "58db352c996156d9c87452d002822c9784a36fb8675e1d11e4f692392e83a66b",
           "features": len(feats), "stage": x.stage}
    M = models()
    if x.stage == "train":
        res["folds"] = []
        for cut, a, b in FOLDS:
            tr = embargo(between(df, TRAIN[0], cut), cut)
            te = between(df, a, b)
            fold = {"train_to": str(cut), "test": f"{a}..{b}"}
            for name, mk in M.items():
                m = mk().fit(tr[feats], tr["target"])
                pred = m.predict(te[feats])
                fold[name] = evaluate(te, pred)
                if x.target == "x1":                         # delay curve (amendment 1, reported only)
                    for lab in ("y_x2", "y_x5"):
                        t2 = te.assign(ret=te[lab], pred_=pred)
                        t2 = t2[t2["ret"].notna()]
                        fold[f"{name}_{lab}"] = evaluate(t2.drop(columns="pred_"), t2["pred_"].to_numpy())
            res["folds"].append(fold)
            print(json.dumps(fold, default=str), flush=True)
    else:
        if x.stage == "validation":
            tr, te = embargo(between(df, *TRAIN), TRAIN[1]), between(df, *VALID)
        else:
            prev = json.loads((STORE / f"_{tag}_validation.json").read_text())
            if not any(prev[n]["pass"] for n in ("M1", "B1")):
                sys.exit("no model passed validation: the final stage is not run")
            tr, te = embargo(between(df, TRAIN[0], VALID[1]), VALID[1]), between(df, *FINAL)
        for name, mk in M.items():
            m = mk().fit(tr[feats], tr["target"])
            s = evaluate(te, m.predict(te[feats]))
            res[name] = s | {"pass": passes(s)}
            if name == "M1":
                from sklearn.inspection import permutation_importance
                smp = te.sample(min(len(te), 200_000), random_state=1)
                pi = permutation_importance(m, smp[feats], smp["target"], n_repeats=1, random_state=1, n_jobs=1)
                order = np.argsort(-pi.importances_mean)[:20]
                res["M1_top_features"] = [[feats[i], float(pi.importances_mean[i])] for i in order]
            print(name, json.dumps(res[name], default=str), flush=True)
    res["seconds"] = round(time.time() - t0)
    out.write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
