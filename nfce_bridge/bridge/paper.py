"""Paper-trading ledger with two books, tracked on the live FRONT-MONTH FUTURES quote (the contract NIFTY1! follows).

theoretical  Enters at the signal's own entry price and manages exits exactly like the backtests:
             targets fill at the target, stops at the stop (at the observed price only after a data gap),
             15:15 square-off. Costs = dated fees + 4 ticks per side friction (same convention as the backtests).
executable   What a person could actually have done: enters at the live ask (BUY) / bid (SELL) plus extra
             slippage when the alert ARRIVES, only if the quote is fresh, the spread is acceptable, the alert is
             not too old, and the risk gate allows it. Targets need a trade-through of one tick; stops and
             square-off exit at the opposite touch minus slippage (an SL-M order becomes a market order).
             Costs = dated fees (friction is already inside the fills).

Quantity (FIX, review round 3, H02): every book trades a whole number of lots, PAPER_LOTS = 10 by default, the same
as the TradingView strategy, so the 40/30/30 exits are 4/3/3 whole lots. lot_plan() splits any lot count into whole
lots (1 lot = one exit of everything at T1). Fees are charged for the actual number of lots and orders.

Never invented: a trade still open on a later session, or after an outage spanning the 15:15 square-off, is closed
at the first new observation with status UNRESOLVED and excluded from performance figures (counted separately).
Both books keep VETOED signals as shadow trades, so the option-chain veto rule is measured, not assumed.
"""
from __future__ import annotations

import json
import math
import sqlite3
import statistics
import threading
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from .costs import futures_cost_points
from .providers import IST, Quote

TICK = {"NIFTY": 0.1, "BANKNIFTY": 0.2, "FINNIFTY": 0.1, "MIDCPNIFTY": 0.05, "SENSEX": 0.05}   # SENSEX: BSE file, 5 paise
LOT = {"NIFTY": 65, "BANKNIFTY": 30, "FINNIFTY": 60, "MIDCPNIFTY": 120, "SENSEX": 20}
THEO_FRICTION_TICKS = 4
PAPER_LOTS = 10
EXCLUSIVE_BOOKS = ("executable", "theoretical")
STOCK_BOOKS = ("scanner", "stock3m")                # stock-futures books, quoted by their own futures keys    # one open position per underlying/timeframe; r4 = paired shadow trials

SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_trades (
    id INTEGER PRIMARY KEY, book TEXT NOT NULL, sid TEXT, opened TEXT, closed TEXT, underlying TEXT, tf TEXT,
    decision TEXT, grade TEXT, side INTEGER, entry REAL, sl REAL, t1 REAL, t2 REAL, t3 REAL, status TEXT,
    exit_reason TEXT, gross_pts REAL, net_pts REAL, r_pts REAL, flags TEXT, state TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS ux_paper_sid ON paper_trades(book, sid) WHERE sid IS NOT NULL;
"""
# FIX (H03): the one-position rule is enforced by the database too, not only by an in-memory check.
OPEN_INDEX = ("CREATE UNIQUE INDEX IF NOT EXISTS ux_paper_open ON paper_trades(book, underlying, tf) "
              "WHERE status='OPEN' AND book IN ('executable','theoretical')")


def lot_plan(lots: int) -> tuple[int, int, int]:
    """Whole lots exited at T1 / T2 / T3 (40/30/30 rounded; at least one lot at T1)."""
    lots = max(1, int(lots))
    n1 = max(1, round(0.4 * lots))
    n2 = min(round(0.3 * lots), lots - n1)
    return n1, n2, lots - n1 - n2


def _mins(t: datetime) -> int:
    t = t.astimezone(IST)
    return t.hour * 60 + t.minute


@dataclass
class PaperTrade:
    book: str
    underlying: str
    tf: str
    decision: str
    grade: str
    side: int
    entry: float
    sl: float
    t1: float
    t2: float
    t3: float
    opened: str
    sid: str | None = None
    signal_R: float = 0.0
    id: int | None = None
    rem: float = 1.0
    pnl: float = 0.0
    t1hit: bool = False
    t2hit: bool = False
    stop: float = math.nan
    status: str = "OPEN"          # OPEN / CLOSED / UNRESOLVED / REJECTED
    exit_reason: str = ""
    closed: str = ""
    last_seen: str = ""
    exit_value: float = 0.0       # sum(fraction x exit price), for the average exit price
    orders: int = 1
    flags: list[str] = field(default_factory=list)
    lots: int = PAPER_LOTS
    received: str = ""            # when the alert arrived (opened = when the entry decision was made)
    lot_units: int = 0            # units per lot; 0 = the index table (stock futures carry their own)
    tick_size: float = 0.0        # 0 = the index table

    def __post_init__(self):
        if math.isnan(self.stop):
            self.stop = self.sl
        if not self.signal_R:
            self.signal_R = abs(self.entry - self.sl)

    @property
    def R(self) -> float:
        return self.signal_R

    @property
    def tick(self) -> float:
        return self.tick_size or TICK.get(self.underlying, 0.1)

    def avg_exit(self) -> float:
        return self.exit_value if self.exit_value else self.entry

    def net_pts(self) -> float:
        when = datetime.fromisoformat(self.opened).astimezone(IST).date()
        friction = THEO_FRICTION_TICKS * self.tick if self.book == "theoretical" else 0.0
        return self.pnl - futures_cost_points(self.entry, self.avg_exit(), self.side, when,
                                              self.lot_units or LOT.get(self.underlying, 1), self.lots, self.orders, friction)

    @property
    def units(self) -> int:
        return self.lots * (self.lot_units or LOT.get(self.underlying, 1))

    # ---- fills ----
    def _book_exit(self, frac: float, px: float) -> None:
        self.pnl += frac * self.side * (px - self.entry)
        self.exit_value += frac * px
        self.rem -= frac
        self.orders += 1

    def _exit_touch(self, q: Quote, slip_ticks: int) -> float:
        """Price a market exit would get: the opposite touch minus slippage (falls back to last price)."""
        if self.book == "theoretical":
            return q.last_price
        touch = (q.bid if self.side > 0 else q.ask) or q.last_price
        return touch - self.side * slip_ticks * self.tick

    def _close(self, reason: str, now: datetime, status: str = "CLOSED") -> bool:
        self.status, self.exit_reason, self.closed = status, reason, now.isoformat()
        return True

    def on_quote(self, q: Quote, now: datetime, max_gap_s: float = 75, slip_ticks: int = 2,
                 square_off: int = 15 * 60 + 15) -> bool:
        """Update with a futures quote. Returns True when the trade closes (or becomes UNRESOLVED)."""
        if self.status != "OPEN":
            return False
        px = q.last_price
        prev = datetime.fromisoformat(self.last_seen) if self.last_seen else datetime.fromisoformat(self.opened)
        self.last_seen = now.isoformat()
        gap = (now - prev).total_seconds() > max_gap_s
        if gap and "gap" not in self.flags:
            self.flags.append("gap")
        if now.astimezone(IST).date() != datetime.fromisoformat(self.opened).astimezone(IST).date():
            self._book_exit(self.rem, self._exit_touch(q, slip_ticks))
            self.flags.append("overnight")
            return self._close("unresolved: still open on a later session (missed square-off)", now, "UNRESOLVED")
        if gap and _mins(now) >= square_off and _mins(prev) < square_off:
            self._book_exit(self.rem, self._exit_touch(q, slip_ticks))
            self.flags.append("missed_square_off")
            return self._close("unresolved: data outage across 15:15", now, "UNRESOLVED")
        s = self.side
        if (px - self.stop) * s <= 0:                                   # stop triggered (LTP crossed it)
            if self.book == "theoretical":
                fill = px if gap else self.stop
            else:
                fill = self._exit_touch(q, slip_ticks)
                fill = min(fill, self.stop) if s > 0 else max(fill, self.stop)   # SL-M: never better than the stop
            self._book_exit(self.rem, fill)
            return self._close("stop" if not self.t1hit else "trail/BE stop", now)
        # limit fills need a one-tick trade-through in the executable book (EPS absorbs float rounding)
        through = (0.0 if self.book == "theoretical" else self.tick) - 1e-9
        n1, n2, _ = lot_plan(self.lots)
        if not self.t1hit and (px - self.t1) * s >= through:
            self.t1hit = True
            self._book_exit(min(n1 / self.lots, self.rem), self.t1)
            self.stop = self.entry
            if self.rem <= 1e-9:
                return self._close("T1 (all lots)", now)
        if not self.t2hit and (px - self.t2) * s >= through:
            self.t2hit = True
            if n2:
                self._book_exit(min(n2 / self.lots, self.rem), self.t2)
            self.stop = self.t1
            if self.rem <= 1e-9:
                return self._close("T2 (all lots)", now)
        if (px - self.t3) * s >= through:
            self._book_exit(self.rem, self.t3)
            return self._close("T3", now)
        if _mins(now) >= square_off:
            self._book_exit(self.rem, self._exit_touch(q, slip_ticks))
            return self._close("square-off 15:15", now)
        return False


class PaperBook:
    def __init__(self, store):
        self.store = store
        self.db = store.db
        self.lock: threading.RLock = store._lock
        with self.lock:
            self.db.executescript(SCHEMA)
            try:
                self.db.execute(OPEN_INDEX)
            except sqlite3.IntegrityError:       # an old database with overlapping open trades: keep running, say so
                import logging
                logging.getLogger("nfce.paper").warning("existing overlapping open paper trades; one-position index not created")
            states = self.db.execute("SELECT id, state FROM paper_trades WHERE status='OPEN'").fetchall()
        self.open: list[PaperTrade] = []
        for tid, st in states:                                   # survive restarts
            t = PaperTrade(**json.loads(st))
            t.id = tid
            self.open.append(t)

    # ---- persistence ----
    def _save(self, t: PaperTrade) -> bool:
        state = json.dumps(asdict(t))
        closed = t.status in ("CLOSED", "UNRESOLVED")
        with self.lock, self.db:
            if t.id is None:
                try:
                    cur = self.db.execute(
                        "INSERT INTO paper_trades (book, sid, opened, underlying, tf, decision, grade, side, entry, sl,"
                        " t1, t2, t3, status, exit_reason, r_pts, flags, state) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (t.book, t.sid, t.opened, t.underlying, t.tf, t.decision, t.grade, t.side, t.entry, t.sl,
                         t.t1, t.t2, t.t3, t.status, t.exit_reason, t.R, json.dumps(t.flags), state))
                except sqlite3.IntegrityError:     # same signal id, or an open position, already in this book
                    return False
                t.id = cur.lastrowid
            self.db.execute(
                "UPDATE paper_trades SET closed=?, status=?, exit_reason=?, gross_pts=?, net_pts=?, flags=?, state=? WHERE id=?",
                (t.closed or None, t.status, t.exit_reason, t.pnl if closed else None,
                 t.net_pts() if closed else None, json.dumps(t.flags), json.dumps(asdict(t)), t.id))
        return True

    # ---- queries ----
    def has_open(self, underlying: str, tf: str, book: str) -> bool:
        with self.lock:
            return any(t.underlying == underlying and t.tf == tf and t.book == book for t in self.open)

    def underlyings_open(self) -> set[str]:
        """Index roots with an open trade (stock-scanner trades are tracked separately: see open_stock_trades)."""
        with self.lock:
            return {t.underlying for t in self.open if t.book not in STOCK_BOOKS}

    def open_stock_trades(self) -> list[PaperTrade]:
        with self.lock:
            return [t for t in self.open if t.book in STOCK_BOOKS]

    def find_open(self, sid: str, book: str) -> PaperTrade | None:
        with self.lock:
            return next((t for t in self.open if t.sid == sid and t.book == book), None)

    def day_stats(self, day: date, book: str = "executable") -> dict:
        with self.lock:
            rows = self.db.execute(
                "SELECT net_pts, r_pts, status FROM paper_trades WHERE book=? AND substr(opened,1,10)=? "
                "AND status IN ('CLOSED','OPEN','UNRESOLVED')", (book, day.isoformat())).fetchall()
        closed = [(n / r) for n, r, st in rows if st == "CLOSED" and r]
        return {"trades": len(rows), "losses": sum(x < 0 for x in closed), "r_sum": sum(closed)}

    # ---- actions ----
    def open_trade(self, t: PaperTrade) -> bool:
        """Atomic: the one-position check and the insert happen under one lock (and the database index backs it).
        Returns False for a duplicate signal id or, in an exclusive book, when a position is already open."""
        with self.lock:
            if t.book in EXCLUSIVE_BOOKS and any(o.underlying == t.underlying and o.tf == t.tf and o.book == t.book
                                                 for o in self.open):
                return False
            if not self._save(t):
                return False
            self.open.append(t)
            return True

    def reject(self, t: PaperTrade, reason: str) -> None:
        t.status, t.exit_reason, t.closed = "REJECTED", reason, t.opened
        self._save(t)

    def on_quote(self, underlying: str, q: Quote, now: datetime, max_gap_s: float = 75, slip_ticks: int = 2,
                 square_off: int = 15 * 60 + 15) -> list[PaperTrade]:
        closed = []
        with self.lock:
            for t in list(self.open):
                if t.underlying != underlying:
                    continue
                if t.on_quote(q, now, max_gap_s, slip_ticks, square_off):
                    self.open.remove(t)
                    closed.append(t)
                self._save(t)
        return closed

    # ---- reporting ----
    def report(self) -> str:
        with self.lock:
            rows = self.db.execute("SELECT book, decision, grade, status, net_pts, r_pts, exit_reason, underlying "
                                   "FROM paper_trades").fetchall()
        if not rows:
            return "Paper trading: no trades yet."
        out = ["Paper trading, net of costs (UNRESOLVED and REJECTED are excluded from results):"]
        for book in ("executable", "theoretical"):
            b = [r for r in rows if r[0] == book]
            if not b:
                continue
            closed = [r for r in b if r[3] == "CLOSED" and r[5]]
            out.append(f"[{book}] closed {len(closed)}, open {sum(r[3] == 'OPEN' for r in b)}, "
                       f"unresolved {sum(r[3] == 'UNRESOLVED' for r in b)}, rejected {sum(r[3] == 'REJECTED' for r in b)}")
            groups = {"taken (PASS)": [r for r in closed if r[1] == "PASS"],
                      "vetoed (shadow)": [r for r in closed if r[1] == "VETO"],
                      "unchecked": [r for r in closed if r[1] == "NO_DATA"]}
            for label, g in groups.items():
                if g:
                    rs = [r[4] / r[5] for r in g]
                    inr = sum(r[4] * LOT.get(r[7], 1) for r in g)
                    out.append(f"   {label}: n={len(g)} win={sum(x > 0 for x in rs) / len(rs) * 100:.0f}% "
                               f"avg {statistics.fmean(rs):+.2f}R net ₹{inr:,.0f}/lot")
            p = [r[4] / r[5] for r in groups["taken (PASS)"]]
            v = [r[4] / r[5] for r in groups["vetoed (shadow)"]]
            if len(p) >= 2 and len(v) >= 2:
                se = math.sqrt(statistics.variance(p) / len(p) + statistics.variance(v) / len(v))
                if se > 0:
                    out.append(f"   veto test: PASS−VETO = {statistics.fmean(p) - statistics.fmean(v):+.2f}R "
                               f"(Welch t {(statistics.fmean(p) - statistics.fmean(v)) / se:+.2f}; registered pass bar: "
                               f"≥+0.20R, one-sided p < 0.0167, PASS trades > 0, after ≥200 signals incl. ≥40 "
                               f"vetoes; REGISTRY.md R3, score with nfce_engine/tools/registry_eval.py r3)")
            rej = {}
            for r in b:
                if r[3] == "REJECTED":
                    rej[r[6]] = rej.get(r[6], 0) + 1
            if rej:
                out.append("   rejected because: " + "; ".join(f"{k} ×{v}" for k, v in rej.items()))
        out.append("Small samples mean nothing; judge only against the registered criteria.")
        return "\n".join(out)
