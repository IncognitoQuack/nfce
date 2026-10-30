"""Paper execution (blueprint section 6; A section 4.5). Pure functions over observed books; no order code.

* Marketable fills walk the displayed 5-level book after the latency, never past level 5.
* Capacity: notional <= 5% of the trailing 5-minute average traded value per minute, and book-walk impact <= 3 bp
  beyond the touch; otherwise a partial size, or a skip below one share / lot.
* Passive limit orders, three scenarios: TOUCH (illustration only), STRICT (a later quote trades through the limit by
  >= 1 tick; fill AT the limit, at most 10% of the visible size at that quote) and ADVERSE (strict, then the best 25%
  of filled outcomes removed and 2 bp charged on the rest: `adverse_stress`). A limit that already crosses the
  opposite quote when it becomes active is marketable, not spread-earning.
* Multi-leg option structures: wings first, then shorts; exits shorts first, then wings. A failed short leaves the
  wings to be unwound at executable quotes (legging cost kept); no quote leaves a residual, never a stale mark.
* Markouts at +10 s, +1 min, +5 min: 10,000 x side x (mid_after - fill) / fill.
`simulate`-style functions only see the books they are handed, in time order; they cannot fetch anything.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .types import ExecutionEvent

IMPACT_MAX_BP = 3.0
CAPACITY_SHARE = 0.05
STRICT_PARTICIPATION = 0.10
ADVERSE_DROP, ADVERSE_PENALTY_BP = 0.25, 2.0
MARKOUTS_S = (10, 60, 300)


@dataclass(frozen=True)
class Book:
    """One observed quote: ts = response-received time (or the snapshot time for old archives)."""
    ts: datetime
    bids: tuple = ()          # ((price, qty), ...) best first
    asks: tuple = ()
    last: float | None = None
    volume: float | None = None   # cumulative day volume
    exch_ts: datetime | None = None

    @property
    def bid(self) -> float:
        return self.bids[0][0] if self.bids else 0.0

    @property
    def ask(self) -> float:
        return self.asks[0][0] if self.asks else 0.0

    @property
    def bid_qty(self) -> float:
        return self.bids[0][1] if self.bids else 0.0

    @property
    def ask_qty(self) -> float:
        return self.asks[0][1] if self.asks else 0.0

    @property
    def mid(self) -> float | None:
        return (self.bid + self.ask) / 2 if self.valid else None

    @property
    def valid(self) -> bool:
        """Positive two-sided quote, not crossed."""
        return self.bid > 0 and self.ask > 0 and self.ask >= self.bid and self.bid_qty > 0 and self.ask_qty > 0

    @staticmethod
    def from_depth(ts, depth: dict, last=None, volume=None, exch_ts=None) -> "Book":
        """From an Upstox depth dict {"buy": [{price, quantity}], "sell": [...]}; zero levels dropped."""
        lv = lambda xs: tuple((float(x["price"]), float(x["quantity"])) for x in (xs or [])  # noqa: E731
                              if x.get("price") and x.get("quantity"))
        return Book(ts, lv(depth.get("buy")), lv(depth.get("sell")), last, volume, exch_ts)


# ------------------------------------------------------------------ book walk and capacity
@dataclass(frozen=True)
class Walk:
    qty: float
    avg_price: float
    impact_bp: float          # average price beyond the touch, in bp of the touch
    exhausted: bool           # the displayed book ran out before the requested size


def walk(book: Book, side: int, qty: float, limit: float | None = None) -> Walk:
    """Fill `qty` against the displayed levels (asks for a buy, bids for a sale), not beyond `limit`."""
    levels = book.asks if side > 0 else book.bids
    left, cost, got = qty, 0.0, 0.0
    for px, q in levels:
        if limit is not None and (px > limit if side > 0 else px < limit):
            break
        take = min(left, q)
        cost += take * px
        got += take
        left -= take
        if left <= 0:
            break
    if got <= 0:
        return Walk(0.0, math.nan, math.nan, True)
    avg = cost / got
    touch = levels[0][0]
    return Walk(got, avg, side * (avg - touch) / touch * 1e4, left > 1e-9)


def traded_value_per_min(books: list[Book]) -> list[float]:
    """Traded value per minute between consecutive observations (cumulative volume x last price); a negative or
    missing volume step (a reset or a gap) gives no value."""
    out = []
    for a, b in zip(books, books[1:]):
        if a.volume is None or b.volume is None or b.volume < a.volume or not b.last:
            continue
        mins = (b.ts - a.ts).total_seconds() / 60
        if mins <= 0:
            continue
        out.append((b.volume - a.volume) * b.last / mins)
    return out


def capacity_qty(price: float, trailing_books: list[Book], now: datetime, share: float = CAPACITY_SHARE,
                 window_min: int = 5) -> float:
    """Max shares by participation: share x mean traded value per minute over the trailing completed window."""
    w = [b for b in trailing_books if now - timedelta(minutes=window_min) - timedelta(seconds=30) <= b.ts <= now]
    v = traded_value_per_min(w)
    if not v or price <= 0:
        return 0.0
    return share * (sum(v) / len(v)) / price


def max_qty_within_impact(book: Book, side: int, qty: int, lot: int = 1, impact_max_bp: float = IMPACT_MAX_BP) -> int:
    """The largest multiple of `lot` <= qty that the displayed book fills with impact <= impact_max_bp."""
    q = (qty // lot) * lot
    while q >= lot:
        w = walk(book, side, q)
        if not w.exhausted and w.impact_bp <= impact_max_bp + 1e-9:
            return q
        q -= lot
    return 0


# ------------------------------------------------------------------ marketable fills
def first_book(books: list[Book], at: datetime, max_wait_s: float) -> Book | None:
    """The first VALID book with at <= ts <= at + max_wait_s (books must be in time order)."""
    for b in books:
        if b.ts < at:
            continue
        if (b.ts - at).total_seconds() > max_wait_s:
            return None
        if b.valid:
            return b
    return None


def market_fill(intent_id: str, leg_index: int, instrument_id: str, side: int, qty: int, books: list[Book],
                activate_at: datetime, fee_fn, lot: int = 1, max_wait_s: float = 10.0,
                impact_max_bp: float = IMPACT_MAX_BP, scenario: str = "market") -> ExecutionEvent:
    """Fill a marketable order on the first valid book after activation, walking depth, size capped by impact.
    Expires if no valid book arrives within max_wait_s; a partial size if the book is thin."""
    b = first_book(books, activate_at, max_wait_s)
    if b is None:
        return ExecutionEvent.new(intent_id, leg_index, activate_at + timedelta(seconds=max_wait_s), "expire",
                                  instrument_id=instrument_id, side=side, scenario=scenario,
                                  reason="no valid quote in time")
    q = max_qty_within_impact(b, side, qty, lot, impact_max_bp)
    if q == 0:
        return ExecutionEvent.new(intent_id, leg_index, b.ts, "reject", instrument_id=instrument_id, side=side,
                                  scenario=scenario, reason="depth or impact")
    w = walk(b, side, q)
    return ExecutionEvent.new(intent_id, leg_index, b.ts, "fill", instrument_id=instrument_id, side=side, qty=int(q),
                              price=w.avg_price, fee=fee_fn(side, w.avg_price, q, b.ts),
                              scenario=scenario, meta=(("impact_bp", round(w.impact_bp, 4)),
                                                       ("partial", q < qty), ("mid", b.mid)))


# ------------------------------------------------------------------ passive fills
def passive_limit(side: int, boundary: float, book: Book) -> float:
    """GS-SIP-1: a long rests at min(boundary, bid), a short at max(boundary, ask)."""
    return min(boundary, book.bid) if side > 0 else max(boundary, book.ask)


class PassiveOrder:
    """One resting limit order, fed book by book (the same object serves replay and live). `scenario` is "touch" or
    "strict". Fills are AT the limit (or at a better opposite quote if the order is marketable on arrival)."""

    def __init__(self, intent_id: str, leg_index: int, instrument_id: str, side: int, qty: int, limit: float,
                 tick: float, activate_at: datetime, expires_at: datetime, fee_fn, scenario: str = "strict",
                 participation: float = STRICT_PARTICIPATION, arrival_book: Book | None = None,
                 fee_fn_rest=None):
        self.intent_id, self.leg_index, self.instrument_id = intent_id, leg_index, instrument_id
        self.side, self.left, self.limit, self.tick = side, qty, limit, tick
        self.activate_at, self.expires_at, self.fee_fn = activate_at, expires_at, fee_fn
        self.scenario, self.participation = scenario, participation
        self.first, self.done = True, False
        self.filled = 0
        self.pre = arrival_book if arrival_book is not None and arrival_book.valid else None
        # brokerage is per executed ORDER: the parts after the first fill of one order pay no brokerage
        self.fee_fn_rest = fee_fn_rest or fee_fn

    def _fill(self, ts, q, px, reason=""):
        fee = (self.fee_fn if self.filled == 0 else self.fee_fn_rest)(self.side, px, q, ts)
        self.left -= q
        self.filled += q
        return ExecutionEvent.new(self.intent_id, self.leg_index, ts, "fill", instrument_id=self.instrument_id,
                                  side=self.side, qty=int(q), price=px, fee=fee, scenario=self.scenario, reason=reason)

    def on_book(self, b: Book) -> list[ExecutionEvent]:
        if self.done:
            return []
        if b.ts > self.expires_at:
            return self.expire()
        if not b.valid:
            return []
        if b.ts <= self.activate_at:                               # the market as the order arrives
            self.pre = b
            if b.ts < self.activate_at:
                return []
        side, limit = self.side, self.limit
        out = []
        if self.first:
            self.first = False
            a = self.pre or b
            aopp = a.ask if side > 0 else a.bid
            if aopp <= limit if side > 0 else aopp >= limit:
                w = walk(a, side, self.left, limit)                # crosses on arrival: a marketable fill
                if w.qty > 0:
                    out.append(self._fill(max(a.ts, self.activate_at), int(w.qty), w.avg_price,
                                          "marketable on arrival"))
                if self.left <= 0:
                    self.done = True
                return out
            if b.ts <= self.activate_at:
                return out
        opp = b.ask if side > 0 else b.bid
        if self.scenario == "touch":
            hit = (opp <= limit) if side > 0 else (opp >= limit)
            if not hit and b.last:
                hit = (b.last <= limit) if side > 0 else (b.last >= limit)
            q = self.left if hit else 0
        else:
            through = (opp <= limit - self.tick + 1e-9) if side > 0 else (opp >= limit + self.tick - 1e-9)
            size = b.ask_qty if side > 0 else b.bid_qty
            q = int(min(self.left, math.floor(self.participation * size))) if through else 0
        if q > 0:
            out.append(self._fill(b.ts, q, limit))
        if self.left <= 0:
            self.done = True
        return out

    def expire(self) -> list[ExecutionEvent]:
        """Close the order at its expiry; an `expire` event for any unfilled remainder."""
        if self.done:
            return []
        self.done = True
        if self.left <= 0:
            return []
        return [ExecutionEvent.new(self.intent_id, self.leg_index, self.expires_at, "expire",
                                   instrument_id=self.instrument_id, side=self.side, qty=int(self.left),
                                   scenario=self.scenario, reason="unfilled at expiry")]


def passive_fill(intent_id: str, leg_index: int, instrument_id: str, side: int, qty: int, limit: float, tick: float,
                 books: list[Book], activate_at: datetime, expires_at: datetime, fee_fn,
                 scenario: str = "strict", participation: float = STRICT_PARTICIPATION) -> list[ExecutionEvent]:
    """Batch form of PassiveOrder over books in time order: fills, then an `expire` for any remainder."""
    o = PassiveOrder(intent_id, leg_index, instrument_id, side, qty, limit, tick, activate_at, expires_at, fee_fn,
                     scenario, participation)
    out = []
    for b in books:
        out += o.on_book(b)
        if o.done:
            break
    return out + o.expire()


def adverse_stress(outcomes: list[float | None], notionals: list[float], drop: float = ADVERSE_DROP,
                   penalty_bp: float = ADVERSE_PENALTY_BP) -> list[float]:
    """Ex-post stress (never a filter): from the STRICT outcomes (rupees; None = not filled), the best `drop` share
    of FILLED outcomes are set to zero and every remaining fill pays `penalty_bp` of its notional."""
    filled = [i for i, x in enumerate(outcomes) if x is not None]
    k = int(math.ceil(drop * len(filled)))
    best = set(sorted(filled, key=lambda i: (-outcomes[i], i))[:k])
    return [0.0 if (x is None or i in best) else x - penalty_bp * 1e-4 * notionals[i] for i, x in enumerate(outcomes)]


# ------------------------------------------------------------------ markouts
def markouts(fill_ts: datetime, fill_price: float, side: int, books: list[Book], horizons=MARKOUTS_S,
             tolerance_s: float = 70.0) -> dict:
    """Signed bp markout at each horizon from the first valid mid at/after fill + h (None if none within tolerance)."""
    out = {}
    for h in horizons:
        b = first_book(books, fill_ts + timedelta(seconds=h), tolerance_s)
        out[h] = None if b is None else 1e4 * side * (b.mid - fill_price) / fill_price
    return out


# ------------------------------------------------------------------ multi-leg structures
@dataclass
class StructureState:
    """Wings-first entry / shorts-first exit of a defined-risk structure. legs: [(instrument_id, side, qty, role)]."""
    legs: list
    state: str = "PENDING"    # PENDING -> WINGS -> OPEN | CANCELLED | UNWOUND | RESIDUAL -> CLOSING -> CLOSED
    events: list = field(default_factory=list)
    open_qty: dict = field(default_factory=dict)


def _fill_leg(intent_id, i, leg, snap, side, fee_fn, lot):
    inst, _, qty, _ = leg
    b = snap.get(inst)
    if b is None or not b.valid:
        return None
    q = max_qty_within_impact(b, side, qty, lot, impact_max_bp=float("inf"))
    if q < qty:                                                    # option legs: the whole size or nothing
        return None
    w = walk(b, side, qty)
    return ExecutionEvent.new(intent_id, i, b.ts, "fill", instrument_id=inst, side=side, qty=qty, price=w.avg_price,
                              fee=fee_fn(side, w.avg_price, qty, b.ts), scenario="market")


def enter_structure(intent_id: str, legs: list, snaps: list, activate_at: datetime, cancel_at: datetime, fee_fn,
                    lot: int) -> StructureState:
    """snaps: [(ts, {instrument_id: Book})] in time order. Wings (role "wing") fill first, at the first snapshot
    >= activate_at where every wing fills; shorts at the first snapshot >= that one where every short fills. Wings that
    cannot be completed by cancel_at: nothing is entered. Shorts that cannot: the wings are sold back (UNWOUND) at the
    first snapshot where they can be, or left RESIDUAL."""
    st = StructureState(list(legs))
    wings = [i for i, l in enumerate(legs) if l[3] == "wing"]
    shorts = [i for i, l in enumerate(legs) if l[3] != "wing"]
    k_w = None
    for k, (ts, snap) in enumerate(snaps):
        if ts < activate_at or ts > cancel_at:
            continue
        evs = [_fill_leg(intent_id, i, legs[i], snap, legs[i][1], fee_fn, lot) for i in wings]
        if all(e is not None for e in evs):
            st.events += evs
            st.open_qty.update({i: legs[i][1] * legs[i][2] for i in wings})
            st.state, k_w = "WINGS", k
            break
    if k_w is None:
        st.state = "CANCELLED"
        return st
    for ts, snap in snaps[k_w:]:
        if ts > cancel_at:
            break
        evs = [_fill_leg(intent_id, i, legs[i], snap, legs[i][1], fee_fn, lot) for i in shorts]
        if all(e is not None for e in evs):
            st.events += evs
            st.open_qty.update({i: legs[i][1] * legs[i][2] for i in shorts})
            st.state = "OPEN"
            return st
    # shorts failed: unwind the wings (sell them back) at executable quotes after the cancel time
    for ts, snap in snaps[k_w + 1:]:
        if ts <= cancel_at:
            continue
        evs = [_fill_leg(f"{intent_id}-unwind", i, legs[i], snap, -legs[i][1], fee_fn, lot) for i in wings]
        if all(e is not None for e in evs):
            st.events += evs
            st.open_qty = {}
            st.state = "UNWOUND"
            return st
    st.state = "RESIDUAL"                                          # long wings still open, no executable quote
    return st


def exit_structure(st: StructureState, intent_id: str, snaps: list, start_at: datetime, fee_fn, lot: int,
                   deadline: datetime | None = None) -> StructureState:
    """Close shorts first (each at its first executable snapshot >= start_at), then wings (at or after the later
    short exit). Legs without a quote by the deadline stay open: state RESIDUAL."""
    if st.state not in ("OPEN", "RESIDUAL", "CLOSING"):
        return st
    shorts = [i for i in st.open_qty if st.legs[i][3] != "wing"]
    wings = [i for i in st.open_qty if st.legs[i][3] == "wing"]
    floor = start_at
    for group in (shorts, wings):
        done = []
        for i in group:
            for ts, snap in snaps:
                if ts < floor or (deadline is not None and ts > deadline):
                    continue
                e = _fill_leg(f"{intent_id}-exit", i, st.legs[i], snap, -st.legs[i][1], fee_fn, lot)
                if e is not None:
                    done.append(e)
                    st.open_qty.pop(i)
                    break
        st.events += sorted(done, key=lambda e: (e.ts, e.leg_index))
        done_ts = [e.ts for e in done]
        if any(i in st.open_qty for i in group):
            st.state = "RESIDUAL"
            return st
        floor = max(done_ts) if done_ts else floor
    st.state = "CLOSED"
    return st
