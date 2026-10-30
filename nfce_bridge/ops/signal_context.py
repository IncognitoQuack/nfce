"""Shadow signal context (28 Oct 2026): for every signal of a day, record what the market looked like at that moment.
Read-only on every live source; writes only its own data/signal_context.db. It changes NO trading rule.

    PYTHONPATH=. .venv/bin/python ops/signal_context.py [YYYY-MM-DD]      (after the close; the evening runbook runs it)

Per signal (every non-scanner paper trade and every scanner pick), as of the signal time t:
  stock    : day change vs previous close, quoted spread (bp), L1 and L2-5 book imbalance (stream ticks)
  market   : NIFTY day change, India VIX and its day change, breadth (share of F&O stocks up on the day)
  options  : NIFTY ATM IV (next non-expiring contract), 25-delta skew, put/call OI ratio (recorded chain)
  news     : F&O filings for the stock before t (count today, minutes since the last, results flag), plus the
             morning brief's overnight view (categories RESULTS / RESULTS DUE / MAJOR; profit and revenue growth YoY)
  calendar : results board meeting today (results_calendar.csv)
  alignment: does the book, the market and the breadth point the same way as the signal?
  regime   : bridge/regime.py labels (calm / normal / stressed; trend up / trend down / mixed) and VIX's 1-year percentile
  sector   : from the OPTIONAL ~/Downloads/nfce_data/sector_map.csv (columns symbol,sector): the stock's sector, the
             sector's move at t (equal-weight day change of its sector peers in the stream) and whether it agrees
             with the signal. Without the file these stay empty (test-ready: add the map, nothing else changes).
Outcomes are deliberately NOT stored here: a later locked protocol joins them by `sid`, so nobody picks a rule after
seeing which context "worked".
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "nfce_engine"))
DATA = ROOT / "data"
OUT = DATA / "signal_context.db"
RESULTS = Path.home() / "Downloads" / "nfce_data" / "results_calendar.csv"
SECTOR_MAP = Path.home() / "Downloads" / "nfce_data" / "sector_map.csv"   # optional: symbol,sector
NIFTY, VIX = "NSE_INDEX|Nifty 50", "NSE_INDEX|India VIX"
COLS = ("sid text primary key, day text, t text, book text, symbol text, side integer, entry real, "
        "stock_chg_pct real, spread_bp real, imb_l1 real, imb_l2_5 real, nifty_chg_pct real, vix real, vix_chg_pct real, "
        "breadth real, opt_iv_atm real, opt_skew_25d real, opt_pcr_oi real, news_count_day real, news_mins_since real, "
        "news_results real, results_today integer, book_aligned integer, market_aligned integer, breadth_aligned integer, "
        "sector text, brief_cats text, results_pat_yoy real, results_rev_yoy real, regime_vol text, regime_trend text, vix_pct real, sector_chg_pct real, sector_aligned integer, built_at text")


def ro(p: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)


def equity_keys() -> dict:
    rows = json.loads((DATA / "instruments_NSE.json").read_text())["rows"]
    return {r["underlying_symbol"]: r["underlying_key"] for r in rows if r.get("underlying_type") == "EQUITY"}


def signals(con: sqlite3.Connection, day: str) -> list[dict]:
    nxt = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    out = []
    for i, book, opened, sym, side, entry, sid in con.execute(
            "SELECT id, book, opened, underlying, side, entry, sid FROM paper_trades WHERE opened >= ? AND opened < ? "
            "ORDER BY opened", (day, nxt)):
        out.append({"sid": sid or f"{book}-{i}", "book": book, "t": opened, "symbol": sym, "side": int(side or 0),
                    "entry": entry})
    return out


def tick_at(con: sqlite3.Connection, key: str, t: str) -> dict | None:
    r = con.execute("SELECT ltp, cp, bid1, ask1, depth FROM tick WHERE key=? AND recv_ts <= ? ORDER BY recv_ts DESC "
                    "LIMIT 1", (key, t)).fetchone()
    return None if r is None else {"ltp": r[0], "cp": r[1], "bid": r[2], "ask": r[3], "depth": r[4]}


def sector_map(path: Path = SECTOR_MAP) -> dict:
    if not path.exists():
        return {}
    m = pd.read_csv(path, dtype=str, keep_default_na=False)          # a blank sector stays "", never "nan"
    return {a.strip(): b.strip() for a, b in zip(m["symbol"], m["sector"]) if a.strip() and b.strip()}


def sector_chg_at(con: sqlite3.Connection, t: str, peer_keys: list[str]) -> float | None:
    """Equal-weight day change (%) of a sector's stocks as of t, from each peer's newest tick."""
    if not peer_keys:
        return None
    q = (f"SELECT ltp, cp FROM tick WHERE rowid IN (SELECT max(rowid) FROM tick WHERE key IN "
         f"({','.join('?' * len(peer_keys))}) AND recv_ts <= ? GROUP BY key)")
    ch = [(a / b - 1) * 100 for a, b in con.execute(q, [*peer_keys, t]) if a and b]
    return sum(ch) / len(ch) if ch else None


def breadth_at(con: sqlite3.Connection, t: str) -> float | None:
    rows = con.execute("SELECT ltp, cp FROM tick WHERE rowid IN (SELECT max(rowid) FROM tick WHERE key LIKE 'NSE_EQ|%' "
                       "AND recv_ts <= ? GROUP BY key)", (t,)).fetchall()
    ok = [(a, b) for a, b in rows if a and b]
    return sum(a > b for a, b in ok) / len(ok) if ok else None


def _chg(x: dict | None) -> float | None:
    return (x["ltp"] / x["cp"] - 1) * 100 if x and x.get("ltp") and x.get("cp") else None


def _sign(v) -> int | None:
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else (1 if v > 0 else -1 if v < 0 else 0)


def context(sig: dict, stream: sqlite3.Connection | None, chain: pd.DataFrame | None, news: pd.DataFrame | None,
            results_today: set, keys: dict, brief: dict | None = None, sectors: dict | None = None) -> dict:
    from nfx import live_features as lf
    t = sig["t"]
    asof = pd.Timestamp(t)
    row = {k: None for k in ("stock_chg_pct", "spread_bp", "imb_l1", "imb_l2_5", "nifty_chg_pct", "vix", "vix_chg_pct",
                             "breadth", "opt_iv_atm", "opt_skew_25d", "opt_pcr_oi", "news_count_day", "news_mins_since",
                             "news_results", "book_aligned", "market_aligned", "breadth_aligned")}
    row |= {"sid": sig["sid"], "day": t[:10], "t": t, "book": sig["book"], "symbol": sig["symbol"], "side": sig["side"],
            "entry": sig["entry"], "results_today": int(sig["symbol"] in results_today), "sector": None,
            "sector_chg_pct": None, "sector_aligned": None}
    sectors = sectors or {}
    row["sector"] = sectors.get(sig["symbol"])
    b = (brief or {}).get(sig["symbol"])
    row["brief_cats"] = ",".join(b.get("cats") or []) if b else None
    res_ = (b or {}).get("results") or {}
    row["results_pat_yoy"], row["results_rev_yoy"] = res_.get("pat_yoy"), res_.get("rev_yoy")
    if stream is not None:
        st = tick_at(stream, keys.get(sig["symbol"], ""), t)
        if st:
            row["stock_chg_pct"] = _chg(st)
            if st["bid"] and st["ask"]:
                row["spread_bp"] = (st["ask"] - st["bid"]) / ((st["ask"] + st["bid"]) / 2) * 1e4
            if st["depth"]:
                lv = json.loads(st["depth"])
                b = lf.book_features(json.dumps({"buy": [{"price": x[0], "quantity": x[1]} for x in lv],
                                                 "sell": [{"price": x[2], "quantity": x[3]} for x in lv]}))
                row["imb_l1"], row["imb_l2_5"] = b.get("book_imb_l1"), b.get("book_imb_l2_5")
        row["nifty_chg_pct"] = _chg(tick_at(stream, NIFTY, t))
        v = tick_at(stream, VIX, t)
        if v:
            row["vix"], row["vix_chg_pct"] = v["ltp"], _chg(v)
        row["breadth"] = breadth_at(stream, t)
        if row["sector"]:
            peers = [keys[sym] for sym, sec in sectors.items() if sec == row["sector"] and sym in keys]
            row["sector_chg_pct"] = sector_chg_at(stream, t, peers)
    if chain is not None and len(chain):
        o = lf.option_features(chain, asof)
        row["opt_iv_atm"], row["opt_skew_25d"], row["opt_pcr_oi"] = (o.get("opt_iv_atm"), o.get("opt_skew_25d"),
                                                                     o.get("opt_pcr_oi"))
    if news is not None and len(news):
        nf = lf.news_features(news, sig["symbol"], asof)
        row["news_count_day"], row["news_mins_since"], row["news_results"] = (nf["news_count_day"],
                                                                              nf["news_mins_since"], nf["news_results"])
    from bridge import regime
    rg = regime.classify(row["vix"], row["vix_chg_pct"], row["nifty_chg_pct"], row["breadth"])
    row["regime_vol"], row["regime_trend"], row["vix_pct"] = rg["vol"], rg["trend"], rg["vix_pct"]
    s = sig["side"]
    for name, val in (("book_aligned", row["imb_l1"]), ("market_aligned", row["nifty_chg_pct"]),
                      ("sector_aligned", row["sector_chg_pct"]),
                      ("breadth_aligned", None if row["breadth"] is None else row["breadth"] - 0.5)):
        sg = _sign(val)
        row[name] = None if sg is None or not s else int(sg == s)
    return row


def build(day: str, data: Path = DATA, out: Path = OUT) -> list[dict]:
    d8 = day.replace("-", "")
    con = ro(data / "nfce.db")
    try:
        sigs = signals(con, day)
    finally:
        con.close()
    stream = ro(data / f"stream_{d8}.db") if (data / f"stream_{d8}.db").exists() else None
    chain = news = None
    if (data / f"study_chain_{d8}.db").exists():
        c = ro(data / f"study_chain_{d8}.db")
        chain = pd.read_sql_query("SELECT ts, underlying, expiry, spot, strike, typ, iv, delta, oi FROM chain "
                                  "WHERE underlying='NIFTY'", c)
        c.close()
    if (data / f"study_news_{d8}.db").exists():
        c = ro(data / f"study_news_{d8}.db")
        news = pd.read_sql_query("SELECT * FROM news", c)
        c.close()
    res = set()
    if RESULTS.exists():
        rc = pd.read_csv(RESULTS)
        res = set(rc[(rc["date"] == day) & (rc["results"] == 1)]["symbol"])
    keys = equity_keys() if (data / "instruments_NSE.json").exists() else {}
    wf = data / "news" / f"watch_{d8}.json"
    brief = {x["symbol"]: x for x in json.loads(wf.read_text())} if wf.exists() else {}
    sectors = sector_map()
    rows = [context(s, stream, chain, news, res, keys, brief, sectors) for s in sigs]
    if stream is not None:
        stream.close()
    db = sqlite3.connect(out)
    db.execute(f"CREATE TABLE IF NOT EXISTS ctx ({COLS})")
    have = {r[1] for r in db.execute("PRAGMA table_info(ctx)")}
    for c in COLS.split(", "):                          # a database made by an earlier version gains new columns
        name, typ = c.split()[0], c.split()[1]
        if name not in have:
            db.execute(f"ALTER TABLE ctx ADD COLUMN {name} {typ}")
    built = datetime.now().isoformat(timespec="seconds")
    cols = [c.split()[0] for c in COLS.split(", ")]
    for r in rows:
        r["built_at"] = built
        db.execute(f"INSERT OR REPLACE INTO ctx ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                   [r.get(c) for c in cols])
    db.commit()
    db.close()
    return rows


def summary(rows: list[dict]) -> dict:
    """Coverage and alignment counts only (no outcomes)."""
    n = len(rows)
    have = lambda k: sum(r.get(k) is not None for r in rows)  # noqa: E731
    agree = lambda k: sum(r.get(k) == 1 for r in rows)  # noqa: E731
    return {"signals": n, "with_stream": have("stock_chg_pct"), "with_options": have("opt_iv_atm"),
            "with_news_feed": have("news_count_day"), "results_today": sum(r["results_today"] for r in rows),
            "in_morning_brief": have("brief_cats"), "with_results_numbers": have("results_pat_yoy"),
            "book_aligned": f"{agree('book_aligned')}/{have('book_aligned')}",
            "market_aligned": f"{agree('market_aligned')}/{have('market_aligned')}",
            "breadth_aligned": f"{agree('breadth_aligned')}/{have('breadth_aligned')}",
            "regimes": {f"{r.get('regime_vol') or '?'} · {r.get('regime_trend') or '?'}": sum(
                1 for x in rows if (x.get('regime_vol'), x.get('regime_trend')) == (r.get('regime_vol'), r.get('regime_trend')))
                for r in rows},
            "sector": (f"{have('sector')} with a sector, aligned {agree('sector_aligned')}/{have('sector_aligned')}"
                       if have("sector") else "no sector map yet (add ~/Downloads/nfce_data/sector_map.csv: symbol,sector)")}


if __name__ == "__main__":
    day = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    print(json.dumps(summary(build(day)), indent=1))
