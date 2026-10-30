"""Study collector (22 Oct 2026, admin request): once a minute, record the full quote (last, volume, OI,
5-level depth) for every F&O stock and its front-month future, plus the NIFTY/SENSEX front futures.
Live-only data (bid/ask spreads cannot be downloaded later); candles can be pulled after the close.
Writes to its own database, never to the live nfce.db. Read-only use of Upstox (market quotes).

Times (26 Oct 2026, GS phase 0c; review A finding 3): `ts` is still the snapshot label (the loop start, as before, so
old readers keep working); every row also stores `req_ts` (its batch request was sent), `resp_ts` (that response was
received) and `exch_ts` (the quote's own exchange `timestamp` field, when Upstox gives one). All are timezone-aware.

usage: .venv/bin/python collect.py <out.db> [end HH:MM]   (run from nfce_bridge/)
"""
import datetime as dt, json, sqlite3, sys, time
import httpx

COLS = ("ts text, key text, symbol text, last real, volume real, oi real, bid real, bid_qty real, ask real, "
        "ask_qty real, depth text, ltt text, req_ts text, resp_ts text, exch_ts text")


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


def open_db(path):
    db = sqlite3.connect(path)
    db.execute(f"create table if not exists q ({COLS})")
    have = {r[1] for r in db.execute("pragma table_info(q)")}
    for c in ("req_ts", "resp_ts", "exch_ts"):                 # a database started by the old recorder
        if c not in have:
            db.execute(f"alter table q add column {c} text")
    db.execute("create index if not exists q_ts on q(ts)")
    return db


def rows_of(ts: str, batch: dict, req_ts: str, resp_ts: str) -> list[tuple]:
    out = []
    for name, v in batch.items():
        d = v.get("depth") or {}
        b = (d.get("buy") or [{}])[0]; a = (d.get("sell") or [{}])[0]
        out.append((ts, v.get("instrument_token"), name, v.get("last_price"), v.get("volume"), v.get("oi"),
                    b.get("price"), b.get("quantity"), a.get("price"), a.get("quantity"), json.dumps(d),
                    v.get("last_trade_time"), req_ts, resp_ts, v.get("timestamp")))
    return out


def poll(keys, headers, get=httpx.get) -> list[tuple[str, str, dict]]:
    """One request per batch of 450 keys: [(request sent, response received, data)]."""
    out = []
    for i in range(0, len(keys), 450):
        req = now_iso()
        r = get("https://api.upstox.com/v2/market-quote/quotes",
                params={"instrument_key": ",".join(keys[i:i + 450])}, headers=headers, timeout=20)
        resp = now_iso()
        r.raise_for_status()
        out.append((req, resp, r.json().get("data", {})))
    return out


def main() -> None:
    from bridge.config import Settings
    OUT, END = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "15:31")
    s = Settings.from_env()
    tok = json.load(open(s.token_file))
    tok = tok.get("access_token", tok) if isinstance(tok, dict) else tok
    H = {"Authorization": f"Bearer {tok}", "Accept": "application/json"}

    rows = json.load(open("data/instruments_NSE.json"))["rows"]
    today = dt.date.today()
    front = {}
    for r in rows:
        if r["instrument_type"] != "FUT" or r["underlying_type"] not in ("EQUITY", "INDEX"):
            continue
        exp = dt.datetime.fromtimestamp(r["expiry"] / 1000).date()
        if exp < today:
            continue
        u = r["underlying_symbol"]
        if u not in front or exp < front[u][0]:
            front[u] = (exp, r)
    keys = []
    for u, (exp, r) in front.items():
        if r["underlying_type"] == "EQUITY":
            keys += [r["underlying_key"], r["instrument_key"]]
        elif u in ("NIFTY",):
            keys.append(r["instrument_key"])
    keys = sorted(set(keys))
    print(f"{len(front)} underlyings, {len(keys)} instrument keys", flush=True)

    db = open_db(OUT)
    while dt.datetime.now().strftime("%H:%M") < END:
        t0 = time.time()
        ts = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            recs = []
            for req, resp, data in poll(keys, H):
                recs += rows_of(ts, data, req, resp)
            db.executemany(f"insert into q values ({','.join('?' * 15)})", recs)
            db.commit()
            print(f"{ts} {len(recs)} quotes", flush=True)
        except Exception as e:
            print(f"{ts} error {e!r}", flush=True)
        time.sleep(max(1, 60 - (time.time() - t0)))
    print("done", flush=True)


if __name__ == "__main__":
    main()
