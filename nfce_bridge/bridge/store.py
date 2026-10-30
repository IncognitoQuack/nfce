"""SQLite storage: durable signal inbox, chain snapshots, quotes, signals, events, key-value state."""
from __future__ import annotations

import json
import math
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .analytics import Summary
from .providers import IST

SCHEMA = """
CREATE TABLE IF NOT EXISTS inbox (
    id INTEGER PRIMARY KEY, received TEXT NOT NULL, source TEXT, sid TEXT, raw TEXT,
    status TEXT NOT NULL DEFAULT 'NEW', note TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS ux_inbox_sid ON inbox(sid) WHERE sid IS NOT NULL;
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, session TEXT, underlying TEXT NOT NULL, expiry TEXT, spot REAL,
    atm_strike REAL, pcr_oi REAL, put_doi REAL, call_doi REAL, flow TEXT, max_call_oi_strike REAL,
    max_put_oi_strike REAL, max_pain REAL, atm_iv REAL, synth_forward REAL);
CREATE INDEX IF NOT EXISTS ix_snap ON snapshots(underlying, ts);
CREATE TABLE IF NOT EXISTS quotes (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, key TEXT, last REAL, bid REAL, ask REAL, ltt TEXT);
CREATE INDEX IF NOT EXISTS ix_quotes ON quotes(key, ts);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, source TEXT, sid TEXT, raw TEXT, symbol TEXT, side TEXT,
    entry REAL, sl REAL, t1 REAL, score REAL, grade_in TEXT, action TEXT, grade_out TEXT, flow TEXT,
    basis REAL, delay_s REAL, reasons TEXT, snapshot_id INTEGER);
CREATE TABLE IF NOT EXISTS option_quotes (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, session TEXT, snap_id INTEGER, underlying TEXT, expiry TEXT,
    strike REAL, type TEXT, key TEXT, ltp REAL, bid REAL, ask REAL, oi REAL, iv REAL);
CREATE INDEX IF NOT EXISTS ix_optq ON option_quotes(underlying, expiry, strike, type, ts);
CREATE TABLE IF NOT EXISTS signal_evidence (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, sid TEXT, trust TEXT, cell_key TEXT, cost_share REAL, card TEXT);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, source TEXT, raw TEXT);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS sent_messages (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, ok INTEGER, text TEXT);
CREATE TABLE IF NOT EXISTS range_forecasts (
    root TEXT NOT NULL, bar_close TEXT NOT NULL, model TEXT NOT NULL, ts TEXT, price REAL, q10 REAL, q50 REAL, q90 REAL,
    realized REAL, PRIMARY KEY (root, bar_close, model));
CREATE TABLE IF NOT EXISTS contracts (
    key TEXT NOT NULL, root TEXT NOT NULL, expiry TEXT, lot_size INTEGER, day TEXT NOT NULL, PRIMARY KEY (key, day));
"""


def _clean(x):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else x


def session_of(ts_iso: str) -> str:
    return datetime.fromisoformat(ts_iso).astimezone(IST).date().isoformat()


class Store:
    def __init__(self, path: Path):
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL") if str(path) != ":memory:" else None
        self.db.executescript(SCHEMA)
        self._lock = threading.RLock()

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # ---- durable inbox (TradingView payloads are written here BEFORE the webhook answers) ----
    def inbox_add(self, source: str, raw: dict, sid: str | None) -> tuple[int | None, bool]:
        """Returns (inbox id, is_duplicate)."""
        with self._lock, self.db:
            try:
                cur = self.db.execute("INSERT INTO inbox (received, source, sid, raw) VALUES (?,?,?,?)",
                                      (self.now(), source, sid or None, json.dumps(raw)[:20000]))
                return cur.lastrowid, False
            except sqlite3.IntegrityError:
                return None, True

    def inbox_done(self, inbox_id: int, status: str, note: str = "") -> None:
        with self._lock, self.db:
            self.db.execute("UPDATE inbox SET status=?, note=? WHERE id=?", (status, note[:500], inbox_id))

    def inbox_pending(self) -> list[tuple[int, str, str, str]]:
        with self._lock:
            return self.db.execute("SELECT id, source, raw, received FROM inbox WHERE status='NEW' ORDER BY id").fetchall()

    # ---- key-value state that must survive restarts (Telegram offset, daily-report marker, risk state) ----
    def kv_get(self, k: str, default=None):
        with self._lock:
            row = self.db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return json.loads(row[0]) if row else default

    def kv_set(self, k: str, v) -> None:
        with self._lock, self.db:
            self.db.execute("INSERT INTO kv (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                            (k, json.dumps(v)))

    # ---- market data ----
    def add_snapshot(self, s: Summary) -> int:
        with self._lock, self.db:
            cur = self.db.execute(
                "INSERT INTO snapshots (ts, session, underlying, expiry, spot, atm_strike, pcr_oi, put_doi, call_doi,"
                " flow, max_call_oi_strike, max_put_oi_strike, max_pain, atm_iv, synth_forward)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (s.fetched_at, session_of(s.fetched_at), s.underlying_key, s.expiry, s.spot, s.atm_strike,
                 _clean(s.pcr_oi), _clean(s.put_doi), _clean(s.call_doi), s.flow, s.max_call_oi_strike,
                 s.max_put_oi_strike, s.max_pain, s.atm_iv, s.synth_forward))
            return cur.lastrowid

    def add_option_quotes(self, s: Summary, snap_id: int) -> None:
        """ATM +/- window strikes, both types: timestamped bid/ask for the registered option test (R1)."""
        rows = []
        for r in s.window_rows:
            rows.append((r.strike, "CE", r.call_key, r.call_ltp, r.call_bid, r.call_ask, r.call_oi, r.call_iv))
            rows.append((r.strike, "PE", r.put_key, r.put_ltp, r.put_bid, r.put_ask, r.put_oi, r.put_iv))
        with self._lock, self.db:
            self.db.executemany(
                "INSERT INTO option_quotes (ts, session, snap_id, underlying, expiry, strike, type, key, ltp, bid, ask,"
                " oi, iv) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(s.fetched_at, session_of(s.fetched_at), snap_id, s.underlying_key, s.expiry, *x) for x in rows])

    def add_option_rows(self, chain, snap_id: int | None, rows) -> None:
        """Bid/ask/OI/IV of the given strikes of one expiry, both types (R1 recorder; see Bridge._record_rows)."""
        ts = chain.fetched_at.isoformat()
        out = []
        for r in rows:
            out.append((r.strike, "CE", r.call_key, r.call_ltp, r.call_bid, r.call_ask, r.call_oi, r.call_iv))
            out.append((r.strike, "PE", r.put_key, r.put_ltp, r.put_bid, r.put_ask, r.put_oi, r.put_iv))
        with self._lock, self.db:
            self.db.executemany(
                "INSERT INTO option_quotes (ts, session, snap_id, underlying, expiry, strike, type, key, ltp, bid, ask,"
                " oi, iv) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(ts, session_of(ts), snap_id, chain.underlying_key, chain.expiry, *x) for x in out])

    def add_range_forecast(self, root: str, bar_close: str, model: str, ts: str, price: float, q: tuple) -> bool:
        with self._lock, self.db:
            cur = self.db.execute("INSERT OR IGNORE INTO range_forecasts (root, bar_close, model, ts, price, q10, q50, q90)"
                                  " VALUES (?,?,?,?,?,?,?,?)", (root, bar_close, model, ts, price, *q))
            return cur.rowcount > 0

    def unscored_forecasts(self) -> list[tuple[str, str]]:
        with self._lock:
            return self.db.execute("SELECT DISTINCT root, bar_close FROM range_forecasts WHERE realized IS NULL").fetchall()

    def set_realized(self, root: str, bar_close: str, value: float) -> None:
        with self._lock, self.db:
            self.db.execute("UPDATE range_forecasts SET realized=? WHERE root=? AND bar_close=?", (value, root, bar_close))

    def scored_forecasts(self) -> list[tuple]:
        with self._lock:
            return self.db.execute("SELECT root, bar_close, model, q10, q50, q90, realized FROM range_forecasts "
                                   "WHERE realized IS NOT NULL").fetchall()

    def add_contract(self, key: str, root: str, expiry: str, lot_size: int, day: str) -> None:
        """Which futures contract was the front month on which day (the R1 scorer matches quotes by it)."""
        with self._lock, self.db:
            self.db.execute("INSERT OR IGNORE INTO contracts (key, root, expiry, lot_size, day) VALUES (?,?,?,?,?)",
                            (key, root, expiry, lot_size, day))

    def add_quote(self, q) -> None:
        with self._lock, self.db:
            self.db.execute("INSERT INTO quotes (ts, key, last, bid, ask, ltt) VALUES (?,?,?,?,?,?)",
                            (q.fetched_at.isoformat(), q.key, q.last_price, q.bid, q.ask,
                             q.last_trade_time.isoformat() if q.last_trade_time else None))

    def iv_change(self, underlying: str, ts_iso: str, minutes: int = 15, tolerance: int = 5) -> tuple[float | None, str]:
        """ATM IV now minus ATM IV ~`minutes` earlier, same session, same expiry and same ATM strike.

        Returns (change, note). The reference snapshot must lie within `minutes` +/- `tolerance`; otherwise the
        change is unavailable (no overnight or cross-expiry comparisons)."""
        with self._lock:
            row = self.db.execute(
                "SELECT atm_iv, expiry, session, atm_strike FROM snapshots WHERE underlying=? AND ts<=? "
                "ORDER BY ts DESC LIMIT 1", (underlying, ts_iso)).fetchone()
            if not row or row[0] is None:
                return None, "no IV"
            t = datetime.fromisoformat(ts_iso)
            lo = (t - timedelta(minutes=minutes + tolerance)).isoformat()
            hi = (t - timedelta(minutes=minutes - tolerance)).isoformat()
            ref = self.db.execute(
                "SELECT atm_iv, atm_strike FROM snapshots WHERE underlying=? AND expiry=? AND session=? "
                "AND ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 1", (underlying, row[1], row[2], lo, hi)).fetchone()
        if not ref or ref[0] is None:
            return None, "no comparable snapshot 10-20 min earlier today"
        if ref[1] != row[3]:
            return row[0] - ref[0], f"ATM strike moved {ref[1]:g}→{row[3]:g}"
        return row[0] - ref[0], ""

    # ---- signals / events ----
    def add_signal(self, source: str, raw: dict, sig, dec, snapshot_id, basis, delay_s) -> int:
        with self._lock, self.db:
            cur = self.db.execute(
                "INSERT INTO signals (ts, source, sid, raw, symbol, side, entry, sl, t1, score, grade_in, action,"
                " grade_out, flow, basis, delay_s, reasons, snapshot_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (self.now(), source, sig.sid or None, json.dumps(raw)[:20000], sig.symbol, sig.side, sig.entry,
                 sig.sl, sig.t1, sig.score, dec.grade_in, dec.action, dec.grade_out, dec.flow, basis, delay_s,
                 json.dumps(dec.reasons), snapshot_id))
            return cur.lastrowid

    def add_evidence(self, sid: str | None, card) -> None:
        with self._lock, self.db:
            self.db.execute(
                "INSERT INTO signal_evidence (ts, sid, trust, cell_key, cost_share, card) VALUES (?,?,?,?,?,?)",
                (self.now(), sid, card.trust, card.key, _clean(card.cost_share),
                 json.dumps({"cell": card.cell, "window": card.window, "note": card.note, "reasons": card.reasons})))

    def add_sent(self, text: str, ok: bool) -> None:
        with self._lock, self.db:
            self.db.execute("INSERT INTO sent_messages (ts, ok, text) VALUES (?,?,?)", (self.now(), int(ok), text))

    def add_event(self, source: str, raw: dict) -> None:
        with self._lock, self.db:
            self.db.execute("INSERT INTO events (ts, source, raw) VALUES (?,?,?)", (self.now(), source, json.dumps(raw)))

    def count(self, table: str) -> int:
        assert table in ("snapshots", "signals", "events", "inbox", "quotes", "option_quotes", "contracts")
        with self._lock:
            return self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
