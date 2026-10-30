"""Portfolio risk for the paper books, the way a desk risk screen does it (read-only; used by ops/desk.py).

* Marks: a long option is marked at the bid, a short at the ask (what closing would actually get), falling back to the
  last trade only when the book side is missing, and flagged as such.
* Greeks per position = Upstox's live option Greeks (stream feed, per unit) × units × side.
* Scenarios: P&L ≈ Δ·dS + ½·Γ·dS² + vega·dIV for spot moves of ±1/2/3% and IV moves of −5/+5/+10 vol points
  (the standard second-order Greeks approximation; it understates very large gaps, which the grid labels).
"""
from __future__ import annotations

from dataclasses import dataclass, field

SPOT_MOVES = (-0.03, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03)
IV_MOVES = (-5.0, 0.0, 5.0, 10.0)


@dataclass
class Tick:
    ltp: float | None = None
    bid: float | None = None
    ask: float | None = None
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    vega: float | None = None
    theta: float | None = None
    recv_ts: str | None = None


@dataclass
class PositionRisk:
    acct: str
    symbol: str
    key: str
    under_key: str
    units: int                     # signed: + long, - short
    entry: float
    mark: float | None = None
    mark_source: str = "none"      # bid / ask / last / none
    unrealized: float | None = None
    spot: float | None = None
    delta: float | None = None     # position delta, in underlying units
    gamma: float | None = None
    vega: float | None = None      # ₹ per 1 vol point
    theta: float | None = None     # ₹ per day
    notes: list = field(default_factory=list)
    sid: str = ""                    # the account position's id (the desk's Close button)
    peak_unrealized: float | None = None   # best open P&L since entry, at the bid (stream ticks)
    giveback: float | None = None          # peak_unrealized - unrealized
    recv_ts: str | None = None             # when the option's latest stream tick arrived (freshness)
    opened: str | None = None              # when the position was bought (time in trade)


def mark_of(units: int, t: Tick | None) -> tuple[float | None, str]:
    if t is None:
        return None, "none"
    side_px = t.bid if units > 0 else t.ask
    if side_px and side_px > 0:
        return float(side_px), "bid" if units > 0 else "ask"
    if t.ltp and t.ltp > 0:
        return float(t.ltp), "last"
    return None, "none"


def position_risk(acct: str, pos: dict, opt: Tick | None, under: Tick | None) -> PositionRisk:
    """pos: an account_positions state (key, under_key, symbol, side, rem_lots or lots, lot_units, entry).
    The accounts only BUY options: `side` is the underlying signal's direction (a SELL buys a put), never a short."""
    lots = pos.get("rem_lots", pos.get("lots", 0)) or 0
    units = int(lots) * int(pos.get("lot_units", 1))
    r = PositionRisk(acct, pos.get("symbol", ""), pos.get("key", ""), pos.get("under_key", ""), units,
                     float(pos.get("entry", 0.0)))
    r.sid = str(pos.get("sid", ""))
    r.opened = pos.get("opened")
    r.mark, r.mark_source = mark_of(units, opt)
    r.recv_ts = getattr(opt, "recv_ts", None) if opt is not None else None
    if r.mark is not None:
        r.unrealized = (r.mark - r.entry) * units
    if r.mark_source == "last":
        r.notes.append("marked at last trade (no book side)")
    r.spot = under.ltp if under and under.ltp else None
    if opt is not None and opt.delta is not None:
        r.delta = opt.delta * units
        r.gamma = (opt.gamma or 0.0) * units
        r.vega = (opt.vega or 0.0) * units
        r.theta = (opt.theta or 0.0) * units
    else:
        r.notes.append("no live Greeks: excluded from scenarios")
    return r


def scenario_grid(positions: list[PositionRisk], spot_moves=SPOT_MOVES, iv_moves=IV_MOVES) -> dict:
    """{(spot_move, iv_move): P&L ₹} summed over positions with Greeks and a spot. Plus which positions were left out."""
    grid = {}
    used = [p for p in positions if p.delta is not None and p.spot]
    for m in spot_moves:
        for v in iv_moves:
            total = 0.0
            for p in used:
                ds = p.spot * m
                total += p.delta * ds + 0.5 * p.gamma * ds * ds + p.vega * v
            grid[(m, v)] = total
    return {"grid": grid, "included": len(used), "excluded": [p.symbol for p in positions if p not in used]}


def exposure(positions: list[PositionRisk]) -> dict:
    """Net delta in ₹ (Δ × spot) and premium at risk, by underlying, and totals."""
    by: dict = {}
    for p in positions:
        e = by.setdefault(p.under_key or p.symbol, {"delta_rs": 0.0, "premium": 0.0, "positions": 0})
        e["positions"] += 1
        if p.delta is not None and p.spot:
            e["delta_rs"] += p.delta * p.spot
        if p.mark is not None:
            e["premium"] += abs(p.mark * p.units)
    tot = {"delta_rs": sum(e["delta_rs"] for e in by.values()), "premium": sum(e["premium"] for e in by.values()),
           "vega": sum(p.vega or 0.0 for p in positions), "theta": sum(p.theta or 0.0 for p in positions),
           "unrealized": sum(p.unrealized or 0.0 for p in positions)}
    return {"by_underlying": by, "total": tot}
