"""Execute underlying signals through options, from REAL option quotes (registered experiment R1).

Fixed, pre-registered rules (independent review, experiment 1):
  * BUY signal -> buy a call, SELL signal -> buy a put; whole lot, all-in / all-out, no partial exits.
  * Strike: the nearest listed strike strictly in the money on the underlying price at the decision time
    (call: highest strike below spot; put: lowest strike above spot).
  * Expiry: the nearest listed expiry with at least `min_sessions_left` trading sessions remaining (default 2).
  * Entry: the first quote at or after decision time + `delay_s` (default 5 s), at the ASK.
  * Exit: the first quote at or after the underlying exit decision, at the BID.
  * Fees: nfce.costs.option_fees on the trade date (STT on sell premium, exchange, SEBI, stamp, GST, Rs 20/order).
  * A trade is SKIPPED (counted, never imputed) if no quote exists within `max_quote_gap_s`, or bid/ask is missing.
  * Chronology (FIX, review round 3, H01): decision <= entry fill <= exit fill, both on the decision's session. A signal
    whose exit decision comes before the entry could be filled is skipped, never booked.
  * Quotes must be finite, positive and uncrossed (ask >= bid); others are ignored.
  * Stress: net with both spreads widened 1.5x (half a spread worse at entry and at exit, quarter each side).
No theta is subtracted separately: real premium changes already contain it.

Quote input: DataFrame with columns time (tz-aware), expiry (date), strike, type ('CE'/'PE'), bid, ask.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from . import costs


@dataclass
class OptionFill:
    signal_time: pd.Timestamp
    side: int
    strike: float
    opt_type: str
    expiry: date
    entry_time: pd.Timestamp | None
    entry_ask: float | None
    exit_time: pd.Timestamp | None
    exit_bid: float | None
    fees_inr: float = 0.0
    lot_units: int = 65
    skipped: str = ""
    spread_in: float = 0.0
    spread_out: float = 0.0

    @property
    def net_inr(self) -> float:
        if self.skipped:
            return 0.0
        return (self.exit_bid - self.entry_ask) * self.lot_units - self.fees_inr

    @property
    def stressed_net_inr(self) -> float:
        """Net rupees if each spread were 1.5x wider (entry 1/4 spread higher, exit 1/4 spread lower)."""
        if self.skipped:
            return 0.0
        return self.net_inr - 0.25 * (self.spread_in + self.spread_out) * self.lot_units


def pick_contract(quotes: pd.DataFrame, spot: float, side: int, when: pd.Timestamp, trading_days: list[date],
                  min_sessions_left: int = 2) -> tuple[float, str, date] | None:
    typ = "CE" if side > 0 else "PE"
    today = when.tz_convert("Asia/Kolkata").date()
    future_days = [d for d in trading_days if d >= today]
    expiries = sorted(e for e in quotes.expiry.unique()
                      if sum(1 for d in future_days if d <= e) >= min_sessions_left)
    if not expiries:
        return None
    exp = expiries[0]
    strikes = np.sort(quotes.loc[(quotes.expiry == exp) & (quotes.type == typ), "strike"].unique())
    itm = strikes[strikes < spot] if side > 0 else strikes[strikes > spot]
    if not len(itm):
        return None
    strike = float(itm.max() if side > 0 else itm.min())
    return strike, typ, exp


def _valid(q: pd.DataFrame) -> pd.DataFrame:
    b, a = q.bid.astype(float), q.ask.astype(float)
    return q[np.isfinite(b) & np.isfinite(a) & (b > 0) & (a > 0) & (a >= b)]


def execute(signals: list[dict], quotes: pd.DataFrame, trading_days: list[date], lot_units: int = 65,
            delay_s: int = 5, max_quote_gap_s: int = 60, min_sessions_left: int = 2) -> list[OptionFill]:
    """signals: dicts with decision_time, exit_time (tz-aware), side (+1/-1), spot (underlying at decision)."""
    q = quotes.sort_values("time")
    out = []
    for s in signals:
        pick = pick_contract(q, s["spot"], s["side"], s["decision_time"], trading_days, min_sessions_left)
        if pick is None:
            out.append(OptionFill(s["decision_time"], s["side"], np.nan, "", None, None, None, None, None,
                                  lot_units=lot_units, skipped="no eligible contract"))
            continue
        strike, typ, exp = pick
        c = _valid(q[(q.strike == strike) & (q.type == typ) & (q.expiry == exp)])
        t_in = s["decision_time"] + pd.Timedelta(seconds=delay_s)
        f = OptionFill(s["decision_time"], s["side"], strike, typ, exp, None, None, None, None, lot_units=lot_units)
        session = s["decision_time"].tz_convert("Asia/Kolkata").date()
        if s["exit_time"] <= t_in:
            f.skipped = "exit decision before the entry could be filled"
            out.append(f)
            continue
        a = c[c.time >= t_in].head(1)
        if a.empty or (a.time.iloc[0] - t_in).total_seconds() > max_quote_gap_s:
            f.skipped = "no entry quote close to the decision time"
            out.append(f)
            continue
        if a.time.iloc[0] > s["exit_time"]:
            f.skipped = "entry quote arrives after the exit decision"
            out.append(f)
            continue
        b = c[c.time >= max(s["exit_time"], a.time.iloc[0])].head(1)
        if b.empty or (b.time.iloc[0] - s["exit_time"]).total_seconds() > max_quote_gap_s:
            f.skipped = "no exit quote close to the exit time"
        elif a.time.iloc[0].tz_convert("Asia/Kolkata").date() != session or \
                b.time.iloc[0].tz_convert("Asia/Kolkata").date() != session:
            f.skipped = "quote from another session"
        else:
            f.entry_time, f.entry_ask = a.time.iloc[0], float(a.ask.iloc[0])
            f.exit_time, f.exit_bid = b.time.iloc[0], float(b.bid.iloc[0])
            f.spread_in = float(a.ask.iloc[0] - a.bid.iloc[0])
            f.spread_out = float(b.ask.iloc[0] - b.bid.iloc[0])
            f.fees_inr = costs.option_fees(f.entry_ask, f.exit_bid, lot_units, session).total
        out.append(f)
    return out
