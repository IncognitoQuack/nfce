"""Range-forecast benchmark (../evidence/range_benchmark_protocol.md): the shipped R4 model vs simple baselines,
on FRESH Aug-Oct 2026 data the model never saw (set B) and on Jan-Jul 2026 (set A, secondary).

  python tools/range_benchmark.py UPSTOX_DIR YAHOO_60D.pkl MODEL.pkl ML_DATASET.pkl [--out result.json]

UPSTOX_DIR holds NIFTY_5m.pkl, BANKNIFTY_5m.pkl, INDIAVIX_5m.pkl (2022-01..2026-07); YAHOO_60D.pkl is the yfinance
download used by the hold-out study (^NSEI, ^NSEBANK, ^INDIAVIX); ML_DATASET.pkl is tools/ml_study.py's cache.
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce.research import expiry_dates  # noqa: E402
from tools.ml_study import DECISION_BAR_STARTS, symbol_frame  # noqa: E402
from tools.train_range_model import LIVE_FEATURES  # noqa: E402

TZ = "Asia/Kolkata"
QS = (0.1, 0.5, 0.9)
YAHOO = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "INDIAVIX": "^INDIAVIX"}
SET_B = ("2026-08-01", "2026-10-19")
SET_A = ("2026-01-01", "2026-07-31")


def yahoo(pkl: Path, name: str) -> pd.DataFrame:
    raw = pd.read_pickle(pkl)[YAHOO[name]]
    d = raw[["Open", "High", "Low", "Close"]].rename(columns=str.lower).dropna()
    d.index = pd.DatetimeIndex(d.index).tz_convert(TZ)
    d["volume"] = 0.0
    return d


def upstox(folder: Path, name: str) -> pd.DataFrame:
    d = pd.read_pickle(folder / f"{name}_5m.pkl")
    d.index = pd.DatetimeIndex(d.index).tz_convert(TZ)
    return d[["open", "high", "low", "close", "volume"]]


def overlap_check(u: pd.DataFrame, y: pd.DataFrame) -> float:
    a, b = pd.Timestamp("2026-07-24", tz=TZ), pd.Timestamp("2026-08-01", tz=TZ)
    j = u.close[(u.index >= a) & (u.index < b)].to_frame("u").join(y.close[(y.index >= a) & (y.index < b)].rename("y"),
                                                                     how="inner")
    return float((j.u / j.y - 1).abs().median()) if len(j) else float("nan")


def index_rows(bars: dict[str, pd.DataFrame], vix: pd.Series) -> pd.DataFrame:
    """Decision rows with the 19 live features, built exactly as tools/ml_study.py builds them."""
    sessions = sorted(set(bars["NIFTY"].index.normalize().date))
    exp = expiry_dates(sessions, "NIFTY")
    vday = vix.groupby(vix.index.normalize()).transform("first")
    out = []
    for s, d in bars.items():
        x = symbol_frame(d)
        rows = np.flatnonzero(x.hm.isin(DECISION_BAR_STARTS).to_numpy() & np.isfinite(x.R60.to_numpy()))
        f = x.iloc[rows].copy()
        f["sym"] = s
        f["is_index"] = 1.0
        f["expiry"] = [float(dd.date() in exp) for dd in f.day]
        f["vix"] = vix.reindex(f.index).to_numpy()
        f["vix5"] = (vix - vix.shift(5)).reindex(f.index).to_numpy()
        f["vix_open"] = (vix - vday).reindex(f.index).to_numpy()
        out.append(f[LIVE_FEATURES + ["R60", "sym", "day"]])
    return pd.concat(out)


def span(df: pd.DataFrame, a: str, b: str) -> pd.DataFrame:
    return df[(df.day >= pd.Timestamp(a, tz=TZ)) & (df.day <= pd.Timestamp(b, tz=TZ))]


def pinball(y: np.ndarray, p: np.ndarray, q: float) -> np.ndarray:
    e = y - p
    return np.maximum(q * e, (q - 1) * e)


# ---------------- competitors ----------------
def seasonal(all_rows: pd.DataFrame, test: pd.DataFrame, n: int = 20) -> np.ndarray:
    """B1: per index and decision time, quantiles of the previous n sessions' targets (past only)."""
    out = np.full((len(test), 3), np.nan)
    pos = {key: k for k, key in enumerate(zip(test.index, test.sym))}
    for (s, _), g in all_rows.groupby(["sym", "tod"]):
        g = g.sort_values("day")
        r = g.R60.shift(1).rolling(n, min_periods=n)
        qv = np.column_stack([r.quantile(q).to_numpy() for q in QS])
        for ts, row in zip(g.index, qv):
            k = pos.get((ts, s))
            if k is not None:
                out[k] = row
    return out


LOG_COLS = ("rv12", "rv_prev", "atr_px", "vix")
HAR_COLS = ["rv12", "rv_prev", "atr_px", "vix", "rng_atr", "expiry"]


def _design(df: pd.DataFrame, cols: list[str], tods: list[int], med: dict | None = None):
    X = pd.DataFrame(index=df.index)
    for c in cols:
        v = df[c].astype(float)
        X[c] = np.log(v.clip(lower=1e-9)) if c in LOG_COLS else v
    for t in tods[1:]:
        X[f"tod{t}"] = (df.tod == t).astype(float)
    med = X.median().to_dict() if med is None else med
    return X.fillna(med), med


def har_fit(train: pd.DataFrame, cols: list[str] = HAR_COLS) -> dict:
    """Linear quantile regression (pinball loss) per quantile, pooled over both indices; plain numbers only, so
    the bridge can evaluate it without scikit-learn."""
    from sklearn.linear_model import QuantileRegressor
    tods = sorted(int(t) for t in train.tod.unique())
    X, med = _design(train, cols, tods)
    coef = {}
    for q in QS:
        m = QuantileRegressor(quantile=q, alpha=0.0, solver="highs").fit(X.to_numpy(), train.R60.to_numpy())
        coef[str(q)] = [float(m.intercept_)] + [float(c) for c in m.coef_]
    return {"cols": list(cols), "tods": tods, "median": {k: float(v) for k, v in med.items()}, "columns": list(X.columns),
            "coef": coef, "target": "log next-60-minute range / close"}


def har_predict(model: dict, df: pd.DataFrame) -> np.ndarray:
    X, _ = _design(df, model["cols"], model["tods"], model["median"])
    X = X[model["columns"]].to_numpy()
    return np.column_stack([model["coef"][str(q)][0] + X @ np.array(model["coef"][str(q)][1:]) for q in QS])


def linear_quantiles(train: pd.DataFrame, test: pd.DataFrame, cols: list[str]) -> np.ndarray:
    """B2 / B3: linear quantile regression, one model per quantile, pooled over both indices."""
    return har_predict(har_fit(train, cols), test)


def hgb_fit(train: pd.DataFrame) -> dict:
    from sklearn.ensemble import HistGradientBoostingRegressor as H
    kw = dict(max_depth=6, max_iter=300, learning_rate=0.05, random_state=7)
    return {q: H(loss="quantile", quantile=q, **kw).fit(train[LIVE_FEATURES], train.R60) for q in QS}


def hgb_predict(ms: dict, test: pd.DataFrame) -> np.ndarray:
    return np.column_stack([ms[q].predict(test[LIVE_FEATURES]) for q in QS])


def shipped_predict(model_path: Path, test: pd.DataFrame) -> np.ndarray:
    blob = pickle.loads(model_path.read_bytes())
    m = blob["models"]
    return np.column_stack([m[k].predict(test[blob["meta"]["features"]]) for k in ("q10", "q50", "q90")])


def conformal_shift(pred: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Additive shifts so that exactly q of calibration targets fall below each shifted quantile."""
    return np.array([np.quantile(y - pred[:, k], q) for k, q in enumerate(QS)])


# ---------------- scoring ----------------
def metrics(y: np.ndarray, p: np.ndarray) -> dict:
    p = np.sort(p, axis=1)                                 # no quantile crossing
    pin = np.mean([pinball(y, p[:, k], q).mean() for k, q in enumerate(QS)])
    cov = float(((y >= p[:, 0]) & (y <= p[:, 2])).mean())
    r2 = float(1 - ((y - p[:, 1]) ** 2).sum() / ((y - y.mean()) ** 2).sum())
    return {"n": int(len(y)), "pinball": float(pin), "coverage": cov, "r2_q50": r2, "width": float((p[:, 2] - p[:, 0]).mean())}


def evaluate(test: pd.DataFrame, preds: dict[str, np.ndarray]) -> dict:
    ok = np.all([np.isfinite(p).all(axis=1) for p in preds.values()], axis=0)
    t = test[ok]
    y = t.R60.to_numpy()
    res = {"rows_scored": int(ok.sum()), "rows_dropped_no_prediction": int((~ok).sum()), "models": {}}
    tb = np.where(t.tod < 11 * 60 + 15, "before 11:15", np.where(t.tod < 13 * 60, "11:15-12:59", "13:00+"))
    for name, p in preds.items():
        p = p[ok]
        r = {"pooled": metrics(y, p)}
        for s in ("NIFTY", "BANKNIFTY"):
            m = (t.sym == s).to_numpy()
            r[s] = metrics(y[m], p[m])
        for b in ("before 11:15", "11:15-12:59", "13:00+"):
            m = tb == b
            r[b] = metrics(y[m], p[m])
        res["models"][name] = r
    return res, t, ok


def day_block_ci(t: pd.DataFrame, pa: np.ndarray, pb: np.ndarray, n: int = 2000, seed: int = 11) -> list[float]:
    y = t.R60.to_numpy()
    la = np.mean([pinball(y, np.sort(pa, 1)[:, k], q) for k, q in enumerate(QS)], axis=0)
    lb = np.mean([pinball(y, np.sort(pb, 1)[:, k], q) for k, q in enumerate(QS)], axis=0)
    d = pd.Series(la - lb).groupby(t.day.to_numpy()).agg(["sum", "count"])
    rng = np.random.default_rng(seed)
    k = len(d)
    boots = []
    for _ in range(n):
        i = rng.integers(0, k, k)
        boots.append(d["sum"].to_numpy()[i].sum() / d["count"].to_numpy()[i].sum())
    return [float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975)), float((la - lb).mean())]


def main(upstox_dir: Path, ypkl: Path, model: Path, mlds: Path, out: Path | None) -> None:
    warnings.filterwarnings("ignore")
    report = {"protocol": "evidence/range_benchmark_protocol.md (sha256 a9f0afa0...)"}
    bars, gaps = {}, {}
    for s in ("NIFTY", "BANKNIFTY", "INDIAVIX"):
        u, y = upstox(upstox_dir, s), yahoo(ypkl, s)
        gaps[s] = overlap_check(u, y)
        bars[s] = pd.concat([u, y[y.index >= pd.Timestamp("2026-08-01", tz=TZ)]]).sort_index()
    report["overlap_median_abs_close_diff"] = gaps
    reliable = all(gaps[s] <= 0.0005 for s in ("NIFTY", "BANKNIFTY"))
    report["set_B_reliable"] = reliable
    print("overlap check (median |Upstox/Yahoo - 1| on 24-31 Jul):", {k: f"{v:.5%}" for k, v in gaps.items()},
          "->", "OK" if reliable else "UNRELIABLE", flush=True)
    vix = bars.pop("INDIAVIX").close
    rows = index_rows(bars, vix)
    ds = pd.read_pickle(mlds)

    # ---- set B (fresh) ----
    B = span(rows, *SET_B)
    trainB = span(rows, "2022-01-01", "2026-07-31")
    print(f"set B: {len(B)} index decision rows, {B.day.nunique()} sessions", flush=True)
    m1 = hgb_fit(span(ds, "2022-01-01", "2025-12-31").pipe(lambda d: d[np.isfinite(d.R60)]))
    cal = span(ds, *SET_A)
    cal = cal[cal.sym.isin(["NIFTY", "BANKNIFTY"]) & np.isfinite(cal.R60)]
    shift = conformal_shift(hgb_predict(m1, cal), cal.R60.to_numpy())
    report["M1_conformal_shifts_log"] = shift.tolist()
    predsB = {
        "M0 shipped R4": shipped_predict(model, B),
        "M1 refit+conformal": hgb_predict(m1, B) + shift,
        "B1 seasonal 20d": seasonal(rows, B),
        "B2 VIX quantile reg": linear_quantiles(trainB, B, ["vix"]),
        "B3 HAR+VIX quantile reg": linear_quantiles(trainB, B, HAR_COLS),
    }
    resB, tB, okB = evaluate(B, predsB)
    base_names = [k for k in predsB if k.startswith("B")]
    best_base = min(base_names, key=lambda k: resB["models"][k]["pooled"]["pinball"])
    ci = day_block_ci(tB, predsB["M0 shipped R4"][okB], predsB[best_base][okB])
    resB["M0_minus_best_baseline"] = {"baseline": best_base, "mean": ci[2], "ci95": ci[:2]}
    M0 = resB["models"]["M0 shipped R4"]
    M1 = resB["models"]["M1 refit+conformal"]
    claims = {
        "best_on_benchmark": bool(all(M0["pooled"]["pinball"] < resB["models"][b]["pooled"]["pinball"] for b in base_names)
                                  and all(M0[s]["pinball"] < resB["models"][b][s]["pinball"] for b in base_names
                                          for s in ("NIFTY", "BANKNIFTY")) and ci[1] < 0),
        "M0_bands_reliable": bool(all(0.75 <= M0[s]["coverage"] <= 0.85 for s in ("NIFTY", "BANKNIFTY"))),
        "M1_bands_reliable": bool(all(0.75 <= M1[s]["coverage"] <= 0.85 for s in ("NIFTY", "BANKNIFTY"))),
        "adopt_M1_for_R4": bool(M1["pooled"]["pinball"] <= M0["pooled"]["pinball"]
                                and abs(M1["pooled"]["coverage"] - 0.8) < abs(M0["pooled"]["coverage"] - 0.8)),
    }
    resB["claims"] = claims
    report["set_B_fresh"] = resB

    # ---- set A (secondary, previously used) ----
    A = span(rows, *SET_A)
    trainA = span(rows, "2022-01-01", "2025-12-31")
    predsA = {"HGB (R4 architecture) fit 2022-25": hgb_predict(m1, A),
              "B1 seasonal 20d": seasonal(rows, A),
              "B2 VIX quantile reg": linear_quantiles(trainA, A, ["vix"]),
              "B3 HAR+VIX quantile reg": linear_quantiles(trainA, A, HAR_COLS)}
    resA, _, _ = evaluate(A, predsA)
    report["set_A_secondary"] = resA

    for label, res in (("SET B (fresh, Aug-Oct 2026)", resB), ("SET A (secondary, Jan-Jul 2026)", resA)):
        print(f"\n{label}: rows scored {res['rows_scored']} (dropped without a prediction: {res['rows_dropped_no_prediction']})")
        print("| Model | Pinball (pooled) | NIFTY | BANKNIFTY | Coverage 10-90 (N / BN) | R² q50 | Width |")
        print("|---|---|---|---|---|---|---|")
        for k, r in res["models"].items():
            print(f"| {k} | {r['pooled']['pinball']:.4f} | {r['NIFTY']['pinball']:.4f} | {r['BANKNIFTY']['pinball']:.4f} | "
                  f"{r['pooled']['coverage']:.1%} ({r['NIFTY']['coverage']:.1%} / {r['BANKNIFTY']['coverage']:.1%}) | "
                  f"{r['pooled']['r2_q50']:.3f} | {r['pooled']['width']:.3f} |")
        print("| time of day (pooled pinball / coverage) | " + " | ".join(
            f"{b}: " + ", ".join(f"{k.split()[0]} {r[b]['pinball']:.4f}/{r[b]['coverage']:.0%}" for k, r in res["models"].items())
            for b in ("before 11:15", "11:15-12:59", "13:00+")) + " |")
    print("\nM0 - best baseline:", resB["M0_minus_best_baseline"])
    print("claims:", claims)
    if out:
        out.write_text(json.dumps(report, indent=1, default=float))


def save_har(upstox_dir: Path, ypkl: Path, out: Path) -> None:
    bars = {s: upstox(upstox_dir, s) for s in ("NIFTY", "BANKNIFTY", "INDIAVIX")}
    vix = bars.pop("INDIAVIX").close
    rows = span(index_rows(bars, vix), "2022-01-01", "2026-07-31")
    m = har_fit(rows)
    m["trained_on"] = ["2022-01-01", "2026-07-31"]
    m["rows"] = int(len(rows))
    out.write_text(json.dumps(m, indent=1))
    print(json.dumps({k: m[k] for k in ("cols", "rows", "trained_on")}))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--save-har":     # python tools/range_benchmark.py --save-har UPSTOX_DIR OUT.json
        save_har(Path(sys.argv[2]), None, Path(sys.argv[3]))
        sys.exit(0)
    ap = argparse.ArgumentParser()
    ap.add_argument("upstox_dir", type=Path)
    ap.add_argument("yahoo_pkl", type=Path)
    ap.add_argument("model", type=Path)
    ap.add_argument("ml_dataset", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    main(a.upstox_dir, a.yahoo_pkl, a.model, a.ml_dataset, a.out)
