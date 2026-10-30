"""Dated Indian F&O transaction-cost schedule (NSE, Zerodha-type flat brokerage). Pure functions, no I/O.

This file is kept byte-identical in nfce_engine/nfce/costs.py and nfce_bridge/bridge/costs.py (a test checks it).

Rates, by effective date. "verified" = checked against a primary source on 18 Oct 2026 (independent review
sources S1-S3: NSE STT page updated 17 Apr 2026, NSE circular FA73061, Zerodha charges page).
"approx" = commonly published broker figure, NOT independently verified: treat older-period costs as estimates.

  STT futures (sell side, % of notional): 0.0100% (approx, before 2023-04-01), 0.0125% (approx, from 2023-04-01),
                                         0.0200% (approx, from 2024-10-01), 0.0500% (verified, from 2026-04-01)
  STT options (sell side, % of premium): 0.0500% / 0.0625% / 0.1000% / 0.1500% (same dates; last verified)
  NSE transaction charge, futures (each side): 0.00190% (approx), 0.00173% (approx, from 2024-10-01),
                                              0.00183% incl. IPFT (verified, from 2026-03-01)
  NSE transaction charge, options (each side, on premium): 0.05000% (approx), 0.03503% (approx, from 2024-10-01),
                                                          0.03553% (verified, from 2026-03-01)
  SEBI turnover fee: Rs 10 per crore each side (verified).   Stamp duty (buy side): futures 0.002%, options 0.003%.
  GST: 18% on brokerage + exchange charge + SEBI fee.        Brokerage: Rs 20 per executed order (configurable).
Execution friction (spread/slippage) is NOT a fee and is passed separately, in index points.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

_FUT_STT = [(date(1900, 1, 1), 0.000100), (date(2023, 4, 1), 0.000125), (date(2024, 10, 1), 0.000200),
            (date(2026, 4, 1), 0.000500)]
_OPT_STT = [(date(1900, 1, 1), 0.000500), (date(2023, 4, 1), 0.000625), (date(2024, 10, 1), 0.001000),
            (date(2026, 4, 1), 0.001500)]
_FUT_EXCH = [(date(1900, 1, 1), 0.0000190), (date(2024, 10, 1), 0.0000173), (date(2026, 3, 1), 0.0000183)]
_OPT_EXCH = [(date(1900, 1, 1), 0.000500), (date(2024, 10, 1), 0.0003503), (date(2026, 3, 1), 0.0003553)]
SEBI_FEE = 0.000001          # Rs 10 / crore
STAMP_FUT = 0.00002
STAMP_OPT = 0.00003
GST = 0.18
CURRENT = date(2026, 10, 18)  # "current-cost stress" uses the schedule in force on this date


def _rate(table, when: date) -> float:
    r = table[0][1]
    for d, v in table:
        if when >= d:
            r = v
    return r


@dataclass(frozen=True)
class CostBreakdown:
    stt: float
    exchange: float
    sebi: float
    stamp: float
    brokerage: float
    gst: float

    @property
    def total(self) -> float:
        return self.stt + self.exchange + self.sebi + self.stamp + self.brokerage + self.gst


def futures_fees(entry: float, exit_: float, side: int, units: float, when: date, orders: int = 2,
                 brokerage_per_order: float = 20.0) -> CostBreakdown:
    """Rupee fees for one futures round trip of `units` (lot size x lots). side +1 long / -1 short."""
    buy_px, sell_px = (entry, exit_) if side > 0 else (exit_, entry)
    buy_val, sell_val = buy_px * units, sell_px * units
    stt = _rate(_FUT_STT, when) * sell_val
    exch = _rate(_FUT_EXCH, when) * (buy_val + sell_val)
    sebi = SEBI_FEE * (buy_val + sell_val)
    stamp = STAMP_FUT * buy_val
    brk = brokerage_per_order * orders
    return CostBreakdown(stt, exch, sebi, stamp, brk, GST * (brk + exch + sebi))


def option_fees(entry_prem: float, exit_prem: float, units: float, when: date, orders: int = 2,
                brokerage_per_order: float = 20.0) -> CostBreakdown:
    """Rupee fees for BUYING an option and selling it back (no exercise)."""
    buy_val, sell_val = entry_prem * units, exit_prem * units
    stt = _rate(_OPT_STT, when) * sell_val
    exch = _rate(_OPT_EXCH, when) * (buy_val + sell_val)
    sebi = SEBI_FEE * (buy_val + sell_val)
    stamp = STAMP_OPT * buy_val
    brk = brokerage_per_order * orders
    return CostBreakdown(stt, exch, sebi, stamp, brk, GST * (brk + exch + sebi))


def futures_cost_points(entry: float, avg_exit: float, side: int, when: date, lot_units: int, lots: int = 1,
                        orders: int = 2, friction_pts_per_side: float = 0.0, brokerage_per_order: float = 20.0) -> float:
    """All-in round-trip cost in index points per unit: fees (amortised over lots) + execution friction."""
    units = lot_units * lots
    fees = futures_fees(entry, avg_exit, side, units, when, orders, brokerage_per_order).total
    return fees / units + 2 * friction_pts_per_side
