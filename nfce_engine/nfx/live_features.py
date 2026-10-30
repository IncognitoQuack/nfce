"""NFCE-X phase 1b: features that exist only from the live recorders (from 26 Oct 2026), so they have no 2022–26
history and are collected forward. Pure functions over the recorder tables:

* options (index chains, `study_chain_*.db` table `chain`): ATM IV, put-call skew, put/call OI ratio, IV change;
* order book (`study_quotes_*.db` table `q`, 5-level `depth` JSON): L1 imbalance, distance-weighted L2-5 imbalance
  (Gupta & Kumar 2025 form), spread in bp, depth;
* news (`study_news_*.db` table `news`): minutes since the stock's last filing, results flag, market-hours flag.

Every function takes rows up to the decision time `asof` and ignores anything later.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd


def _times(s: pd.Series, asof: pd.Timestamp, **kw) -> pd.Series:
    """Recorder times may be naive (IST wall clock, as the chain recorder writes them) or carry an offset."""
    t = pd.to_datetime(s, errors="coerce", **kw)
    if t.dt.tz is None and asof.tzinfo is not None:
        t = t.dt.tz_localize(asof.tzinfo)
    elif t.dt.tz is not None and asof.tzinfo is not None:
        t = t.dt.tz_convert(asof.tzinfo)
    return t


def option_features(chain: pd.DataFrame, asof: pd.Timestamp, underlying: str = "NIFTY") -> dict:
    """chain: rows of the `chain` table (ts, underlying, expiry, spot, strike, typ, iv, delta, oi, ...)."""
    chain = chain.reset_index(drop=True)
    t = _times(chain["ts"], asof, format="ISO8601")
    c = chain[(chain["underlying"] == underlying) & (t <= asof)]
    if c.empty:
        return {}
    ts_all = t[c.index]
    later = pd.to_datetime(c["expiry"]).dt.date > asof.date()    # never the expiring contract (0DTE IV is distorted)
    c, ts_all = c[later], ts_all[later]
    if c.empty:
        return {}
    last = c[ts_all == ts_all.max()]
    near = last[last["expiry"] == last["expiry"].min()]
    spot = float(near["spot"].iloc[0])
    atm_k = near.loc[(near["strike"] - spot).abs().idxmin(), "strike"]
    atm = near[near["strike"] == atm_k]
    iv_atm = float(atm["iv"].mean())
    calls, puts = near[near["typ"] == "CE"], near[near["typ"] == "PE"]

    def iv_at(df, target):
        df = df.dropna(subset=["delta", "iv"])
        return float(df.loc[(df["delta"] - target).abs().idxmin(), "iv"]) if len(df) else math.nan

    skew = iv_at(puts, -0.25) - iv_at(calls, 0.25)
    pcr = float(puts["oi"].sum() / calls["oi"].sum()) if calls["oi"].sum() > 0 else math.nan
    first = c[ts_all == ts_all.min()]
    first = first[first["expiry"] == first["expiry"].min()]
    k0 = first.loc[(first["strike"] - float(first["spot"].iloc[0])).abs().idxmin(), "strike"]
    iv_open = float(first[first["strike"] == k0]["iv"].mean())
    return {"opt_iv_atm": iv_atm, "opt_skew_25d": skew, "opt_pcr_oi": pcr, "opt_iv_chg_day": iv_atm - iv_open}


def book_features(depth_json: str, decay: float = 0.5) -> dict:
    """One quote's 5-level book. L2-5 imbalance weights level k by exp(-decay * (k - 1))."""
    try:
        d = json.loads(depth_json) if isinstance(depth_json, str) else depth_json
        buy, sell = d.get("buy") or [], d.get("sell") or []
    except (TypeError, ValueError):
        return {}
    if not buy or not sell or not buy[0].get("price") or not sell[0].get("price"):
        return {}
    bq = [float(x.get("quantity") or 0) for x in buy[:5]]
    aq = [float(x.get("quantity") or 0) for x in sell[:5]]
    b1, a1 = float(buy[0]["price"]), float(sell[0]["price"])
    mid = (b1 + a1) / 2
    imb1 = (bq[0] - aq[0]) / (bq[0] + aq[0]) if bq[0] + aq[0] > 0 else math.nan
    w = [math.exp(-decay * (k - 1)) for k in range(2, 6)]
    bw = sum(wi * q for wi, q in zip(w, bq[1:]))
    aw = sum(wi * q for wi, q in zip(w, aq[1:]))
    imb25 = (bw - aw) / (bw + aw) if bw + aw > 0 else math.nan
    return {"book_imb_l1": imb1, "book_imb_l2_5": imb25, "book_spread_bp": (a1 - b1) / mid * 1e4,
            "book_depth_ratio": sum(bq) / sum(aq) if sum(aq) > 0 else math.nan,
            "book_depth_rupees": (sum(bq) * b1 + sum(aq) * a1) / 2}


def news_features(news: pd.DataFrame, symbol: str, asof: pd.Timestamp) -> dict:
    """news: the `news` table. Uses the time each filing was disseminated (seen by NSE's feed), never later rows."""
    n = news[(news["symbol"] == symbol) & news["fno"].astype(bool)].copy()
    n["t"] = _times(n["disseminated"], asof, format="mixed", dayfirst=True)
    n = n[n["t"] <= asof]
    if n.empty:
        return {"news_mins_since": math.nan, "news_results": 0.0, "news_in_market_hours": 0.0, "news_count_day": 0.0}
    last = n.loc[n["t"].idxmax()]
    hm = last["t"].hour * 60 + last["t"].minute
    same_day = n[n["t"].dt.date == asof.date()]
    is_results = "result" in f"{last['category']} {last['text']}".lower()
    return {"news_mins_since": (asof - last["t"]).total_seconds() / 60, "news_results": float(is_results),
            "news_in_market_hours": float(555 <= hm <= 930), "news_count_day": float(len(same_day))}
