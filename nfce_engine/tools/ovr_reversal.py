"""OVR-1: high-VIX, news-free overnight loser reversal (../evidence/ovr_reversal_protocol.md, SHA-256 23f54111…b8f7).

  python tools/ovr_reversal.py --stage train|validation|final [--i-accept-one-shot]

Everything is rebuilt from the 3-minute cash bars in ~/Downloads/nfce_data/hist3m_fo, as of the bar closing 15:15.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce.stats import block_bootstrap_mean  # noqa: E402

DATA = Path.home() / "Downloads" / "nfce_data"
SPLITS = {"train": (date(2022, 1, 1), date(2024, 12, 31)), "validation": (date(2025, 1, 1), date(2025, 12, 31)),
          "final": (date(2026, 1, 1), date(2026, 10, 20))}
COST_BP, TOP, THR, VOLX, VIX_PCT = 15.0, 3, -0.025, 1.5, 0.70
SKIP = {"INDIAVIX", "NIFTY", "BANKNIFTY", "SENSEX"}


def daily(d: pd.DataFrame) -> pd.DataFrame:
    d = d[~d.index.duplicated(keep="first")].sort_index()
    t = d.index.strftime("%H:%M")
    day = d.index.date
    g = d.groupby(day)
    to1515 = d[t <= "15:12"].groupby(d.index.date[t <= "15:12"])
    out = pd.DataFrame({
        "open": g["open"].first(),
        "close1515": to1515["close"].last(),
        "vol1515": to1515["volume"].sum(),
        "close": g["close"].last(),
        "rupee_vol": (d["close"] * d["volume"]).groupby(day).sum(),
        "exit0945": d[t == "09:42"].groupby(d.index.date[t == "09:42"])["close"].last(),
    })
    out["ret_d"] = np.log(out["close"] / out["close"].shift(1))
    prev = out.shift(1)                                        # statistics known at 15:15 come from earlier days
    out["vol_med20"] = prev["vol1515"].rolling(20, min_periods=15).median()
    out["rv20"] = prev["rupee_vol"].rolling(20, min_periods=15).mean()
    out["amihud20"] = (prev["ret_d"].abs() / prev["rupee_vol"]).rolling(20, min_periods=15).mean()
    out["intraday"] = np.log(out["close1515"] / out["open"])
    out["next_exit"] = out["exit0945"].shift(-1)               # the next session's 09:45 close
    out["overnight"] = np.log(out["next_exit"] / out["close1515"])
    return out


def build() -> pd.DataFrame:
    cal = pd.read_csv(DATA / "results_calendar.csv")
    cal = cal[cal["results"] == 1]
    res = {s: set(pd.to_datetime(g["date"]).dt.date) for s, g in cal.groupby("symbol")}
    rows = []
    for p in sorted((DATA / "hist3m_fo").glob("*_3m.pkl")):
        sym = p.stem[:-3]
        if sym in SKIP:
            continue
        dd = daily(pd.read_pickle(p))
        dd["sym"] = sym
        rdays = res.get(sym, set())
        dd["news"] = [any((x + timedelta(days=k)) in rdays for k in range(-1, 4)) for x in dd.index]  # t-3..t+1
        rows.append(dd)
    panel = pd.concat(rows)
    panel["mkt"] = panel.groupby(level=0)["intraday"].transform("mean")
    panel["rel"] = panel["intraday"] - panel["mkt"]
    v = pd.read_pickle(DATA / "hist3m_fo" / "INDIAVIX_3m.pkl")
    v = v[~v.index.duplicated(keep="first")]
    vt = v.index.strftime("%H:%M")
    v1515 = v[vt <= "15:12"].groupby(v.index.date[vt <= "15:12"])["close"].last()
    vclose = v.groupby(v.index.date)["close"].last()
    pct = pd.Series({d: (vclose.loc[:d].iloc[:-1].tail(252) <= v1515[d]).mean()
                     if len(vclose.loc[:d]) > 60 else np.nan for d in v1515.index})
    panel["vix_pct"] = pd.Series(panel.index).map(pct).to_numpy()
    return panel


def trades(panel: pd.DataFrame, gate: bool) -> pd.DataFrame:
    out = []
    for d, g in panel.groupby(level=0):
        g = g.dropna(subset=["rel", "overnight", "rv20", "amihud20", "vol_med20"])
        if g.empty or (gate and not (g["vix_pct"].iloc[0] >= VIX_PCT)):
            continue
        big = set(g.nlargest(30, "rv20")["sym"])
        g = g[~g["sym"].isin(big) & ~g["news"]]
        if g.empty:
            continue
        g = g[g["amihud20"] >= g["amihud20"].quantile(1 / 3)]
        g = g[(g["rel"] <= THR) & (g["vol1515"] >= VOLX * g["vol_med20"])]
        for _, r in g.nsmallest(TOP, "rel").iterrows():
            gross = r["overnight"] * 1e4
            out.append({"day": d, "sym": r["sym"], "rel": r["rel"], "gross": gross, "net": gross - COST_BP})
    return pd.DataFrame(out)


def stats(t: pd.DataFrame) -> dict:
    if t.empty:
        return {"n": 0}
    dm = t.groupby("day")["net"].mean()
    tt = dm.mean() / (dm.std() / math.sqrt(len(dm))) if len(dm) > 1 and dm.std() > 0 else 0.0
    from scipy.stats import t as student
    p = float(student.sf(tt, len(dm) - 1)) if len(dm) > 1 else 1.0
    lo, hi = block_bootstrap_mean(t["net"].tolist(), t["day"].tolist())
    return {"n": len(t), "nights": int(len(dm)), "win": float((t["net"] > 0).mean()), "gross_bp": float(t["gross"].mean()),
            "net_bp": float(t["net"].mean()), "ci": [lo, hi], "p_day": p, "worst_night_bp": float(dm.min())}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=list(SPLITS), required=True)
    ap.add_argument("--i-accept-one-shot", action="store_true")
    x = ap.parse_args()
    if x.stage == "final" and not x.i_accept_one_shot:
        sys.exit("the final stage is one-shot: pass --i-accept-one-shot")
    panel = build()
    a, b = SPLITS[x.stage]
    sel = panel[(panel.index >= a) & (panel.index <= b)]
    res = {"protocol_sha256": "23f54111ee8eb7278f5c32b9029cf42e999e335f5940cbc8ebedc0e3daa6b8f7", "stage": x.stage}
    s = stats(trades(sel, gate=True))
    res["OVR1"] = s | {"pass": bool(s.get("n", 0) >= 60 and s["net_bp"] > 0 and s["ci"][0] > 0 and s["p_day"] < 0.05)}
    res["context_no_vix_gate"] = stats(trades(sel, gate=False))
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
