"""Option-chain analytics: PCR, change-in-OI flow state, OI walls, max pain, ATM IV.

Change-in-OI (ΔOI) is today's OI minus Upstox's "previous OI". When any strike in the window lacks a previous
OI, every ΔOI-based figure is reported as unavailable (None); it is never computed from zeros.

ΔOI flow is classified explicitly instead of dividing two signed numbers:
    put ΔOI   call ΔOI    state
    > 0       < 0         bullish        (puts added, calls removed)
    < 0       > 0         bearish        (calls added, puts removed)
    > 0       > 0         by ratio put/call: > 1/0.7 bullish_lean, < 0.7 bearish_lean, else neutral
    < 0       < 0         unwinding      (both sides removed; no direction)
    > 0       = 0         bullish_lean
    = 0       > 0         bearish_lean
    < 0       = 0         bearish_lean   (put unwinding)
    = 0       < 0         bullish_lean   (call unwinding)
    = 0       = 0         neutral
Note: every option contract has a buyer and a seller. Reading added put OI as "put writing / support" is the
report's hypothesis, not an established fact; the bridge measures it in paper trading (shadow vetoes).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .providers import Chain, StrikeRow

BULLISH = ("bullish", "bullish_lean")
BEARISH = ("bearish", "bearish_lean")


@dataclass
class Summary:
    underlying_key: str
    expiry: str
    spot: float
    fetched_at: str
    step: float
    atm_strike: float
    pcr_oi: float | None          # put OI / call OI, ATM +/- window
    put_doi: float | None         # sum of put ΔOI in the window (None = unavailable)
    call_doi: float | None
    flow: str                     # see module docstring; "unavailable" when ΔOI is missing
    max_call_oi_strike: float     # global call wall (information only)
    max_put_oi_strike: float      # global put wall (information only)
    max_pain: float
    atm_iv: float | None
    synth_forward: float | None   # weekly K + C - P (information only; NOT used as the futures basis)
    window_rows: list[StrikeRow]

    @property
    def doi_available(self) -> bool:
        return self.put_doi is not None and self.call_doi is not None

    @property
    def pcr_doi(self) -> float | None:
        """Plain put/call ΔOI ratio, only when both sides added OI (for display)."""
        if self.doi_available and self.put_doi > 0 and self.call_doi > 0:
            return self.put_doi / self.call_doi
        return None


def strike_step(rows: list[StrikeRow]) -> float:
    diffs = [b.strike - a.strike for a, b in zip(rows, rows[1:]) if b.strike > a.strike]
    return min(diffs) if diffs else 0.0


def atm_index(rows: list[StrikeRow], spot: float) -> int:
    return min(range(len(rows)), key=lambda i: abs(rows[i].strike - spot))


def ratio(num: float, den: float) -> float | None:
    if den > 0:
        return num / den
    if num > 0:
        return math.inf
    return None


def _sum(values) -> float | None:
    vals = list(values)
    if any(v is None for v in vals):
        return None
    return float(sum(vals))


def flow_state(put_doi: float | None, call_doi: float | None, veto: float = 0.7) -> str:
    if put_doi is None or call_doi is None:
        return "unavailable"
    if put_doi > 0 and call_doi < 0:
        return "bullish"
    if put_doi < 0 and call_doi > 0:
        return "bearish"
    if put_doi > 0 and call_doi > 0:
        r = put_doi / call_doi
        return "bullish_lean" if r > 1 / veto else "bearish_lean" if r < veto else "neutral"
    if put_doi < 0 and call_doi < 0:
        return "unwinding"
    if put_doi > 0 or call_doi < 0:
        return "bullish_lean"
    if call_doi > 0 or put_doi < 0:
        return "bearish_lean"
    return "neutral"


def max_pain(rows: list[StrikeRow]) -> float:
    """Strike at which total intrinsic value paid to option holders is smallest."""
    best_k, best_pain = rows[0].strike, math.inf
    for cand in rows:
        k = cand.strike
        pain = sum(r.call_oi * max(0.0, k - r.strike) + r.put_oi * max(0.0, r.strike - k) for r in rows)
        if pain < best_pain:
            best_k, best_pain = k, pain
    return best_k


def path_wall(rows: list[StrikeRow], lo: float, hi: float, side: str) -> StrikeRow | None:
    """Strike with the most call OI (side='call') or put OI (side='put') strictly inside (lo, hi]."""
    inside = [r for r in rows if lo < r.strike <= hi]
    if not inside:
        return None
    key = (lambda r: r.call_oi) if side == "call" else (lambda r: r.put_oi)
    best = max(inside, key=key)
    return best if key(best) > 0 else None


def summarize(chain: Chain, window: int = 5, veto: float = 0.7) -> Summary:
    rows = chain.rows
    if not rows:
        raise ValueError("empty chain")
    i = atm_index(rows, chain.spot)
    win = rows[max(0, i - window): i + window + 1]
    atm = rows[i]
    ivs = [x for x in (atm.call_iv, atm.put_iv) if x is not None]
    fwd = atm.strike + atm.call_ltp - atm.put_ltp if (atm.call_ltp and atm.put_ltp) else None
    put_doi = _sum(r.put_doi for r in win)
    call_doi = _sum(r.call_doi for r in win)
    return Summary(
        underlying_key=chain.underlying_key,
        expiry=chain.expiry,
        spot=chain.spot,
        fetched_at=chain.fetched_at.isoformat(),
        step=strike_step(rows),
        atm_strike=atm.strike,
        pcr_oi=ratio(sum(r.put_oi for r in win), sum(r.call_oi for r in win)),
        put_doi=put_doi,
        call_doi=call_doi,
        flow=flow_state(put_doi, call_doi, veto),
        max_call_oi_strike=max(rows, key=lambda r: r.call_oi).strike,
        max_put_oi_strike=max(rows, key=lambda r: r.put_oi).strike,
        max_pain=max_pain(rows),
        atm_iv=sum(ivs) / len(ivs) if ivs else None,
        synth_forward=fwd,
        window_rows=win,
    )
