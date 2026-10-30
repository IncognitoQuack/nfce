"""R4 live-feasible range model (../evidence/r4_protocol.md).

  python tools/train_range_model.py DATASET.pkl --stage validation
  python tools/train_range_model.py DATASET.pkl --stage final --i-accept-one-shot
  python tools/train_range_model.py DATASET.pkl --stage fit --out ../nfce_bridge/bridge/models/range_r4.pkl
  python tools/train_range_model.py DATASET.pkl --stage fit-m1 --out ../nfce_bridge/bridge/models/range_r4.pkl

fit-m1 (adopted 20 Oct 2026 by the pre-declared rule in ../evidence/range_benchmark_protocol.md): fitted on 2022-2025,
then conformalised on the Jan-Jul 2026 index rows (additive log-space shifts so 10% / 50% / 90% of them fall below
q10 / q50 / q90). The shifts are stored in meta["conformal_shift"] and applied by the bridge.

DATASET.pkl is the cache written by tools/ml_study.py (--cache).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

LIVE_FEATURES = ["r1", "r3", "r6", "r12", "r24", "r_open", "gap", "first30", "rng_atr", "atr_px", "rv12", "rv_prev",
                 "tod", "dow", "expiry", "vix", "vix5", "vix_open", "is_index"]
SPLITS = {"train": ("2022-01-01", "2024-12-31"), "validation": ("2025-01-01", "2025-12-31"), "final": ("2026-01-01", "2026-07-31"),
          "all": ("2022-01-01", "2026-07-31")}
INDICES = ("NIFTY", "BANKNIFTY")
TZ = "Asia/Kolkata"


def part(df, name):
    a, b = (pd.Timestamp(x, tz=TZ) for x in SPLITS[name])
    return df[(df.day >= a) & (df.day <= b) & np.isfinite(df.R60)]


def models():
    from sklearn.ensemble import HistGradientBoostingRegressor as H
    kw = dict(max_depth=6, max_iter=300, learning_rate=0.05, random_state=7)
    return {"point": H(**kw), "q10": H(loss="quantile", quantile=0.10, **kw), "q50": H(loss="quantile", quantile=0.50, **kw),
            "q90": H(loss="quantile", quantile=0.90, **kw)}


def fit(train: pd.DataFrame) -> dict:
    ms = models()
    for m in ms.values():
        m.fit(train[LIVE_FEATURES], train.R60)
    return ms


def score(ms: dict, test: pd.DataFrame) -> dict:
    from sklearn.metrics import r2_score
    t = test[test.sym.isin(INDICES)]
    pred = ms["point"].predict(t[LIVE_FEATURES])
    lo, hi = ms["q10"].predict(t[LIVE_FEATURES]), ms["q90"].predict(t[LIVE_FEATURES])
    y = t.R60.to_numpy()
    cov = float(((y >= lo) & (y <= hi)).mean())
    r2 = float(r2_score(y, pred))
    by = {ix: float(r2_score(t.R60[t.sym == ix], pred[(t.sym == ix).to_numpy()])) for ix in INDICES}
    return {"n_index": len(t), "r2_index": r2, "r2_by_index": by, "coverage_10_90_index": cov,
            "pass": bool(r2 >= 0.30 and 0.75 <= cov <= 0.85)}


def main(dataset: Path, stage: str, out: Path | None, one_shot: bool) -> None:
    if stage == "final" and not one_shot:
        sys.exit("final stage is one-shot: pass --i-accept-one-shot")
    df = pd.read_pickle(dataset)
    if stage in ("validation", "final"):
        ms = fit(part(df, "train"))
        res = score(ms, part(df, stage))
        print(json.dumps({"stage": stage, **res}, indent=1))
        return
    import sklearn
    if stage == "fit-m1":
        from sklearn.ensemble import HistGradientBoostingRegressor as H
        kw = dict(max_depth=6, max_iter=300, learning_rate=0.05, random_state=7)
        a, b = pd.Timestamp("2022-01-01", tz=TZ), pd.Timestamp("2025-12-31", tz=TZ)
        tr = df[(df.day >= a) & (df.day <= b) & np.isfinite(df.R60)]   # one filter, original row order (as benchmarked)
        ms = {k: H(loss="quantile", quantile=q, **kw).fit(tr[LIVE_FEATURES], tr.R60)
              for k, q in (("q10", 0.1), ("q50", 0.5), ("q90", 0.9))}
        cal = part(df, "final")
        cal = cal[cal.sym.isin(INDICES)]
        shift = [float(np.quantile(cal.R60 - ms[k].predict(cal[LIVE_FEATURES]), q))
                 for k, q in (("q10", 0.1), ("q50", 0.5), ("q90", 0.9))]
        trained, rows = ("2022-01-01", "2025-12-31"), int(len(tr))
    else:
        ms = fit(part(df, "all"))
        shift, trained, rows = [0.0, 0.0, 0.0], SPLITS["all"], int(len(part(df, "all")))
    meta = {"features": LIVE_FEATURES, "target": "log((max high - min low) over next 12 x 5m bars / close)",
            "trained_on": trained, "rows": rows, "conformal_shift": shift,
            "calibrated_on": SPLITS["final"] if stage == "fit-m1" else None,
            "model": "M1 (fit 2022-2025 + conformal on 2026-01..07)" if stage == "fit-m1" else "M0",
            "built_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "versions": {"python": platform.python_version(), "sklearn": sklearn.__version__, "numpy": np.__version__,
                         "pandas": pd.__version__}, "protocol": "evidence/r4_protocol.md"}
    blob = pickle.dumps({"meta": meta, "models": ms})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(blob)
    print(json.dumps({**meta, "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", type=Path)
    ap.add_argument("--stage", choices=["validation", "final", "fit", "fit-m1"], required=True)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--i-accept-one-shot", action="store_true")
    a = ap.parse_args()
    main(a.dataset, a.stage, a.out, a.i_accept_one_shot)
