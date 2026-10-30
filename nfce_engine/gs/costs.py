"""Per-fill fees by effective date (blueprint section 3; A section 4.4). Wraps the frozen `nfce/costs.py` unchanged.

Every fill is charged on its own side and value: a buy pays stamp duty, a sale pays STT, both pay the exchange charge,
the SEBI fee, the brokerage of that one order and GST on (brokerage + exchange + SEBI). Entry and exit fills can fall
under different schedules, so each fill takes its own date.

Options and futures: the frozen round-trip functions are linear in buy and sell value, so one side is obtained exactly
by calling them with the other side at zero and one order (`option_fill_fee(buy) + option_fill_fee(sell)` equals the
frozen `option_fees(buy, sell, orders=2)` to the paisa; a test checks it).

Cash equity intraday (the Upstox tariff, to be re-checked against Upstox's official page before any test is locked):
STT 0.025% sell side, NSE 0.00322% each side (study2's figure; NSE's IPFT-inclusive rate is not verified here),
SEBI Rs 10/crore, stamp 0.003% buy side, brokerage Rs 20 per order (BROKERAGE_RULE = "flat20"; "min20_0.03pct" is the
Zerodha-type rule study2 used), GST 18%.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce import costs as frozen  # noqa: E402

GST = frozen.GST
SEBI_FEE = frozen.SEBI_FEE
EQ_STT_INTRADAY = 0.00025
EQ_EXCH = 0.0000322
EQ_STAMP = 0.00003
BROKERAGE = 20.0
BROKERAGE_RULE = "flat20"
TARIFF_VERSION = "gs-fees-2026-10-26"


@dataclass(frozen=True)
class Fee:
    stt: float
    exchange: float
    sebi: float
    stamp: float
    brokerage: float
    gst: float

    @property
    def total(self) -> float:
        return self.stt + self.exchange + self.sebi + self.stamp + self.brokerage + self.gst

    def __add__(self, o: "Fee") -> "Fee":
        return Fee(*(a + b for a, b in zip(self._t(), o._t())))

    def _t(self):
        return (self.stt, self.exchange, self.sebi, self.stamp, self.brokerage, self.gst)


ZERO = Fee(0, 0, 0, 0, 0, 0)


def _from(b: frozen.CostBreakdown) -> Fee:
    return Fee(b.stt, b.exchange, b.sebi, b.stamp, b.brokerage, b.gst)


def option_fill_fee(side: int, price: float, qty: float, when: date, brokerage: float = BROKERAGE) -> Fee:
    """One option fill: side +1 buy, -1 sell; qty in units (lots x lot size); one order."""
    if qty <= 0 or price < 0:
        raise ValueError("qty must be > 0 and price >= 0")
    b = frozen.option_fees(price, 0.0, qty, when, 1, brokerage) if side > 0 else \
        frozen.option_fees(0.0, price, qty, when, 1, brokerage)
    return _from(b)


def futures_fill_fee(side: int, price: float, qty: float, when: date, brokerage: float = BROKERAGE) -> Fee:
    """One futures fill (side +1 buy, -1 sell), one order."""
    if qty <= 0 or price <= 0:
        raise ValueError("qty and price must be > 0")
    b = frozen.futures_fees(price, 0.0, 1, qty, when, 1, brokerage) if side > 0 else \
        frozen.futures_fees(0.0, price, 1, qty, when, 1, brokerage)
    return _from(b)


def equity_fill_fee(side: int, price: float, qty: float, when: date, rule: str = BROKERAGE_RULE) -> Fee:
    """One cash-equity intraday fill (side +1 buy, -1 sell), one order."""
    if qty <= 0 or price <= 0:
        raise ValueError("qty and price must be > 0")
    v = price * qty
    brk = BROKERAGE if rule == "flat20" else min(BROKERAGE, 0.0003 * v)
    exch, sebi = EQ_EXCH * v, SEBI_FEE * v
    stt = EQ_STT_INTRADAY * v if side < 0 else 0.0
    stamp = EQ_STAMP * v if side > 0 else 0.0
    return Fee(stt, exch, sebi, stamp, brk, GST * (brk + exch + sebi))


def round_trip_equity_bp(price: float, qty: float, when: date) -> float:
    """Fees of a buy and a sell at the same price, in bp of the notional (a planning figure)."""
    f = equity_fill_fee(1, price, qty, when).total + equity_fill_fee(-1, price, qty, when).total
    return f / (price * qty) * 1e4
