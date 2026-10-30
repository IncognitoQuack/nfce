"""Build the NFCE-X feature store from the 3-minute history (2022 → Oct 2026, 213 F&O stocks).

    ../nfce_bridge/.venv/bin/python tools/nfx_build.py [out_dir]

Writes one pickle per stock: features at the 15-minute decision bars (bars closing at :15/:30/:45/:00, 09:30–15:15),
then joins the cross-sectional ranks, breadth, VIX and results-calendar features. Label columns start with `y_` (future
returns, for training only). Reads only local files; no network.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nfx import features as fx  # noqa: E402

DATA = Path.home() / "Downloads" / "nfce_data"
SKIP = {"INDIAVIX", "NIFTY", "BANKNIFTY", "SENSEX"}


def decision_mask(idx: pd.DatetimeIndex) -> pd.Series:
    m = idx.hour * 60 + idx.minute + 3                                   # the bar's close, in minutes
    return pd.Series(((m % 15) == 0) & (m >= 570) & (m <= 915), index=idx)   # 09:30 .. 15:15


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    vix = pd.read_pickle(DATA / "hist3m_fo" / "INDIAVIX_3m.pkl")
    cal = pd.read_csv(DATA / "results_calendar.csv")
    xs_cols = ("mom_since_open", "mom_1h", "mom_1d", "rvol_cum", "natr_14", "d_ret_5")
    small, t0, done = {}, time.time(), []
    files = sorted(p for p in (DATA / "hist3m_fo").glob("*_3m.pkl") if p.stem[:-3] not in SKIP)
    for i, p in enumerate(files):
        sym = p.stem[:-3]
        d = pd.read_pickle(p)
        d = d[~d.index.duplicated(keep="first")].sort_index()
        f = fx.stock_features(d)
        keep = decision_mask(f.index).to_numpy()
        f = f[keep]
        f = (f.join(fx.labels(d)[keep]).join(fx.exec_labels(d)[keep]).join(fx.vix_features(vix, f.index))
             .join(fx.event_features(sym, f.index, cal)))
        f.to_pickle(out / f"{sym}.pkl")
        small[sym] = f[list(xs_cols)]
        done.append(sym)
        if i % 20 == 0:
            print(f"{i + 1}/{len(files)} {sym} {len(f)} rows, {time.time() - t0:.0f}s", flush=True)
    xs = fx.cross_section(small, xs_cols)
    for sym in done:
        f = pd.read_pickle(out / f"{sym}.pkl").join(xs[sym])
        f.to_pickle(out / f"{sym}.pkl")
    cols = [c for c in f.columns if not c.startswith("y_")]
    meta = {"stocks": len(done), "features": len(cols), "labels": [c for c in f.columns if c.startswith("y_")],
            "families": {fam: sum(fx.family(c) == fam for c in cols) for fam in sorted({fx.family(c) for c in cols})},
            "built_s": round(time.time() - t0)}
    (out / "_meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta, indent=1))


def add_exec_labels(out: Path) -> None:
    """Add the executable-entry labels (y_x1, y_x2, y_x5) to an existing store without rebuilding the features."""
    for p in sorted(out.glob("*.pkl")):
        f = pd.read_pickle(p)
        d = pd.read_pickle(DATA / "hist3m_fo" / f"{p.stem}_3m.pkl")
        f = f.drop(columns=[c for c in f.columns if c.startswith("y_x")]).join(fx.exec_labels(d).reindex(f.index))
        f.to_pickle(p)
    print("exec labels added:", len(list(out.glob("*.pkl"))), "stocks")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    target = Path(args[0]) if args else DATA / "nfx_features"
    add_exec_labels(target) if "--add-exec-labels" in sys.argv else main(target)
