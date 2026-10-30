"""Risk and portfolio rules (blueprint section 7; A section 10). Pure functions.

Caps are checked against the WORST of filled and requested exposure: pending intents count at their full requested
size, so a partial fill can never open room for a second entry, and a position without a valid mark blocks new
entries (bad data = no entry). Latches (DG, day loss, drawdown pause) live in RiskState, which is persisted per book.
The DG decision for the six existing accounts is not here: that is the main session's.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace


@dataclass(frozen=True)
class Limits:
    risk_per_trade: float = 0.0025        # cash: base risk 0.25% of equity
    stress_atr: float = 0.25              # stress loss = stop + 0.25 ATR + friction + fees
    ticket_max: float = 100_000.0         # SIP / NEWS ticket
    max_open: int = 4
    gross_max: float = 1.00
    net_max: float = 0.50
    stock_max: float = 0.20
    sector_max: float = 0.30
    cash_stress_max: float = 0.010
    option_reserve_max: float = 0.010
    overnight_reserve_max: float = 0.005
    short_vol_max: float = 0.005          # OVN + RANGE together
    total_stress_max: float = 0.015
    cluster_max: float = 0.005
    corr_edge: float = 0.70
    day_loss_latch: float = 0.015
    drawdown_pause: float = 0.05
    dg_r0: float = 0.0025                 # DG reference risk: 0.25% of start-of-day equity
    dg_peak_mult: float = 2.0
    dg_giveback: float = 0.5


LIMITS = Limits()


def regime_multiplier(vix_prev: float | None, vix_rise5: float | None, short_vol: bool = False) -> float:
    """VIX <= 20: 1; (20, 25]: 0.5; > 25 or up > 20% in 5 sessions: 0.25 (cash) / 0 (new short volatility).
    Unknown VIX is bad data: 0."""
    if vix_prev is None or vix_rise5 is None or not math.isfinite(vix_prev) or not math.isfinite(vix_rise5):
        return 0.0
    if vix_prev > 25 or vix_rise5 > 0.20:
        return 0.0 if short_vol else 0.25
    return 0.5 if vix_prev > 20 else 1.0


# ------------------------------------------------------------------ latches
@dataclass(frozen=True)
class RiskState:
    book: str
    day: str = ""
    start_equity: float = 0.0             # start of the current day
    equity_high: float = 0.0              # running high of end-of-update equity (worst bound)
    dg_peak: float = 0.0                  # H: the day's peak realized net P&L
    dg_latched: bool = False
    day_loss_latched: bool = False
    paused: bool = False                  # drawdown pause: only a review clears it
    reasons: tuple = ()

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "RiskState":
        return RiskState(**{**d, "reasons": tuple(d.get("reasons", ()))})


def start_day(state: RiskState, day: str, equity: float) -> RiskState:
    """New session: the DG and day-loss latches reset; the drawdown pause does not."""
    if state.day == day:
        return state                                          # a restart within the day keeps its latches
    return replace(state, day=day, start_equity=equity, equity_high=max(state.equity_high, equity), dg_peak=0.0,
                   dg_latched=False, day_loss_latched=False)


def update(state: RiskState, realized_day_net: float, equity_worst: float, limits: Limits = LIMITS) -> RiskState:
    """After every fill or mark: DG (H >= 2 r0 and C <= 0.5 H), the day-loss latch (equity loss incl. marks and
    reserves >= 1.5% of the day's start) and the drawdown pause (>= 5% below the running high)."""
    r0 = limits.dg_r0 * state.start_equity
    h = max(state.dg_peak, realized_day_net)
    reasons = list(state.reasons)
    dg = state.dg_latched or (h >= limits.dg_peak_mult * r0 and realized_day_net <= limits.dg_giveback * h and h > 0)
    if dg and not state.dg_latched:
        reasons.append(f"DG latched: peak {h:.0f}, now {realized_day_net:.0f}")
    dl = state.day_loss_latched or (state.start_equity - equity_worst >= limits.day_loss_latch * state.start_equity)
    if dl and not state.day_loss_latched:
        reasons.append(f"day-loss latch at equity {equity_worst:.0f}")
    high = max(state.equity_high, equity_worst)
    paused = state.paused or (high - equity_worst >= limits.drawdown_pause * high)
    if paused and not state.paused:
        reasons.append(f"drawdown pause at equity {equity_worst:.0f} (high {high:.0f})")
    return replace(state, dg_peak=h, dg_latched=dg, day_loss_latched=dl, paused=paused, equity_high=high,
                   reasons=tuple(reasons))


def review_resume(state: RiskState, equity: float) -> RiskState:
    """An explicit review (a new authorized paper epoch) clears the pause and restarts the running high."""
    return replace(state, paused=False, equity_high=equity, reasons=state.reasons + ("resumed after review",))


def can_enter(state: RiskState) -> tuple[bool, str]:
    if state.paused:
        return False, "paused (drawdown)"
    if state.day_loss_latched:
        return False, "day-loss latch"
    if state.dg_latched:
        return False, "DG latch"
    return True, ""


# ------------------------------------------------------------------ exposure
@dataclass(frozen=True)
class Exposure:
    """One open or pending risk in the book (pending = requested size, filled or not)."""
    instrument_id: str
    notional: float = 0.0                 # signed rupees (cash)
    stress_loss: float = 0.0              # rupees (cash: qty x L)
    sector: str = ""
    kind: str = "cash"                    # "cash" | "option"
    reserve: float = 0.0                  # option structural max-loss reserve
    overnight: bool = False
    short_vol: bool = False
    stale: bool = False                   # no valid mark now


@dataclass(frozen=True)
class BookView:
    equity: float
    exposures: tuple = ()
    corr: dict = field(default_factory=dict, hash=False)     # (a, b) -> correlation (shrunk), either order


def clusters(items: list[Exposure], corr: dict, edge: float = 0.70) -> dict:
    """instrument_id -> cluster id: connected components of 'same sector or correlation >= edge'."""
    ids = [x.instrument_id for x in items]
    parent = {i: i for i in ids}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a in items:
        for b in items:
            if a.instrument_id >= b.instrument_id:
                continue
            rho = corr.get((a.instrument_id, b.instrument_id), corr.get((b.instrument_id, a.instrument_id)))
            if (a.sector and a.sector == b.sector) or (rho is not None and rho >= edge):
                parent[find(a.instrument_id)] = find(b.instrument_id)
    return {i: find(i) for i in ids}


def cash_qty(price: float, stop_distance: float, atr: float, equity: float, regime: float, friction_per_share: float,
             fee_per_share, limits: Limits = LIMITS, cash_cap: float | None = None,
             depth_cap: int | None = None, volume_cap: int | None = None) -> tuple[int, float]:
    """A section 10: q = floor(min(b/L, ticket/price, cash, depth, volume)) with L = stop + 0.25 ATR + friction + fee
    per share; fees depend on q (fixed brokerage), so q is reduced until b/L holds. Returns (q, L at q)."""
    b = limits.risk_per_trade * equity * regime
    if b <= 0 or price <= 0 or stop_distance <= 0:
        return 0, math.nan
    caps = [limits.ticket_max / price]
    if cash_cap is not None:
        caps.append(cash_cap / price)
    if depth_cap is not None:
        caps.append(depth_cap)
    if volume_cap is not None:
        caps.append(volume_cap)
    base = stop_distance + limits.stress_atr * atr + friction_per_share
    q = int(math.floor(min(caps + [b / base])))
    while q > 0:
        L = base + fee_per_share(q)
        if q * L <= b + 1e-9:
            return q, L
        q -= 1
    return 0, math.nan


def approve_cash(cand: Exposure, price: float, qty: int, stress_per_share: float, book: BookView, state: RiskState,
                 limits: Limits = LIMITS) -> tuple[int, tuple[str, ...]]:
    """Largest qty <= the requested qty that keeps every portfolio cap; (0, reasons) if none. Partial size allowed."""
    ok, why = can_enter(state)
    if not ok:
        return 0, (why,)
    if any(x.stale for x in book.exposures):
        return 0, ("an open position has no valid mark",)
    E = book.equity
    cash = [x for x in book.exposures if x.kind == "cash"]
    if len(cash) + 1 > limits.max_open:
        return 0, ("max open positions",)
    side = 1 if cand.notional >= 0 else -1
    room = {"requested": float(qty)}
    gross = sum(abs(x.notional) for x in cash)
    room["gross"] = (limits.gross_max * E - gross) / price
    net = sum(x.notional for x in cash)
    room["net"] = (limits.net_max * E - side * net) / price
    same = sum(abs(x.notional) for x in cash if x.instrument_id == cand.instrument_id)
    room["stock"] = (limits.stock_max * E - same) / price
    if cand.sector:
        sec = sum(abs(x.notional) for x in cash if x.sector == cand.sector)
        room["sector"] = (limits.sector_max * E - sec) / price
    stress = sum(x.stress_loss for x in cash)
    room["cash stress"] = (limits.cash_stress_max * E - stress) / stress_per_share
    allstress = stress + sum(x.reserve for x in book.exposures if x.kind == "option")
    room["total stress"] = (limits.total_stress_max * E - allstress) / stress_per_share
    probe = replace(cand, notional=side * price, stress_loss=stress_per_share)
    cl = clusters(cash + [probe], book.corr, limits.corr_edge)
    mine = cl[cand.instrument_id]
    cl_stress = sum(x.stress_loss for x in cash if cl[x.instrument_id] == mine)
    room["cluster"] = (limits.cluster_max * E - cl_stress) / stress_per_share
    q = int(math.floor(min(room.values()) + 1e-9))
    if q < 1:
        binding = min(room, key=room.get)
        return 0, (f"cap: {binding}",)
    binding = tuple(f"reduced by {k}" for k, v in room.items() if k != "requested" and math.floor(v + 1e-9) < qty
                    and math.floor(v + 1e-9) == q)
    return q, binding


def approve_option(cand: Exposure, book: BookView, state: RiskState, budget: float,
                   limits: Limits = LIMITS) -> tuple[bool, tuple[str, ...]]:
    """One defined-risk structure: its reserve (max loss + entry fees + exit-fee reserve) <= budget, and the option,
    overnight, short-volatility and total stress caps hold."""
    ok, why = can_enter(state)
    if not ok:
        return False, (why,)
    if any(x.stale for x in book.exposures):
        return False, ("an open position has no valid mark",)
    E = book.equity
    opt = [x for x in book.exposures if x.kind == "option"]
    checks = {"budget": cand.reserve <= budget + 1e-9,
              "option reserves": sum(x.reserve for x in opt) + cand.reserve <= limits.option_reserve_max * E + 1e-9,
              "total stress": sum(x.reserve for x in opt) + sum(x.stress_loss for x in book.exposures
                                                                if x.kind == "cash") + cand.reserve
              <= limits.total_stress_max * E + 1e-9}
    if cand.overnight:
        checks["overnight reserves"] = (sum(x.reserve for x in opt if x.overnight) + cand.reserve
                                        <= limits.overnight_reserve_max * E + 1e-9)
    if cand.short_vol:
        checks["short-volatility cap"] = (sum(x.reserve for x in opt if x.short_vol) + cand.reserve
                                          <= limits.short_vol_max * E + 1e-9)
    bad = tuple(f"cap: {k}" for k, v in checks.items() if not v)
    return (not bad), bad
