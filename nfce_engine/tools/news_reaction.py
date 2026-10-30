"""Stock reaction to NSE corporate announcements, from live recorded data (../evidence/news_reaction_protocol.md).

  python tools/news_reaction.py 2026-10-26 [2026-10-27 ...]

Inputs (read-only), per day: nfce_bridge/data/study_news_YYYYMMDD.db (table news: dissemination time, category)
and study_quotes_YYYYMMDD.db (table q: minute quotes with bid/ask for every F&O stock and NIFTY futures).
An event counts if the stock has cash-equity quotes that day (= an F&O stock) and it was disseminated in market
hours (09:15 <= t0 <= 15:00). Abnormal return = the stock's mid return minus NIFTY futures' mid return.
The registered rule (R1): if the abnormal return over the first 5 minutes after t0 is at least 0.40% in size, trade
in its direction at the first quote at or after max(t0 + 5 min, when the recorder saw it); exit at t0 + 60 min or
15:20, whichever comes first; buy at the ask, sell at the bid; cash-equity intraday fees on Rs 3 L.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.study2 import EQ_NOTIONAL, equity_intraday_fees  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "nfce_bridge" / "data"
HORIZONS = (5, 15, 30, 60)
OPEN, LAST_EVENT, EXIT_BY = "09:15:00", "15:00:00", "15:20:00"
TRIGGER, WAIT, HOLD = 0.004, 5, 60
# Correction (26 Oct 2026, GS phase 0, review A finding 9; evidence/gs_phase0_amendments.md): NIFTY quotes are
# age-bounded like the stock's, and R1 enters on a quote strictly after the one(s) that completed AR5.
# False reproduces the 26 Oct pilot behaviour.
CAUSAL_FIX = True
GROUPS = {"Financial Results": "results", "Outcome of Board Meeting": "results",
          "Bagging/Receiving of orders/contracts": "orders", "Press Release": "press release",
          "Analysts/Institutional Investor Meet/Con. Call Updates": "analyst meet"}


def group(category: str) -> str:
    c = " ".join(str(category).split())
    for k, v in GROUPS.items():
        if " ".join(k.split()).lower() in c.lower():
            return v
    return "other"


def load(day: str, data: Path = DATA) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = day.replace("-", "")
    con = sqlite3.connect(f"file:{data / f'study_news_{d}.db'}?mode=ro", uri=True)
    news = pd.read_sql_query("select seq_id, symbol, fno, disseminated, seen, category, text from news", con)
    con.close()
    con = sqlite3.connect(f"file:{data / f'study_quotes_{d}.db'}?mode=ro", uri=True)
    q = pd.read_sql_query("select ts, symbol, bid, ask from q where bid > 0 and ask >= bid and "
                          "(symbol like 'NSE_EQ:%' or symbol like 'NSE_FO:NIFTY%FUT')", con)
    con.close()
    news["t0"] = pd.to_datetime(news["disseminated"], format="%d-%b-%Y %H:%M:%S")
    news["seen_t"] = pd.to_datetime(news["seen"].str[:19])
    q["t"] = pd.to_datetime(q["ts"].str[:19])
    q["mid"] = (q["bid"] + q["ask"]) / 2
    q["sym"] = np.where(q["symbol"].str.startswith("NSE_EQ:"), q["symbol"].str[7:], "NIFTYFUT")
    return news, q.sort_values("t")


def at_or_after(s: pd.DataFrame, t) -> pd.Series | None:
    i = s["t"].searchsorted(t)
    return s.iloc[i] if i < len(s) else None


def at_or_before(s: pd.DataFrame, t) -> pd.Series | None:
    i = s["t"].searchsorted(t, side="right") - 1
    return s.iloc[i] if i >= 0 else None


def reactions(day: str, data: Path = DATA) -> pd.DataFrame:
    news, q = load(day, data)
    by = {k: g.reset_index(drop=True) for k, g in q.groupby("sym")}
    idx = by.get("NIFTYFUT")
    d0 = pd.Timestamp(day)
    out = []
    busy: dict = {}                                    # symbol -> exit time of its open R1 trade (one at a time)
    for e in news.sort_values("t0").itertuples():
        s = by.get(e.symbol)
        tm = e.t0.strftime("%H:%M:%S")
        if s is None or idx is None or e.t0.normalize() != d0 or not (OPEN <= tm <= LAST_EVENT):
            continue
        p0, i0 = at_or_before(s, e.t0), at_or_before(idx, e.t0)
        if p0 is None or i0 is None or (e.t0 - p0["t"]) > timedelta(minutes=3):
            continue
        if CAUSAL_FIX and (e.t0 - i0["t"]) > timedelta(minutes=3):   # the NIFTY base quote is age-bounded too
            continue
        row = {"day": day, "symbol": e.symbol, "fno_flag": e.fno, "t0": e.t0, "seen": e.seen_t,
               "lag_s": (e.seen_t - e.t0).total_seconds(), "category": e.category, "group": group(e.category)}
        for h in HORIZONS:
            t = e.t0 + timedelta(minutes=h)
            p, i = at_or_after(s, t), at_or_after(idx, t)
            ok = p is not None and i is not None and (p["t"] - t) <= timedelta(minutes=3) and p["t"].strftime("%H:%M:%S") <= "15:30:00"
            if CAUSAL_FIX:
                ok = ok and (i["t"] - t) <= timedelta(minutes=3)
            row[f"ar{h}"] = (p["mid"] / p0["mid"] - i["mid"] / i0["mid"]) if ok else np.nan
            if h == 5:
                sig_t = max(p["t"], i["t"]) if ok else None
        tr = rule_trade(s, e.t0, e.seen_t, row["ar5"], sig_t if CAUSAL_FIX else None)
        if tr["traded"] and e.symbol in busy and busy[e.symbol] > tr["entry_t"]:
            tr = {"traded": False, "skipped": "already in a trade"}
        elif tr["traded"]:
            busy[e.symbol] = tr["exit_t"]
        out.append(row | tr)
    return pd.DataFrame(out)


def rule_trade(s: pd.DataFrame, t0, seen, ar5, signal_t=None) -> dict:
    """R1: follow the first 5 minutes' abnormal move if it is >= 0.40% in size.
    With signal_t (the later of the two quotes that completed AR5; CAUSAL_FIX), the entry is the first stock quote
    strictly AFTER max(t0 + 5 min, seen, signal_t): the quote that completed the signal is never also the entry."""
    if not np.isfinite(ar5) or abs(ar5) < TRIGGER:
        return {"traded": False}
    side = 1 if ar5 > 0 else -1
    te = max(t0 + timedelta(minutes=WAIT), seen)
    if signal_t is not None:
        te = max(te, signal_t)
    tx = min(t0 + timedelta(minutes=HOLD), te.normalize() + pd.Timedelta(EXIT_BY))
    if te >= tx:
        return {"traded": False}
    a = at_or_after(s, te + timedelta(microseconds=1)) if signal_t is not None else at_or_after(s, te)
    b = at_or_before(s, tx)
    if a is None or b is None or b["t"] <= a["t"]:
        return {"traded": False}
    entry = a["ask"] if side > 0 else a["bid"]
    exit_ = b["bid"] if side > 0 else b["ask"]
    units = max(1, round(EQ_NOTIONAL / entry))
    fees = float(equity_intraday_fees(entry, exit_, side, units))
    net = side * (exit_ - entry) * units - fees
    return {"traded": True, "side": side, "entry_t": a["t"], "exit_t": b["t"], "entry": float(entry), "exit": float(exit_),
            "net_inr": float(net), "net_bp": float(net / (entry * units) * 1e4)}


def summary(r: pd.DataFrame) -> dict:
    out = {"events": int(len(r)), "by_group": {}}
    if r.empty:
        out["rule_trades"] = 0
        return out
    for g, x in r.groupby("group"):
        out["by_group"][g] = {"n": int(len(x)), **{f"mean_abs_ar{h}_bp": float(x[f"ar{h}"].abs().mean() * 1e4) for h in HORIZONS}}
    t = r[r.get("traded", pd.Series(False, index=r.index)).fillna(False).astype(bool)] if len(r) else r
    out["rule_trades"] = int(len(t))
    if len(t):
        out["rule_mean_net_bp"] = float(t["net_bp"].mean())
        out["rule_net_inr"] = float(t["net_inr"].sum())
    if len(r):
        out["median_seen_lag_s"] = float(r["lag_s"].median())
    return out


def main() -> None:
    r = pd.concat([reactions(d) for d in sys.argv[1:]], ignore_index=True)
    pd.set_option("display.width", 220)
    if len(r):
        cols = ["day", "symbol", "fno_flag", "t0", "lag_s", "group"] + [f"ar{h}" for h in HORIZONS] + \
               [c for c in ("traded", "side", "net_bp") if c in r]
        print(r[cols].to_string(index=False))
    print(summary(r))


if __name__ == "__main__":
    main()
