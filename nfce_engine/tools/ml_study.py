"""Machine-learning study (../evidence/ml_protocol.md): forecast direction, range and target-before-stop on NIFTY/BANKNIFTY
from 4.5 years of 5m bars, with strict time splits.

  python tools/ml_study.py DATA_DIR --stage validation|final [--out result.json]

The final stage refuses to run unless --i-accept-one-shot is given (it is meant to be run once).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce import costs  # noqa: E402
from nfce.research import expiry_dates  # noqa: E402
from nfce.stats import block_bootstrap_mean  # noqa: E402
from tools.research_run import INDEX, load  # noqa: E402

TZ = "Asia/Kolkata"
H = 12                                                       # 60 minutes of 5m bars
DECISION_BAR_STARTS = list(range(9 * 60 + 40, 14 * 60 + 11, 15))   # bars closing 09:45 .. 14:15
SPLITS = {"train": ("2022-01-01", "2024-12-31"), "validation": ("2025-01-01", "2025-12-31"), "final": ("2026-01-01", "2026-07-31")}
FEATURES = ["r1", "r3", "r6", "r12", "r24", "r_open", "gap", "first30", "vwap_d", "rng_atr", "atr_px", "rv12", "rv_prev",
            "tod", "dow", "expiry", "vix", "vix5", "vix_open", "br_open", "br12", "idx_minus_avg", "relvol", "is_index"]


def symbol_frame(d: pd.DataFrame, vol_proxy: pd.Series | None = None) -> pd.DataFrame:
    x = d.copy()
    if vol_proxy is not None:
        x["volume"] = vol_proxy.reindex(x.index).fillna(0)
    day = x.index.normalize()
    x["day"] = day
    x["hm"] = x.index.hour * 60 + x.index.minute
    lc = np.log(x.close)
    for k in (1, 3, 6, 12, 24):
        x[f"r{k}"] = lc - lc.shift(k)
    g = x.groupby("day")
    x["day_open"] = g.open.transform("first")
    x["r_open"] = lc - np.log(x.day_open)
    dclose = g.close.last()
    prev_close = dclose.shift(1).reindex(day).to_numpy()
    x["gap"] = np.log(x.day_open.to_numpy() / prev_close)
    c0940 = x[x.hm == 9 * 60 + 40].set_index("day").close
    x["first30"] = np.where(x.hm >= 9 * 60 + 40, np.log(c0940.reindex(day).to_numpy() / x.day_open.to_numpy()), np.nan)
    hlc3 = (x.high + x.low + x.close) / 3
    v = x.volume.fillna(0)
    cv = v.groupby(day).cumsum()
    vw = np.where(cv > 0, (hlc3 * v).groupby(day).cumsum() / cv.replace(0, np.nan), hlc3)
    dd = g.agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    pc = dd.close.shift(1)
    tr = pd.concat([dd.high - dd.low, (dd.high - pc).abs(), (dd.low - pc).abs()], axis=1).max(axis=1)
    atr_d = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().shift(1).reindex(day).to_numpy()
    x["atr_d"] = atr_d
    x["vwap_d"] = (x.close - vw) / atr_d
    x["rng_atr"] = (g.high.cummax() - g.low.cummin()) / atr_d
    x["atr_px"] = atr_d / x.close
    r1 = x.r1.where(x.hm != 9 * 60 + 15)                       # no overnight jump inside intraday volatility
    x["rv12"] = r1.rolling(12, min_periods=8).std()
    rv_day = r1.groupby(day).std()
    x["rv_prev"] = rv_day.shift(1).reindex(day).to_numpy()
    x["tod"] = x.hm
    x["dow"] = x.index.dayofweek
    tod_mean = v.groupby([x.hm, day]).sum().groupby(level=0).rolling(10, min_periods=3).mean().droplevel(0)
    prev_tod = tod_mean.groupby(level=0).shift(1)
    key = pd.MultiIndex.from_arrays([x.hm, day])
    x["relvol"] = v.to_numpy() / prev_tod.reindex(key).to_numpy()
    tr5 = np.maximum(x.high - x.low, np.maximum((x.high - x.close.shift()).abs(), (x.low - x.close.shift()).abs()))
    x["atr5"] = tr5.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    # ---- targets (strictly after the decision bar) ----
    fut_close = x.close.shift(-H)
    same_day = x.day.shift(-H) == x.day
    x["D60"] = np.where(same_day, np.sign(fut_close - x.close), np.nan)
    hi = x.high[::-1].rolling(H, min_periods=H).max()[::-1].shift(-1)
    lo = x.low[::-1].rolling(H, min_periods=H).min()[::-1].shift(-1)
    x["R60"] = np.where(same_day, np.log((hi - lo) / x.close), np.nan)
    x["fut_close"] = fut_close
    return x


def target_before_stop(x: pd.DataFrame, rows: np.ndarray) -> np.ndarray:
    h, l, c, a = x.high.to_numpy(), x.low.to_numpy(), x.close.to_numpy(), x.atr5.to_numpy()
    days = x.day.to_numpy()
    out = np.full(len(rows), np.nan)
    for k, i in enumerate(rows):
        if not np.isfinite(a[i]):
            continue
        up, dn = c[i] + a[i], c[i] - a[i]
        res = 0.0
        for j in range(i + 1, min(i + 1 + H, len(c))):
            if days[j] != days[i]:
                break
            if l[j] <= dn:                                      # stop first when both are touched in one bar
                res = 0.0
                break
            if h[j] >= up:
                res = 1.0
                break
        out[k] = res
    return out


def build(data: Path) -> pd.DataFrame:
    stock_files = sorted(p for p in data.glob("*_5m.pkl") if p.stem[:-3] not in ("NIFTY", "BANKNIFTY", "INDIAVIX"))
    stocks = {p.stem[:-3]: load(data, p.stem[:-3]) for p in stock_files}
    vix = load(data, "INDIAVIX").close
    frames = {}
    for s, d in stocks.items():
        frames[s] = symbol_frame(d)
    for ix in ("NIFTY", "BANKNIFTY"):
        proxy = sum(stocks[h].volume.reindex(load(data, ix).index).fillna(0) for h in INDEX[ix][2])
        frames[ix] = symbol_frame(load(data, ix), proxy)
    base = frames["NIFTY"]
    opens = pd.DataFrame({s: f.close / f.day_open for s, f in frames.items() if s not in INDEX}).reindex(base.index)
    r12 = pd.DataFrame({s: f.r12 for s, f in frames.items() if s not in INDEX}).reindex(base.index)
    br_open = (opens > 1).sum(1) / opens.notna().sum(1)
    br12 = (r12 > 0).sum(1) / r12.notna().sum(1)
    avg_open = np.log(opens).mean(1)
    sessions = sorted(set(base.index.normalize().date))
    exp = expiry_dates(sessions, "NIFTY")
    vday = vix.groupby(vix.index.normalize()).transform("first")
    out = []
    for s, x in frames.items():
        sel = x.hm.isin(DECISION_BAR_STARTS).to_numpy() & np.isfinite(x.D60.to_numpy())
        rows = np.flatnonzero(sel)
        f = x.iloc[rows].copy()
        f["TB"] = target_before_stop(x, rows)
        f["sym"] = s
        f["is_index"] = float(s in INDEX)
        f["expiry"] = [float(d.date() in exp) for d in f.day]
        f["vix"] = vix.reindex(f.index).to_numpy()
        f["vix5"] = (vix - vix.shift(5)).reindex(f.index).to_numpy()
        f["vix_open"] = (vix - vday).reindex(f.index).to_numpy()
        f["br_open"] = br_open.reindex(f.index).to_numpy()
        f["br12"] = br12.reindex(f.index).to_numpy()
        f["idx_minus_avg"] = f.r_open - avg_open.reindex(f.index).to_numpy()
        if s in INDEX:
            f["relvol"] = np.nan
        out.append(f[FEATURES + ["D60", "R60", "TB", "sym", "day", "close", "fut_close", "atr_d"]])
    df = pd.concat(out)
    df = df[np.isfinite(df.D60) & (df.D60 != 0)]
    return df


def split(df, name):
    a, b = (pd.Timestamp(x, tz=TZ) for x in SPLITS[name])
    return df[(df.day >= a) & (df.day <= b)]


def direction_models():
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    m = {f"logit C={c}": make_pipeline(SimpleImputer(), StandardScaler(), LogisticRegression(C=c, max_iter=500)) for c in (0.1, 1.0)}
    for depth in (3, 6):
        m[f"hgb depth={depth}"] = HistGradientBoostingClassifier(max_depth=depth, max_iter=300, learning_rate=0.05, random_state=7)
    return m


def range_models():
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LinearRegression
    from sklearn.pipeline import make_pipeline
    har = ["rv12", "rv_prev", "atr_px", "tod"]
    return {"HAR linear": (make_pipeline(SimpleImputer(), LinearRegression()), har),
            "hgb": (HistGradientBoostingRegressor(max_depth=6, max_iter=300, learning_rate=0.05, random_state=7), FEATURES)}


def trade_rule(test: pd.DataFrame, p: np.ndarray, thr: float, current_costs: bool = True) -> dict:
    """Indices only: trade the next 60 min when p > thr (long) or p < 1 - thr (short); one position at a time."""
    rows = []
    t = test.assign(p=p)
    for ix, g in t[t.sym.isin(list(INDEX))].groupby("sym"):
        lot, tick, _ = INDEX[ix]
        busy_until = None
        for ts, r in g.sort_index().iterrows():
            if busy_until is not None and ts < busy_until:
                continue
            side = 1 if r.p > thr else -1 if r.p < 1 - thr else 0
            if not side:
                continue
            when = costs.CURRENT if current_costs else ts.date()
            c = costs.futures_cost_points(r.close, r.fut_close, side, when, lot, 1, 2, 4 * tick)
            R = 0.25 * r.atr_d
            rows.append(dict(day=str(ts.date()), net_r=(side * (r.fut_close - r.close) - c) / R,
                             gross_r=side * (r.fut_close - r.close) / R))
            busy_until = ts + pd.Timedelta(minutes=60)
    if not rows:
        return {"n": 0}
    df = pd.DataFrame(rows)
    lo, hi = block_bootstrap_mean(list(df.net_r), list(df.day))
    w, l_ = df.net_r[df.net_r > 0].sum(), -df.net_r[df.net_r < 0].sum()
    return {"n": len(df), "win": float((df.net_r > 0).mean()), "gross_r": float(df.gross_r.mean()),
            "net_r": float(df.net_r.mean()), "ci": [lo, hi], "pf": float(w / l_) if l_ > 0 else math.inf}


def evaluate(df: pd.DataFrame, stage: str) -> dict:
    from sklearn.metrics import log_loss, r2_score, roc_auc_score
    tr = split(df, "train")
    te = split(df, stage)
    res = {"stage": stage, "rows": {"train": len(tr), stage: len(te)}, "direction": {}, "range": {}, "tb": {}}
    ytr, yte = (tr.D60 > 0).astype(int), (te.D60 > 0).astype(int)
    base = float(ytr.mean())
    idx_mask = te.sym.isin(list(INDEX)).to_numpy()
    for name, m in direction_models().items():
        m.fit(tr[FEATURES], ytr)
        p = m.predict_proba(te[FEATURES])[:, 1]
        auc_all, auc_idx = roc_auc_score(yte, p), roc_auc_score(yte[idx_mask], p[idx_mask])
        ll, ll0 = log_loss(yte, p), log_loss(yte, np.full(len(yte), base))
        acc_idx = float(((p[idx_mask] > 0.5) == yte[idx_mask].astype(bool)).mean())
        conf = np.abs(p[idx_mask] - 0.5)
        top = conf >= np.quantile(conf, 0.9) if idx_mask.sum() else np.zeros(0, bool)
        acc_top = float(((p[idx_mask][top] > 0.5) == yte[idx_mask].astype(bool).to_numpy()[top]).mean()) if top.any() else math.nan
        rules = {f"thr {t}": trade_rule(te, p, t) for t in (0.52, 0.55, 0.58, 0.60)}
        res["direction"][name] = {"auc_all": auc_all, "auc_index": auc_idx, "logloss": ll, "logloss_base": ll0,
                                  "acc_index": acc_idx, "acc_index_top10pct": acc_top, "rules_current_costs": rules}
        print(f"[dir] {name:14s} AUC all {auc_all:.4f} index {auc_idx:.4f} | logloss {ll:.4f} vs base {ll0:.4f} | "
              f"acc index {acc_idx:.3f} top10% {acc_top:.3f} | " + " | ".join(
                  f"{k}: n{v.get('n', 0)} net {v.get('net_r', float('nan')):+.3f}" for k, v in rules.items()), flush=True)
    for name, (m, cols) in range_models().items():
        trr, ter = tr[np.isfinite(tr.R60)], te[np.isfinite(te.R60)]
        m.fit(trr[cols], trr.R60)
        pred = m.predict(ter[cols])
        r2_all = r2_score(ter.R60, pred)
        im = ter.sym.isin(list(INDEX)).to_numpy()
        r2_idx = r2_score(ter.R60[im], pred[im])
        res["range"][name] = {"r2_all": r2_all, "r2_index": r2_idx}
        print(f"[range] {name:10s} R2 all {r2_all:.3f} index {r2_idx:.3f}", flush=True)
    from sklearn.ensemble import HistGradientBoostingRegressor
    trr, ter = tr[np.isfinite(tr.R60)], te[np.isfinite(te.R60)]
    qs = {}
    for q in (0.1, 0.9):
        qm = HistGradientBoostingRegressor(loss="quantile", quantile=q, max_depth=6, max_iter=300, learning_rate=0.05, random_state=7)
        qm.fit(trr[FEATURES], trr.R60)
        qs[q] = qm.predict(ter[FEATURES])
    inside = (ter.R60.to_numpy() >= qs[0.1]) & (ter.R60.to_numpy() <= qs[0.9])
    im = ter.sym.isin(list(INDEX)).to_numpy()
    res["range"]["interval_10_90"] = {"coverage_all": float(inside.mean()), "coverage_index": float(inside[im].mean())}
    print(f"[range] 10-90% interval coverage all {inside.mean():.3f} index {inside[im].mean():.3f}", flush=True)
    from sklearn.ensemble import HistGradientBoostingClassifier
    trt, tet = tr[np.isfinite(tr.TB)], te[np.isfinite(te.TB)]
    tbm = HistGradientBoostingClassifier(max_depth=6, max_iter=300, learning_rate=0.05, random_state=7)
    tbm.fit(trt[FEATURES], trt.TB.astype(int))
    pt = tbm.predict_proba(tet[FEATURES])[:, 1]
    dec = pd.qcut(pt, 10, labels=False, duplicates="drop")
    cal = pd.DataFrame({"pred": pt, "hit": tet.TB.to_numpy(), "dec": dec}).groupby("dec").agg(pred=("pred", "mean"), hit=("hit", "mean"), n=("hit", "size"))
    res["tb"] = {"auc": float(roc_auc_score(tet.TB.astype(int), pt)), "base_rate": float(tet.TB.mean()),
                 "calibration": cal.round(3).to_dict(orient="index")}
    print(f"[TB] AUC {res['tb']['auc']:.4f} base {res['tb']['base_rate']:.3f}\n" + cal.round(3).to_string(), flush=True)
    return res


def main(data: Path, stage: str, out: Path | None, cache: Path | None, one_shot: bool) -> None:
    if stage == "final" and not one_shot:
        sys.exit("final stage is one-shot: pass --i-accept-one-shot")
    if cache and cache.exists():
        df = pd.read_pickle(cache)
    else:
        df = build(data)
        if cache:
            df.to_pickle(cache)
    print(f"samples {len(df):,} symbols {df.sym.nunique()} from {df.day.min():%Y-%m-%d} to {df.day.max():%Y-%m-%d}", flush=True)
    res = evaluate(df, stage)
    if out:
        out.write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("--stage", choices=["validation", "final"], required=True)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--cache", type=Path)
    ap.add_argument("--i-accept-one-shot", action="store_true")
    a = ap.parse_args()
    main(a.data, a.stage, a.out, a.cache, a.i_accept_one_shot)
