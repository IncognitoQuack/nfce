"""Option-chain collector (26 Oct 2026, owner: use the live market for testing): once a minute, record the whole
option chain (ltp, bid/ask with size, volume, OI, IV, greeks, every strike) for NIFTY (two nearest expiries),
BANKNIFTY and SENSEX (nearest). Option bid/ask history cannot be downloaded later, and it is what an options
strategy built on the range model needs. Writes to its own database, never to the live nfce.db. Read-only use of
Upstox (4 requests a minute).

Times (26 Oct 2026, GS phase 0c; review A finding 3): `ts` is still the snapshot label (the loop start, as before, so
old readers keep working); every row also stores `req_ts` and `resp_ts`: when ITS chain request (one per underlying
and expiry) was sent and its response received, timezone-aware. The requests are sequential, so the roots in one
snapshot are NOT simultaneous; legs of one structure come from one response. The chain API gives no exchange time,
so `exch_ts` stays empty.

usage: .venv/bin/python ops/collect_chain.py <out.db> [end HH:MM]   (run from nfce_bridge/)
"""
import datetime as dt, json, sqlite3, sys, time
import httpx

API = "https://api.upstox.com/v2/option"
UNDERLYINGS = (("NIFTY", "NSE_INDEX|Nifty 50", 2), ("BANKNIFTY", "NSE_INDEX|Nifty Bank", 1),
               ("SENSEX", "BSE_INDEX|SENSEX", 1))
COLS = ("ts text, underlying text, expiry text, spot real, strike real, typ text, key text, ltp real, bid real, "
        "ask real, bid_qty real, ask_qty real, volume real, oi real, iv real, delta real, gamma real, theta real, "
        "vega real, req_ts text, resp_ts text, exch_ts text")


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


def open_db(path):
    db = sqlite3.connect(path)
    db.execute(f"create table if not exists chain ({COLS})")
    have = {r[1] for r in db.execute("pragma table_info(chain)")}
    for c in ("req_ts", "resp_ts", "exch_ts"):                 # a database started by the old recorder
        if c not in have:
            db.execute(f"alter table chain add column {c} text")
    db.execute("create index if not exists chain_i on chain (underlying, expiry, strike, typ, ts)")
    return db


def get(path, params, headers, http_get=httpx.get):
    """(request sent, response received, data) of the last attempt; 429s are retried with a growing wait."""
    for attempt in range(4):
        req = now_iso()
        r = http_get(f"{API}/{path}", headers=headers, params=params, timeout=30)
        resp = now_iso()
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1)); continue
        r.raise_for_status()
        return req, resp, r.json().get("data") or []
    return None, None, []


def rows_of(ts: str, name: str, exp: str, data: list, req_ts: str, resp_ts: str) -> list[tuple]:
    rows = []
    for x in data:
        for typ, side in (("CE", "call_options"), ("PE", "put_options")):
            o = x.get(side) or {}
            m, g = o.get("market_data") or {}, o.get("option_greeks") or {}
            rows.append((ts, name, exp, x.get("underlying_spot_price"), x.get("strike_price"), typ,
                         o.get("instrument_key"), m.get("ltp"), m.get("bid_price"), m.get("ask_price"),
                         m.get("bid_qty"), m.get("ask_qty"), m.get("volume"), m.get("oi"), g.get("iv"),
                         g.get("delta"), g.get("gamma"), g.get("theta"), g.get("vega"), req_ts, resp_ts, None))
    return rows


def main() -> None:
    from bridge.config import Settings
    OUT, END = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "15:31")
    s = Settings.from_env()
    tok = json.load(open(s.token_file))
    tok = tok.get("access_token", tok) if isinstance(tok, dict) else tok
    H = {"Authorization": f"Bearer {tok}", "Accept": "application/json"}

    today = dt.date.today().isoformat()
    targets = []
    for name, key, n in UNDERLYINGS:
        try:
            exps = sorted({x["expiry"] for x in get("contract", {"instrument_key": key}, H)[2]} - set())
        except Exception as e:
            print("no expiries", name, repr(e)[:120], flush=True); continue
        targets += [(name, key, e) for e in [x for x in exps if x >= today][:n]]
    print("recording", targets, flush=True)

    db = open_db(OUT)
    while dt.datetime.now().strftime("%H:%M") < END:
        t0 = time.time()
        ts = dt.datetime.now().isoformat(timespec="seconds")
        rows = []
        for name, key, exp in targets:
            try:
                req, resp, data = get("chain", {"instrument_key": key, "expiry_date": exp}, H)
            except Exception as e:
                print(ts, "fail", name, exp, repr(e)[:120], flush=True); continue
            rows += rows_of(ts, name, exp, data, req, resp)
        with db:
            db.executemany("insert into chain values (" + ",".join("?" * 22) + ")", rows)
        print(ts, len(rows), "rows", flush=True)
        time.sleep(max(1.0, 60 - (time.time() - t0)))
    print("done", flush=True)


if __name__ == "__main__":
    main()
