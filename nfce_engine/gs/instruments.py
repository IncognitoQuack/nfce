"""Lot size, tick size and strike step by effective date (blueprint section 3; A: "no hard-coded 65/50").

Each entry is (root, kind, effective_from, lot, tick, strike_step, source). A lookup before the first known entry
raises: an unknown lot is a data failure, never a default. Cash equity trades in shares (lot 1, tick 0.05 for most
F&O stocks; tick 0.01 below Rs 250 is NOT assumed here, callers pass the tick from the instrument master when they
have it).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Spec:
    root: str
    kind: str              # "OPT" | "FUT" | "EQ"
    effective_from: date
    lot: int
    tick: float
    strike_step: float | None
    source: str


_SPECS = (
    Spec("NIFTY", "OPT", date(2026, 1, 1), 65, 0.05, 50.0,
         "nfce_bridge/data/instruments_NSE.json (NIFTY FUT lot 65), recorded chains (50-pt strikes), 26 Oct 2026"),
    Spec("NIFTY", "FUT", date(2026, 1, 1), 65, 0.10, None, "nfce_bridge/data/instruments_NSE.json, 26 Oct 2026"),
    Spec("BANKNIFTY", "OPT", date(2026, 1, 1), 30, 0.05, 100.0, "ops/pull_daily.py lot table, 26 Oct 2026"),
)


class UnknownInstrument(LookupError):
    pass


def spec(root: str, kind: str, on: date) -> Spec:
    xs = [s for s in _SPECS if s.root == root and s.kind == kind and s.effective_from <= on]
    if not xs:
        raise UnknownInstrument(f"no {root} {kind} spec effective on {on}")
    return max(xs, key=lambda s: s.effective_from)


def lot_size(root: str, on: date, kind: str = "OPT") -> int:
    return spec(root, kind, on).lot


def round_to_tick(price: float, tick: float, side: int) -> float:
    """Round a limit price against aggressiveness: a buy rounds DOWN, a sell rounds UP (A section 6)."""
    import math
    n = price / tick
    k = math.floor(n + 1e-9) if side > 0 else math.ceil(n - 1e-9)
    return round(k * tick, 10)


def equity(symbol: str, tick: float = 0.05) -> Spec:
    return Spec(symbol, "EQ", date(1900, 1, 1), 1, tick, None, "cash equity, shares")
