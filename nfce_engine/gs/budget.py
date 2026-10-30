"""Shared Upstox request budget (blueprint section 4; A section 4.2): one sliding-window bucket for every process.

<= 1,600 requests per 30 minutes and <= 4 per second, across the bridge and all recorders. Separate sleeps in each
script cannot enforce a shared quota, so the bucket lives in one SQLite file (a BEGIN IMMEDIATE transaction makes
each grant atomic across processes). Priorities: exits first, then health, active positions, chains, warm-up last;
each lower class stops short of the window cap, so the last tokens are always left for exits and health. An HTTP 429
freezes new entries for a back-off period. Not wired into anything yet.
"""
from __future__ import annotations

import random
import sqlite3
import time
from pathlib import Path

EXIT, HEALTH, ACTIVE, CHAIN, WARMUP = 0, 1, 2, 3, 4
WINDOW_S, WINDOW_MAX, PER_SECOND = 1800.0, 1600, 4
# a class may take a token only while the window's use stays at or below its ceiling
CEILING = {EXIT: 1600, HEALTH: 1600, ACTIVE: 1500, CHAIN: 1350, WARMUP: 1200}


class RequestBudget:
    def __init__(self, path: str | Path, window_max: int = WINDOW_MAX, per_second: int = PER_SECOND,
                 window_s: float = WINDOW_S, ceiling: dict | None = None, clock=time.time):
        self.path, self.window_max, self.per_second, self.window_s = str(path), window_max, per_second, window_s
        self.ceiling = dict(ceiling or CEILING)
        self.clock = clock
        con = self._con()
        con.execute("create table if not exists grants (ts real not null, priority integer not null, "
                    "who text not null, n integer not null)")
        con.execute("create index if not exists grants_ts on grants (ts)")
        con.execute("create table if not exists freeze (until real not null, reason text not null)")
        con.close()

    def _con(self):
        c = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        c.execute("pragma journal_mode=wal")
        return c

    def acquire(self, priority: int, who: str = "", n: int = 1, now: float | None = None) -> bool:
        """Non-blocking: True and recorded if n requests may be sent now under every limit; False otherwise."""
        now = self.clock() if now is None else now
        con = self._con()
        try:
            con.execute("begin immediate")
            used = con.execute("select coalesce(sum(n), 0) from grants where ts > ? and ts <= ?",
                               (now - self.window_s, now)).fetchone()[0]
            sec = con.execute("select coalesce(sum(n), 0) from grants where ts > ? and ts <= ?",
                              (now - 1.0, now)).fetchone()[0]
            cap = min(self.window_max, self.ceiling.get(priority, min(self.ceiling.values())))
            ok = used + n <= cap and sec + n <= self.per_second
            if ok:
                con.execute("insert into grants values (?, ?, ?, ?)", (now, priority, who, n))
                con.execute("delete from grants where ts <= ?", (now - 2 * self.window_s,))
            con.execute("commit")
            return ok
        finally:
            con.close()

    def used(self, now: float | None = None) -> int:
        now = self.clock() if now is None else now
        con = self._con()
        try:
            return con.execute("select coalesce(sum(n), 0) from grants where ts > ? and ts <= ?",
                               (now - self.window_s, now)).fetchone()[0]
        finally:
            con.close()

    def by_priority(self, now: float | None = None) -> dict:
        now = self.clock() if now is None else now
        con = self._con()
        try:
            return dict(con.execute("select priority, sum(n) from grants where ts > ? and ts <= ? group by priority",
                                    (now - self.window_s, now)).fetchall())
        finally:
            con.close()

    # -------------------------------------------------------- HTTP 429
    def on_429(self, attempt: int, now: float | None = None, rng: random.Random | None = None) -> float:
        """Freeze new entries; return the back-off in seconds (exponential, with jitter, capped at 5 minutes)."""
        now = self.clock() if now is None else now
        r = rng or random.Random()
        wait = min(300.0, 5.0 * 2 ** attempt) * (1 + 0.25 * r.random())
        con = self._con()
        try:
            con.execute("insert into freeze values (?, ?)", (now + wait, f"HTTP 429 (attempt {attempt})"))
        finally:
            con.close()
        return wait

    def entries_frozen(self, now: float | None = None) -> bool:
        now = self.clock() if now is None else now
        con = self._con()
        try:
            return con.execute("select count(*) from freeze where until > ?", (now,)).fetchone()[0] > 0
        finally:
            con.close()
