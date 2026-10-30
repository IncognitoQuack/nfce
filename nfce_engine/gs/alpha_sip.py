"""GS-SIP-1: stocks in play, cash equity, passive entry (blueprint section 5; A section 6). Paper only.

Rules (frozen in ../../evidence/gs_sip_1_protocol.md):
* Selection at 09:21 (+ a 30 s grace for the 09:18 bar to arrive): F&O cash stocks with both 3-minute bars of
  09:15-09:21 and valid opening windows on each of the 14 previous sessions; RVOL = (09:15-09:21 volume) / mean of
  the same window over those 14 sessions, >= 1; ATR14 (Wilder, previous sessions) / previous close >= 1%; the top 20
  by RVOL (ties: instrument id). Direction = sign(09:21 close - 09:15 open); 0 = skip. Ranked BEFORE any breakout.
* Trigger: the first completed 3-minute bar starting at or after 09:30 and closing by 11:30 whose close is beyond the
  opening-range boundary (above the high for a long, below the low for a short).
* Decision: the first fresh book of that stock after the bar is available. Branch P: a passive limit at
  min(boundary, bid) for a long / max(boundary, ask) for a short, rounded against aggressiveness, active after 2 s,
  expiring after 180 s or at 11:33. Branch M: the same signal, marketable after the same 2 s. No chasing, no second
  attempt that day.
* Exit: stop at the average fill -/+ 0.5 x ATR14, executed at the next valid book after the trigger plus the latency
  (a gap gives the worse price); otherwise out at 15:15 at the touch. No target.
* Size: risk 0.25% of equity x regime, ticket <= Rs 1 L, capacity (5% of trailing traded value per minute), the
  section 7 caps (at most 4 open). Every opportunity is recorded; unfilled ones score zero.
* Events (section 7): no entries on a Union Budget day, none 09:30-10:30 on an RBI policy day.
The engine is fed events in availability order (`on_clock`, `on_bar`, `on_book`); the replay tool and the bridge
adapter call the same methods, so their intents and fills are identical for identical inputs.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta

from . import calendar as cal
from . import costs as gcosts
from . import execution as ex
from . import features as ft
from . import instruments
from . import ledger as lg
from . import risk as rk
from .types import ExecutionEvent, Intent, Leg, StopRule, canonical_json, make_id


@dataclass(frozen=True)
class SipConfig:
    alpha_id: str = "GS-SIP-1"
    branch: str = "P"                     # "P" passive (primary) | "M" marketable counterfactual
    scenario: str = "strict"              # branch P: "strict" (primary) | "touch" (illustration)
    equity: float = 500_000.0
    ticket: float = 100_000.0
    top_n: int = 20
    rvol_min: float = 1.0
    rvol_min_windows: int = 14            # all 14 previous windows valid (exploratory smoke runs may relax it)
    atr_pct_min: float = 0.01
    select_at: time = time(9, 21)
    select_grace_s: float = 30.0          # the 09:18 bar reaches the bridge ~15-20 s after 09:21
    trigger_first_start: time = time(9, 30)
    trigger_last_close: time = time(11, 30)
    entry_expire_by: time = time(11, 33)
    latency_s: float = 2.0
    expire_s: float = 180.0
    refresh_wait_s: float = 10.0          # a decision needs a book within this long after the bar is available
    max_wait_s: float = 10.0              # a marketable order needs a valid book within this long after activation
    stop_atr: float = 0.5
    time_exit: time = time(15, 15)
    book_keep_min: float = 6.0
    protocol_hash: str = "DESIGN"
    exploratory: bool = False


@dataclass
class StockDay:
    """Per-stock inputs known before the session: completed daily bars and previous opening-window volumes."""
    instrument_id: str
    daily: list                           # [features.DailyBar]
    prior_windows: list                   # [(date, volume of 09:15-09:21)]
    sector: str = ""
    tick: float = 0.05


@dataclass
class Opp:
    """One opportunity (a selected stock that triggered), in one branch/scenario."""
    instrument_id: str
    side: int
    rvol: float
    atr: float
    boundary: float
    trigger_bar_end: datetime
    status: str = "triggered"
    decided_at: datetime | None = None
    intent_id: str = ""
    limit: float | None = None
    qty_req: int = 0
    qty: int = 0                          # filled (signed by side when positioned)
    entry_cost: float = 0.0               # sum of fill price x qty
    stop: float | None = None
    stop_hit_at: datetime | None = None
    exit_due_at: datetime | None = None
    exit_reason: str = ""
    exit_qty: int = 0
    exit_value: float = 0.0
    fees: float = 0.0
    reasons: tuple = ()
    imbalance: float | None = None
    er20: float | None = None
    fills: list = field(default_factory=list)
    order: object = None
    trigger_avail: datetime | None = None
    activate_at: datetime | None = None
    stress_per_share: float = 0.0

    @property
    def entry_avg(self) -> float | None:
        return self.entry_cost / self.qty if self.qty else None

    @property
    def exit_avg(self) -> float | None:
        return self.exit_value / self.exit_qty if self.exit_qty else None

    @property
    def open_qty(self) -> int:
        return self.qty - self.exit_qty

    def widened(self, mult: float = 1.5) -> float | None:
        """Net with every MARKETABLE fill's distance from the mid scaled by `mult` (passive fills at the limit are
        left as they are: a wider spread would only make them rarer)."""
        n = self.net()
        if n is None:
            return None
        extra = sum((mult - 1) * abs(f.price - dict(f.meta)["mid"]) * f.qty for f in self.fills
                    if dict(f.meta).get("mid") is not None)
        return n - extra

    def net(self) -> float | None:
        """Net rupees; None while any filled quantity is still open."""
        if self.qty == 0:
            return 0.0
        if self.open_qty > 0:
            return None
        return self.side * (self.exit_value - self.entry_cost) - self.fees


# ------------------------------------------------------------------ pure pieces
def select(cands: list[dict], cfg: SipConfig) -> list[dict]:
    """cands: dicts with instrument_id, rvol, atr, prev_close, open, close, high, low. Eligibility, then the top
    `top_n` by RVOL (ties by instrument id). Ranked before any breakout is looked at."""
    ok = [c for c in cands if c["rvol"] is not None and c["rvol"] >= cfg.rvol_min and c["atr"] and c["prev_close"]
          and c["atr"] / c["prev_close"] >= cfg.atr_pct_min]
    top = sorted(ok, key=lambda c: (-c["rvol"], c["instrument_id"]))[:cfg.top_n]
    out = []
    for c in top:
        d = (c["close"] > c["open"]) - (c["close"] < c["open"])
        if d != 0:
            out.append(c | {"side": d, "boundary": c["high"] if d > 0 else c["low"]})
    return out


def triggers(bar: ft.Bar, sel: dict, cfg: SipConfig) -> bool:
    day = bar.start.astimezone(cal.IST).date()
    if bar.start < datetime.combine(day, cfg.trigger_first_start, cal.IST) or \
            bar.end > datetime.combine(day, cfg.trigger_last_close, cal.IST):
        return False
    return bar.close > sel["boundary"] if sel["side"] > 0 else bar.close < sel["boundary"]


def equity_fee(side: int, price: float, qty: float, ts) -> float:
    d = ts.astimezone(cal.IST).date() if isinstance(ts, datetime) else ts
    return gcosts.equity_fill_fee(side, price, qty, d).total


def equity_fee_rest(side: int, price: float, qty: float, ts) -> float:
    """A later part of an order that already paid its brokerage: the fill's fees without brokerage and its GST."""
    return equity_fee(side, price, qty, ts) - gcosts.BROKERAGE * (1 + gcosts.GST)


# ------------------------------------------------------------------ the engine
class SipEngine:
    def __init__(self, cfg: SipConfig = SipConfig(), limits: rk.Limits = rk.LIMITS, sink=None):
        self.cfg, self.limits, self.sink = cfg, limits, sink
        self.ledger = lg.Ledger.new(f"{cfg.alpha_id}/{cfg.branch}/{cfg.scenario}", cfg.equity)
        self.risk = rk.RiskState(self.ledger.book)
        self.intents: list[Intent] = []
        self.execs: list[ExecutionEvent] = []
        self.log: list[tuple] = []
        self.day: date | None = None

    # -------------------------------------------------------- day lifecycle
    def start_day(self, day: date, universe: dict, vix: tuple = (None, None), vix_avail: datetime | None = None):
        self.day, self.universe = day, universe
        self.vix, self.vix_avail = vix, vix_avail
        self.bars: dict = {k: [] for k in universe}
        self.books: dict = {}
        self.selected: dict = {}
        self.opps: dict = {}
        self.selection_done = False
        self.selection_log: list = []
        self.ledger = lg.start_day(self.ledger, day.isoformat())
        self.risk = rk.start_day(self.risk, day.isoformat(), self._equity_worst())

    def _t(self, hhmm: time) -> datetime:
        return datetime.combine(self.day, hhmm, cal.IST)

    # -------------------------------------------------------- event handlers
    def on_clock(self, now: datetime) -> None:
        if not self.selection_done and now >= self._t(self.cfg.select_at) + timedelta(seconds=self.cfg.select_grace_s):
            self._select(now)
        for o in self.opps.values():
            if o.status == "triggered" and now > o.trigger_avail + timedelta(seconds=self.cfg.refresh_wait_s):
                o.status, o.reasons = "skipped", o.reasons + ("no book refresh in time",)
            if o.order is not None and not o.order.done and now > o.order.expires_at:
                self._record(o, o.order.expire())
            if o.status == "market_pending" and now > o.activate_at + timedelta(seconds=self.cfg.max_wait_s):
                o.status, o.reasons = "unfilled", o.reasons + ("no valid book after activation",)
                self._record(o, [ExecutionEvent.new(o.intent_id, 0, now, "expire", instrument_id=o.instrument_id,
                                                    side=o.side, scenario="market", reason="no valid quote in time")])
            if o.open_qty > 0 and o.exit_due_at is None and now >= self._t(self.cfg.time_exit):
                o.exit_due_at, o.exit_reason = self._t(self.cfg.time_exit), "time 15:15"

    def on_bar(self, bar: ft.Bar) -> None:
        if bar.instrument_id not in self.universe:
            return
        self.on_clock(bar.available_at)
        self.bars[bar.instrument_id].append(bar)
        sel = self.selected.get(bar.instrument_id)
        if sel is None or bar.instrument_id in self.opps or not triggers(bar, sel, self.cfg):
            return
        o = Opp(bar.instrument_id, sel["side"], sel["rvol"], sel["atr"], sel["boundary"], bar.end,
                trigger_avail=bar.available_at)
        o.er20 = ft.er20([b.close for b in self.bars[bar.instrument_id]])
        self.opps[bar.instrument_id] = o

    def on_book(self, inst: str, b: ex.Book) -> None:
        self.on_clock(b.ts)
        if inst not in self.universe:
            return
        keep = self.books.setdefault(inst, [])
        keep.append(b)
        cut = b.ts - timedelta(minutes=self.cfg.book_keep_min)
        while keep and keep[0].ts < cut:
            keep.pop(0)
        o = self.opps.get(inst)
        if o is None:
            return
        if o.status == "triggered" and b.ts >= o.trigger_avail:
            self._decide(o, b)
        elif o.order is not None and not o.order.done:
            self._record(o, o.order.on_book(b))
        elif o.status == "market_pending" and b.ts >= o.activate_at:
            self._market_entry(o, b)
        if o.open_qty > 0:
            self._manage(o, b)

    # -------------------------------------------------------- selection
    def _select(self, now: datetime) -> None:
        self.selection_done = True
        cands = []
        for inst, sd in self.universe.items():
            ow, ow_av = ft.opening_window(self.bars.get(inst, []), self.day, now)
            atr, _ = ft.atr14_wilder(sd.daily, now)
            pc, _ = ft.prev_close(sd.daily, now)
            if ow is None or atr is None or pc is None:
                self.selection_log.append((inst, "ineligible: missing window/ATR/close"))
                continue
            rv = ft.rvol(ow["volume"], sd.prior_windows, self.day, min_valid=self.cfg.rvol_min_windows)
            if rv is None:
                self.selection_log.append((inst, "ineligible: no 14 valid previous windows"))
                continue
            cands.append({"instrument_id": inst, "rvol": rv, "atr": atr, "prev_close": pc, **ow})
        for s in select(cands, self.cfg):
            self.selected[s["instrument_id"]] = s
        self.log.append(("select", now.isoformat(), sorted(self.selected)))

    # -------------------------------------------------------- entry
    def _exposures(self) -> tuple:
        out = []
        for o in self.opps.values():
            px = o.limit or (self.books[o.instrument_id][-1].mid if self.books.get(o.instrument_id) else None)
            pending = o.status in ("resting", "market_pending")
            q = o.qty_req if pending else o.open_qty
            if q <= 0 or px is None:
                continue
            last = self.books.get(o.instrument_id, [None])[-1]
            stale = last is None or not last.valid
            out.append(rk.Exposure(o.instrument_id, o.side * q * px, q * o.stress_per_share,
                                   self.universe[o.instrument_id].sector, stale=stale and o.open_qty > 0))
        return tuple(out)

    def _equity_worst(self) -> float:
        marks = {k: self.books[k][-1].mid for k in self.ledger.open_positions() if self.books.get(k)
                 and self.books[k][-1].valid}
        e = lg.equity(self.ledger, marks)
        return self.ledger.cash if e is None and not self.ledger.open_positions() else (e if e is not None else
                                                                                      self.ledger.start_cash)

    def _event_block(self, t: datetime) -> str:
        """Blueprint section 7: no entries on a Union Budget day; none 09:30-10:30 on an RBI policy day."""
        kinds = {k for d, k in cal.EVENTS if d == self.day}
        if "budget" in kinds:
            return "event day: Union Budget"
        if "rbi" in kinds and self._t(time(9, 30)) <= t <= self._t(time(10, 30)):
            return "event window: RBI policy"
        return ""

    def _decide(self, o: Opp, b: ex.Book) -> None:
        cfg = self.cfg
        o.decided_at = b.ts
        o.imbalance = ft.book_imbalance(b)
        blocked = self._event_block(b.ts)
        if blocked:
            o.status, o.reasons = "skipped", (blocked,)
            return
        if not b.valid:
            o.status, o.reasons = "skipped", ("invalid quote at decision",)
            return
        sd = self.universe[o.instrument_id]
        if cfg.branch == "P":
            raw = ex.passive_limit(o.side, o.boundary, b)
            o.limit = instruments.round_to_tick(raw, sd.tick, o.side)
            price = o.limit
        else:
            price = b.ask if o.side > 0 else b.bid
        stop_dist = cfg.stop_atr * o.atr
        friction = (b.ask - b.bid) / 2
        fee_ps = lambda q: (equity_fee(1, price, q, b.ts) + equity_fee(-1, price, q, b.ts)) / q  # noqa: E731
        reg = rk.regime_multiplier(*self.vix)
        cap = ex.capacity_qty(price, self.books.get(o.instrument_id, []), b.ts)
        q, L = rk.cash_qty(price, stop_dist, o.atr, self._equity_worst(), reg, friction, fee_ps,
                           replace(self.limits, ticket_max=cfg.ticket),
                           cash_cap=self.ledger.cash - self.ledger.reserved, volume_cap=int(cap))
        o.stress_per_share = L if q else stop_dist
        if q == 0:
            o.status, o.reasons = "skipped", ("size 0 (risk/ticket/capacity/regime)",)
            return
        cand = rk.Exposure(o.instrument_id, o.side * q * price, q * L, sd.sector)
        q2, why = rk.approve_cash(cand, price, q, L, rk.BookView(self._equity_worst(), self._exposures()),
                                  self.risk, self.limits)
        if q2 == 0:
            o.status, o.reasons = "skipped", why
            return
        o.qty_req, o.reasons = q2, why
        act = b.ts + timedelta(seconds=cfg.latency_s)
        exp = min(b.ts + timedelta(seconds=cfg.expire_s), self._t(cfg.entry_expire_by))
        o.activate_at = act
        it = Intent(make_id("in", cfg.alpha_id, cfg.branch, cfg.scenario, self.day, o.instrument_id), cfg.alpha_id,
                    b.ts, (Leg(o.instrument_id, o.side, q2, o.limit, "EQ", "entry"),), act, max(exp, act),
                    StopRule(None, self._t(cfg.time_exit)), q2 * L, (), cfg.protocol_hash, cfg.branch,
                    (("rvol", round(o.rvol, 6)), ("atr", round(o.atr, 6)), ("boundary", o.boundary),
                     ("imbalance", None if o.imbalance is None else round(o.imbalance, 6)),
                     ("er20", None if o.er20 is None or o.er20 != o.er20 else round(o.er20, 6)),
                     ("scenario", cfg.scenario), ("exploratory", cfg.exploratory)))
        o.intent_id = it.intent_id
        self.intents.append(it)
        if self.sink is not None:
            self.sink.append_intent(it)
        if cfg.branch == "P":
            o.order = ex.PassiveOrder(it.intent_id, 0, o.instrument_id, o.side, q2, o.limit, sd.tick, act,
                                      max(exp, act), equity_fee, cfg.scenario, arrival_book=b,
                                      fee_fn_rest=equity_fee_rest)
            o.status = "resting"
        else:
            o.status = "market_pending"

    def _market_entry(self, o: Opp, b: ex.Book) -> None:
        if not b.valid:
            return
        e = ex.market_fill(o.intent_id, 0, o.instrument_id, o.side, o.qty_req, [b], o.activate_at, equity_fee,
                           max_wait_s=self.cfg.max_wait_s)
        if e.kind == "expire":
            return
        self._record(o, [e])
        if e.kind != "fill":
            o.status = "unfilled"

    # -------------------------------------------------------- fills and exits
    def _record(self, o: Opp, evs: list[ExecutionEvent]) -> None:
        for e in evs:
            self.execs.append(e)
            if self.sink is not None:
                self.sink.append_execution(e)
            if e.kind == "fill" and e.leg_index == 0:
                o.qty += e.qty
                o.entry_cost += e.qty * e.price
                o.fees += e.fee
                o.fills.append(e)
                o.stop = o.entry_avg - o.side * self.cfg.stop_atr * o.atr
                o.status = "positioned"
            elif e.kind in ("fill", "exit") and e.leg_index == 1:
                o.exit_qty += e.qty
                o.exit_value += e.qty * e.price
                o.fees += e.fee
                o.fills.append(e)
                if o.open_qty == 0:
                    o.status = "closed"
            elif e.kind == "expire" and o.qty == 0:
                o.status = "unfilled"
            self.ledger = lg.apply_event(self.ledger, e)
        if evs:
            self.risk = rk.update(self.risk, self.ledger.day_realized_net, self._equity_worst(), self.limits)

    def _manage(self, o: Opp, b: ex.Book) -> None:
        if not b.valid:
            return
        if o.exit_due_at is None and o.stop is not None:
            hit = b.bid <= o.stop if o.side > 0 else b.ask >= o.stop
            if hit:
                o.stop_hit_at = b.ts
                o.exit_due_at, o.exit_reason = b.ts + timedelta(seconds=self.cfg.latency_s), "stop"
                if o.order is not None and not o.order.done:      # the unfilled rest of the entry is cancelled
                    o.order.done = True
                    self._record(o, [ExecutionEvent.new(o.intent_id, 0, b.ts, "cancel", instrument_id=o.instrument_id,
                                                        side=o.side, qty=int(o.order.left), reason="stop hit")])
                return
        if o.exit_due_at is not None and b.ts >= o.exit_due_at:
            w = ex.walk(b, -o.side, o.open_qty)
            if w.qty <= 0:
                return
            e = ExecutionEvent.new(o.intent_id, 1, b.ts, "exit", instrument_id=o.instrument_id, side=-o.side,
                                   qty=int(w.qty), price=w.avg_price, fee=equity_fee(-o.side, w.avg_price, w.qty, b.ts),
                                   scenario=self.cfg.scenario if self.cfg.branch == "P" else "market",
                                   reason=o.exit_reason, meta=(("impact_bp", round(w.impact_bp, 4)),
                                                               ("over_cap", w.impact_bp > ex.IMPACT_MAX_BP),
                                                               ("mid", b.mid)))
            self._record(o, [e])

    # -------------------------------------------------------- results
    def end_day(self) -> dict:
        rows, total, unresolved = [], 0.0, []
        for inst in sorted(self.opps):
            o = self.opps[inst]
            if o.order is not None and not o.order.done:
                self._record(o, o.order.expire())
            n = o.net()
            mk = {}
            if o.fills:
                f0 = o.fills[0]
                mk = ex.markouts(f0.ts, f0.price, o.side, self.books.get(inst, []))
            if n is None:                                          # open legs without a valid exit: bounds only
                done = o.side * (o.exit_value - o.entry_avg * o.exit_qty) - o.fees
                worst = done - o.open_qty * o.stress_per_share
                valid = [b for b in self.books.get(inst, []) if b.valid]
                last = valid[-1].mid if valid else o.entry_avg
                best = done + o.open_qty * max(0.0, o.side * (last - o.entry_avg))
                unresolved.append((inst, worst, best))
            rows.append({"instrument_id": inst, "side": o.side, "status": o.status, "rvol": o.rvol, "atr": o.atr,
                         "decided_at": o.decided_at.isoformat() if o.decided_at else None, "limit": o.limit,
                         "qty_req": o.qty_req, "qty": o.qty, "entry": o.entry_avg, "exit": o.exit_avg,
                         "exit_reason": o.exit_reason, "fees": o.fees, "net": n, "net_widened": o.widened(),
                         "reasons": list(o.reasons),
                         "notional": (o.entry_avg or 0.0) * o.qty, "markout": mk, "imbalance": o.imbalance,
                         "er20": o.er20})
            total += n or 0.0
        widened = sum(r["net_widened"] or 0.0 for r in rows)
        return {"day": self.day.isoformat(), "branch": self.cfg.branch, "scenario": self.cfg.scenario,
                "selected": sorted(self.selected), "opportunities": rows, "net": total, "net_widened": widened,
                "unresolved": unresolved, "net_worst": total + sum(w for _, w, _ in unresolved),
                "net_best": total + sum(b for _, _, b in unresolved),
                "bp_of_equity": total / self.cfg.equity * 1e4, "exploratory": self.cfg.exploratory,
                "risk": self.risk.to_dict()}

    def fingerprint(self) -> str:
        """Hash of every intent and execution event: replay and live must agree byte for byte."""
        import hashlib
        return hashlib.sha256(canonical_json([self.intents, self.execs]).encode()).hexdigest()
