"""Signed-leg paper ledger (A section 3: apply_event). Pure: every operation returns a new Ledger.

Cash accounting: a buy pays price x qty + fee, a sale receives price x qty - fee; positions are signed (a short or a
sold option is negative). Equity = cash + sum(qty x mark). So a cash short, a long and a credit spread all reconcile
the same way. A fill is applied once: its exec_id is remembered (restart-safe). A position without a valid mark is
"unresolved": its equity is reported only as a bound, never from a stale or last-traded price.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from .types import ExecutionEvent


@dataclass(frozen=True)
class Position:
    instrument_id: str
    qty: int = 0                  # signed units
    avg_price: float = 0.0        # average open price of the current signed quantity
    realized: float = 0.0         # gross realized P&L (before fees) on this instrument


@dataclass(frozen=True)
class Ledger:
    book: str
    start_cash: float
    cash: float
    positions: dict = field(default_factory=dict, hash=False)   # instrument_id -> Position
    fees: float = 0.0
    realized: float = 0.0
    reserves: dict = field(default_factory=dict, hash=False)    # key -> rupees held against a structure
    unresolved: frozenset = frozenset()
    applied: frozenset = frozenset()
    day: str = ""
    day_realized_net: float = 0.0  # realized P&L minus fees, for fills on `day` (the DG input)

    @staticmethod
    def new(book: str, cash: float) -> "Ledger":
        return Ledger(book, float(cash), float(cash))

    # -------------------------------------------------------- views
    def open_positions(self) -> dict:
        return {k: p for k, p in self.positions.items() if p.qty != 0}

    @property
    def reserved(self) -> float:
        return float(sum(self.reserves.values()))

    @property
    def realized_net(self) -> float:
        return self.realized - self.fees


def apply_event(ledger: Ledger, ev: ExecutionEvent) -> Ledger:
    """Apply one execution event. Only `fill`/`exit` move cash and positions; any event is applied at most once."""
    if ev.exec_id in ledger.applied:
        return ledger
    applied = ledger.applied | {ev.exec_id}
    if ev.kind not in ("fill", "exit") or ev.qty == 0:
        return replace(ledger, applied=applied)
    if ev.side not in (1, -1) or ev.qty < 0 or ev.price < 0:
        raise ValueError(f"bad fill {ev.exec_id}")
    pos = dict(ledger.positions)
    p = pos.get(ev.instrument_id, Position(ev.instrument_id))
    q0, dq = p.qty, ev.side * ev.qty
    realized = 0.0
    if q0 == 0 or (q0 > 0) == (dq > 0):                      # opening or adding
        q1 = q0 + dq
        avg = (abs(q0) * p.avg_price + ev.qty * ev.price) / abs(q1)
    else:                                                     # reducing, closing or flipping
        closed = min(abs(q0), ev.qty)
        realized = closed * (ev.price - p.avg_price) * (1 if q0 > 0 else -1)
        q1 = q0 + dq
        avg = p.avg_price if q1 != 0 and (q1 > 0) == (q0 > 0) else (ev.price if q1 != 0 else 0.0)
    pos[ev.instrument_id] = Position(ev.instrument_id, q1, avg, p.realized + realized)
    day = ev.ts.date().isoformat() if hasattr(ev.ts, "date") else ledger.day
    same_day = ledger.day == "" or day == ledger.day
    unresolved = ledger.unresolved - {ev.instrument_id} if q1 == 0 else ledger.unresolved
    return replace(ledger, positions=pos, cash=ledger.cash - ev.side * ev.qty * ev.price - ev.fee,
                   fees=ledger.fees + ev.fee, realized=ledger.realized + realized, applied=applied,
                   unresolved=unresolved,
                   day_realized_net=ledger.day_realized_net + (realized - ev.fee if same_day else 0.0))


def start_day(ledger: Ledger, day: str) -> Ledger:
    """A new session: the day's realized P&L restarts at zero (open positions carry over)."""
    return replace(ledger, day=day, day_realized_net=0.0)


def with_reserve(ledger: Ledger, key: str, amount: float) -> Ledger:
    if amount < 0:
        raise ValueError("a reserve is >= 0")
    r = dict(ledger.reserves)
    r[key] = float(amount)
    return replace(ledger, reserves=r)


def release_reserve(ledger: Ledger, key: str) -> Ledger:
    r = dict(ledger.reserves)
    r.pop(key, None)
    return replace(ledger, reserves=r)


def mark_unresolved(ledger: Ledger, instrument_id: str) -> Ledger:
    return replace(ledger, unresolved=ledger.unresolved | {instrument_id})


def equity(ledger: Ledger, marks: dict) -> float | None:
    """cash + sum(qty x mark). None if any open position lacks a valid mark or is unresolved (no stale substitute)."""
    v = ledger.cash
    for k, p in ledger.open_positions().items():
        m = marks.get(k)
        if m is None or k in ledger.unresolved or m < 0:
            return None
        v += p.qty * m
    return v


def equity_bounds(ledger: Ledger, marks: dict, worst: dict, best: dict | None = None) -> tuple[float, float]:
    """(worst, best) equity. Positions with a valid mark use it in both; the others use the caller's conservative
    worst (and best) resolution prices, which must be given for every unmarked position."""
    lo = hi = ledger.cash
    for k, p in ledger.open_positions().items():
        m = None if k in ledger.unresolved else marks.get(k)
        if m is not None:
            lo += p.qty * m
            hi += p.qty * m
            continue
        if k not in worst:
            raise KeyError(f"no worst-case resolution for unresolved {k}")
        lo += p.qty * worst[k]
        hi += p.qty * (best or worst).get(k, worst[k])
    return lo, hi


def net_pnl(ledger: Ledger, marks: dict) -> float | None:
    e = equity(ledger, marks)
    return None if e is None else e - ledger.start_cash
