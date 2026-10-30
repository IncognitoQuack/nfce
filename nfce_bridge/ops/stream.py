"""Shadow streaming recorder (27 Oct 2026): Upstox Market Data Feed V3 over WebSocket, tick by tick, into its own
database. It runs next to the bridge's minute polling and changes nothing live; the bridge moves to streaming only after
this has been proven in a market session.

    PYTHONPATH=. .venv/bin/python ops/stream.py data/stream_YYYYMMDD.db [end HH:MM] [--mode full]

Flow (Upstox V3 docs): GET /v3/feed/market-data-feed/authorize → a one-time wss:// URL → send the subscription as a
BINARY JSON frame → receive binary protobuf FeedResponse frames (bridge/feed_proto.py, built from Upstox's official
.proto). Each reconnect authorizes again (the URL is single-use). Uses one of the two connections Upstox allows.
Writes ticks (last trade, 5-level book, volume, OI, closing-auction fields) and market-status messages, with the time
each frame was received, so latency against the exchange's last-trade time can be measured.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import sqlite3
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bridge import feed_proto  # noqa: E402

AUTH_URL = "https://api.upstox.com/v3/feed/market-data-feed/authorize"
INDEX_KEYS = ["NSE_INDEX|Nifty 50", "NSE_INDEX|Nifty Bank", "NSE_INDEX|India VIX", "BSE_INDEX|SENSEX"]
TICK_COLS = ("recv_ts text, key text, mode text, ltp real, ltt integer, ltq integer, cp real, bid1 real, bidq1 integer, "
             "ask1 real, askq1 integer, depth text, vtt integer, oi real, atp real, tbq real, tsq real, iep real, "
             "cas integer, iv real, delta real, current_ts integer, gamma real, vega real, theta real")
INFO_COLS = "recv_ts text, kind text, body text"


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


def open_db(path) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=30)
    db.execute("pragma journal_mode=wal")      # readers (desk, scorers) never block the tick writer
    db.execute("pragma synchronous=normal")
    db.execute(f"create table if not exists tick ({TICK_COLS})")
    have = {r[1] for r in db.execute("pragma table_info(tick)")}
    for c in ("gamma", "vega", "theta"):                    # a database started before the Greeks were stored
        if c not in have:
            db.execute(f"alter table tick add column {c} real")
    db.execute(f"create table if not exists info ({INFO_COLS})")
    db.execute("create index if not exists tick_key on tick(key, recv_ts)")
    return db


def subscription(keys: list[str], mode: str = "full", method: str = "sub") -> bytes:
    """The V3 request, sent as a binary frame."""
    return json.dumps({"guid": uuid.uuid4().hex[:20], "method": method,
                       "data": {"mode": mode, "instrumentKeys": keys}}).encode()


def rows_of(resp, recv_ts: str) -> tuple[list[tuple], list[tuple]]:
    """A decoded FeedResponse → (tick rows, info rows). Pure; covers the three feed shapes of the V3 proto."""
    ticks, info = [], []
    if resp.HasField("marketInfo"):
        mi = resp.marketInfo
        info.append((recv_ts, "market_info", json.dumps({
            "segment": {k: int(v) for k, v in mi.segmentStatus.items()},
            "cas": {k: {"status": v.status, "t": v.updatedTime} for k, v in mi.casMarketStatus.items()},
            "pre_open": {k: {"status": v.status, "t": v.updatedTime} for k, v in mi.preOpenSessionStatus.items()}})))
    for key, f in resp.feeds.items():
        kind = f.WhichOneof("FeedUnion")
        ltpc = depth = None
        vtt = oi = atp = tbq = tsq = iep = iv = delta = gamma = vega = theta = None
        cas = None
        if kind == "ltpc":
            ltpc = f.ltpc
        elif kind == "fullFeed":
            ff = f.fullFeed
            which = ff.WhichOneof("FullFeedUnion")
            if which == "marketFF":
                m = ff.marketFF
                ltpc = m.ltpc
                depth = [(q.bidP, q.bidQ, q.askP, q.askQ) for q in m.marketLevel.bidAskQuote]
                vtt, oi, atp, tbq, tsq, iv = m.vtt, m.oi, m.atp, m.tbq, m.tsq, m.iv
                iep, cas = (m.iep or None), int(m.casEligible)
                if m.HasField("optionGreeks"):
                    og = m.optionGreeks
                    delta, gamma, vega, theta = og.delta, og.gamma, og.vega, og.theta
            elif which == "indexFF":
                ltpc = ff.indexFF.ltpc
        elif kind == "firstLevelWithGreeks":
            g = f.firstLevelWithGreeks
            ltpc = g.ltpc
            q = g.firstDepth
            depth = [(q.bidP, q.bidQ, q.askP, q.askQ)]
            vtt, oi, iv = g.vtt, g.oi, g.iv
            if g.HasField("optionGreeks"):
                og = g.optionGreeks
                delta, gamma, vega, theta = og.delta, og.gamma, og.vega, og.theta
        if ltpc is None:
            continue
        b1 = depth[0] if depth else (None, None, None, None)
        ticks.append((recv_ts, key, kind, ltpc.ltp, ltpc.ltt, ltpc.ltq, ltpc.cp, b1[0], b1[1], b1[2], b1[3],
                      json.dumps(depth) if depth else None, vtt, oi, atp, tbq, tsq, iep, cas, iv, delta, resp.currentTs,
                      gamma, vega, theta))
    return ticks, info


def instrument_keys(instruments: Path, today: dt.date) -> list[str]:
    """Each F&O stock's equity key and front-month future, the NIFTY front future, and four indices (same universe as
    ops/collect.py, plus the index feeds)."""
    rows = json.loads(instruments.read_text())["rows"]
    front = {}
    for r in rows:
        if r.get("instrument_type") != "FUT" or r.get("underlying_type") not in ("EQUITY", "INDEX"):
            continue
        exp = dt.datetime.fromtimestamp(r["expiry"] / 1000).date()
        if exp < today:
            continue
        u = r["underlying_symbol"]
        if u not in front or exp < front[u][0]:
            front[u] = (exp, r)
    keys = list(INDEX_KEYS)
    for u, (exp, r) in front.items():
        if r["underlying_type"] == "EQUITY":
            keys += [r["underlying_key"], r["instrument_key"]]
        elif u == "NIFTY":
            keys.append(r["instrument_key"])
    return sorted(set(keys))


def book_keys(nfce_db: Path) -> set[str]:
    """Contracts and underlyings of every OPEN paper-account position (read-only), so the stream can follow the book:
    the accounts hold option contracts that are not in the fixed universe, and the desk marks and risks them from here."""
    try:
        con = sqlite3.connect(f"file:{nfce_db}?mode=ro", uri=True, timeout=2)
        rows = con.execute("SELECT state FROM account_positions WHERE status='OPEN'").fetchall()
        con.close()
    except sqlite3.Error:
        return set()
    out = set()
    for (st,) in rows:
        try:
            s = json.loads(st)
        except (TypeError, ValueError):
            continue
        out |= {k for k in (s.get("key"), s.get("under_key")) if k}
    return out


def authorize(token: str, get=None) -> str:
    import httpx
    get = get or httpx.get
    r = get(AUTH_URL, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}, timeout=15,
            follow_redirects=False)
    r.raise_for_status()
    return r.json()["data"]["authorized_redirect_uri"]


async def run(out: str, end: str, mode: str, keys: list[str], token: str, max_minutes: float | None = None,
              follow: Path | None = None) -> dict:
    import websockets
    db = open_db(out)
    keys = list(keys)
    stats = {"frames": 0, "ticks": 0, "keys": set(), "reconnects": -1, "errors": 0, "lat_ms": []}
    t_stop = time.time() + 60 * max_minutes if max_minutes else None
    backoff = 1.0
    buf_t, buf_i = [], []

    def flush():
        nonlocal buf_t, buf_i
        if buf_t or buf_i:
            db.executemany(f"insert into tick values ({','.join('?' * 25)})", buf_t)
            db.executemany("insert into info values (?,?,?)", buf_i)
            db.commit()
        buf_t, buf_i = [], []

    while dt.datetime.now().strftime("%H:%M") < end and (t_stop is None or time.time() < t_stop):
        stats["reconnects"] += 1
        try:
            url = authorize(token)
            async with websockets.connect(url, max_size=None, open_timeout=15) as ws:
                await ws.send(subscription(keys, mode))
                backoff, last_flush = 1.0, time.time()
                last_follow = 0.0
                while dt.datetime.now().strftime("%H:%M") < end and (t_stop is None or time.time() < t_stop):
                    try:
                        frame = await asyncio.wait_for(ws.recv(), timeout=5)
                    except asyncio.TimeoutError:
                        frame = None
                    if isinstance(frame, (bytes, bytearray)):
                        recv = now_iso()
                        try:
                            ticks, info = rows_of(feed_proto.decode(bytes(frame)), recv)
                        except Exception as exc:       # one bad frame: log and skip it, keep the connection
                            stats["errors"] += 1
                            buf_i.append((recv, "bad_frame", f"{exc!r}"[:300] + f" len={len(frame)}"))
                            continue
                        stats["frames"] += 1
                        stats["ticks"] += len(ticks)
                        now_ms = time.time() * 1000
                        for t in ticks:
                            stats["keys"].add(t[1])
                            if t[4] and len(stats["lat_ms"]) < 200_000:
                                stats["lat_ms"].append(now_ms - t[4])
                        buf_t += ticks
                        buf_i += info
                    if follow is not None and time.time() - last_follow >= 30:     # follow the paper book
                        last_follow = time.time()
                        new = sorted(book_keys(follow) - set(keys))
                        if new:
                            await ws.send(subscription(new, mode))
                            keys += new
                            buf_i.append((now_iso(), "follow", json.dumps(new)))
                    if time.time() - last_flush >= 1 and (buf_t or buf_i):
                        flush()
                        last_flush = time.time()
                    if stats["frames"] and stats["frames"] % 500 == 0:
                        print(f"{now_iso()} frames {stats['frames']} ticks {stats['ticks']} keys {len(stats['keys'])}",
                              flush=True)
                flush()
        except Exception as exc:                       # drop or auth error: keep what was buffered, back off, re-authorize
            stats["errors"] += 1
            try:
                flush()
            except sqlite3.Error:
                buf_t, buf_i = [], []
            db.execute("insert into info values (?,?,?)", (now_iso(), "error", repr(exc)[:500]))
            db.commit()
            print(f"{now_iso()} error {exc!r}; reconnecting in {backoff:.0f}s", flush=True)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
    lat = sorted(stats["lat_ms"])
    summary = {"frames": stats["frames"], "ticks": stats["ticks"], "keys_seen": len(stats["keys"]),
               "subscribed": len(keys), "reconnects": stats["reconnects"], "errors": stats["errors"],
               "latency_ms_p50": lat[len(lat) // 2] if lat else None,
               "latency_ms_p95": lat[int(len(lat) * 0.95)] if lat else None}
    db.execute("insert into info values (?,?,?)", (now_iso(), "summary", json.dumps(summary)))
    db.commit()
    return summary


def main() -> None:
    import argparse
    from bridge.config import Settings
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("end", nargs="?", default="15:40", help="HH:MM to stop (default 15:40)")
    ap.add_argument("--mode", default="full", choices=("ltpc", "full", "option_greeks", "full_d30"))
    ap.add_argument("--minutes", type=float, help="stop after this many minutes (connection tests)")
    x = ap.parse_args()
    out, end, mode, minutes = x.out, x.end, x.mode, x.minutes
    s = Settings.from_env()
    tok = json.loads(Path(s.token_file).read_text())
    tok = tok.get("access_token", tok) if isinstance(tok, dict) else tok
    keys = instrument_keys(ROOT / "data" / "instruments_NSE.json", dt.date.today())
    print(f"{now_iso()} subscribing {len(keys)} keys, mode {mode}, until {end}", flush=True)
    follow = ROOT / "data" / "nfce.db"
    print(json.dumps(asyncio.run(run(out, end, mode, keys, tok, minutes, follow))), flush=True)


if __name__ == "__main__":
    main()
