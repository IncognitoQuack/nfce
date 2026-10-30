"""Append-only SQLite event store, WAL mode, one writer (A section 4.1; blueprint section 3).

Tables: events, intents, execution_events, positions, day_equity, risk_state, protocols, verdicts. Every table is
append-only: triggers abort UPDATE and DELETE, and a revision is a new row. Inserts are idempotent on the record ID
(a restart that re-applies the same record changes nothing), which is what makes replay restart-safe.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .types import Event, ExecutionEvent, Intent, canonical_json

_TABLES = {
    "events": "event_id text primary key, instrument_id text not null, exchange_ts text, received_at text not null, "
              "available_at text not null, kind text not null, payload text not null, source_hash text",
    "intents": "intent_id text primary key, alpha_id text not null, branch text not null, decided_at text not null, "
               "body text not null",
    "execution_events": "exec_id text primary key, intent_id text not null, leg_index integer not null, ts text not null, "
                        "kind text not null, scenario text not null, body text not null",
    "positions": "id integer primary key autoincrement, book text not null, ts text not null, body text not null",
    "day_equity": "id integer primary key autoincrement, book text not null, day text not null, ts text not null, "
                  "body text not null",
    "risk_state": "id integer primary key autoincrement, book text not null, day text not null, ts text not null, "
                  "body text not null",
    "protocols": "protocol_id text primary key, sha256 text not null, frozen_at text not null, body text not null",
    "verdicts": "id integer primary key autoincrement, protocol_id text not null, ts text not null, body text not null",
}
_INDEXES = ("create index if not exists events_ia on events (instrument_id, available_at)",
            "create index if not exists events_a on events (available_at)",
            "create index if not exists exec_i on execution_events (intent_id)",
            "create unique index if not exists verdict_once on verdicts (protocol_id)")


class AppendOnlyError(sqlite3.IntegrityError):
    pass


def _iso(t: datetime | None) -> str | None:
    """UTC ISO text, so that string order is time order across offsets."""
    return None if t is None else t.astimezone(timezone.utc).isoformat()


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        # created on the bridge thread, stepped on the gs-engine thread (27 Oct live bug): allow both
        self.con = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self.con.execute("pragma journal_mode=wal")
        self.con.execute("pragma synchronous=normal")
        for name, cols in _TABLES.items():
            self.con.execute(f"create table if not exists {name} ({cols})")
            for op in ("update", "delete"):
                self.con.execute(f"create trigger if not exists {name}_no_{op} before {op} on {name} "
                                 f"begin select raise(abort, '{name} is append-only'); end")
        for ix in _INDEXES:
            self.con.execute(ix)

    def close(self) -> None:
        self.con.close()

    def _insert(self, table: str, row: dict) -> bool:
        cols = ",".join(row)
        cur = self.con.execute(f"insert or ignore into {table} ({cols}) values ({','.join('?' * len(row))})",
                               tuple(row.values()))
        return cur.rowcount == 1

    # ------------------------------------------------------------ events
    def append_event(self, e: Event) -> bool:
        """True if new; False if this event ID is already stored (idempotent)."""
        return self._insert("events", {"event_id": e.event_id, "instrument_id": e.instrument_id,
                                       "exchange_ts": _iso(e.exchange_ts), "received_at": _iso(e.received_at),
                                       "available_at": _iso(e.available_at), "kind": e.kind,
                                       "payload": canonical_json(e.payload), "source_hash": e.source_hash})

    def events(self, start: datetime | None = None, end: datetime | None = None, instrument_id: str | None = None,
               kind: str | None = None) -> list[Event]:
        """Events with start <= available_at < end, in (available_at, event_id) order: replay order is availability,
        not exchange time."""
        q, p = "select * from events where 1=1", []
        if start is not None:
            q += " and available_at >= ?"
            p.append(_iso(start))
        if end is not None:
            q += " and available_at < ?"
            p.append(_iso(end))
        if instrument_id:
            q += " and instrument_id = ?"
            p.append(instrument_id)
        if kind:
            q += " and kind = ?"
            p.append(kind)
        q += " order by available_at, event_id"
        out = []
        for r in self.con.execute(q, p):
            out.append(Event(r[0], r[1], datetime.fromisoformat(r[2]) if r[2] else None, datetime.fromisoformat(r[3]),
                             datetime.fromisoformat(r[4]), r[5], json.loads(r[6]), r[7] or ""))
        return out

    # ------------------------------------------------------------ intents and executions
    def append_intent(self, it: Intent) -> bool:
        return self._insert("intents", {"intent_id": it.intent_id, "alpha_id": it.alpha_id, "branch": it.branch,
                                        "decided_at": _iso(it.decided_at), "body": canonical_json(it)})

    def intents(self, alpha_id: str | None = None) -> list[dict]:
        q = "select body from intents" + (" where alpha_id = ?" if alpha_id else "") + " order by decided_at, intent_id"
        return [json.loads(r[0]) for r in self.con.execute(q, (alpha_id,) if alpha_id else ())]

    def append_execution(self, x: ExecutionEvent) -> bool:
        return self._insert("execution_events", {"exec_id": x.exec_id, "intent_id": x.intent_id,
                                                 "leg_index": x.leg_index, "ts": _iso(x.ts), "kind": x.kind,
                                                 "scenario": x.scenario, "body": canonical_json(x)})

    def executions(self, intent_id: str | None = None) -> list[dict]:
        q = "select body from execution_events" + (" where intent_id = ?" if intent_id else "") + " order by ts, exec_id"
        return [json.loads(r[0]) for r in self.con.execute(q, (intent_id,) if intent_id else ())]

    # ------------------------------------------------------------ snapshots (revisions are new rows)
    def append_snapshot(self, table: str, book: str, ts: datetime, body: dict, day: str | None = None) -> None:
        if table not in ("positions", "day_equity", "risk_state"):
            raise ValueError(table)
        row = {"book": book, "ts": _iso(ts), "body": canonical_json(body)}
        if table != "positions":
            row["day"] = day or ts.date().isoformat()
        self._insert(table, row)

    def latest_snapshot(self, table: str, book: str) -> dict | None:
        r = self.con.execute(f"select body from {table} where book = ? order by id desc limit 1", (book,)).fetchone()
        return json.loads(r[0]) if r else None

    # ------------------------------------------------------------ protocols and verdicts
    def freeze_protocol(self, protocol_id: str, sha256: str, frozen_at: datetime, body: dict) -> bool:
        return self._insert("protocols", {"protocol_id": protocol_id, "sha256": sha256, "frozen_at": _iso(frozen_at),
                                          "body": canonical_json(body)})

    def protocol(self, protocol_id: str) -> dict | None:
        r = self.con.execute("select sha256, frozen_at, body from protocols where protocol_id = ?",
                             (protocol_id,)).fetchone()
        return None if r is None else {"sha256": r[0], "frozen_at": r[1], "body": json.loads(r[2])}

    def record_verdict(self, protocol_id: str, ts: datetime, body: dict) -> None:
        """One verdict per protocol, ever (the one-look lock): a second call raises."""
        try:
            self.con.execute("insert into verdicts (protocol_id, ts, body) values (?, ?, ?)",
                             (protocol_id, _iso(ts), canonical_json(body)))
        except sqlite3.IntegrityError as e:
            raise AppendOnlyError(f"{protocol_id} already has a verdict: one look only") from e

    def verdict(self, protocol_id: str) -> dict | None:
        r = self.con.execute("select body from verdicts where protocol_id = ?", (protocol_id,)).fetchone()
        return json.loads(r[0]) if r else None

    # ------------------------------------------------------------ maintenance
    def integrity_check(self) -> bool:
        return self.con.execute("pragma integrity_check").fetchone()[0] == "ok"

    def backup(self, dest: str | Path) -> None:
        out = sqlite3.connect(str(dest))
        with out:
            self.con.backup(out)
        out.close()
