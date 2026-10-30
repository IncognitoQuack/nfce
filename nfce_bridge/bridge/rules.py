"""Signal validation and the veto / boost rules from the report (Section 4 and Prompt 2).

BUY:
  VETO  if the ΔOI flow is bearish (bearish or bearish_lean, i.e. "PCR(ΔOI) < 0.7") AND the strike with the
        most call OI strictly between entry and T1 is still ADDING call OI ("call writing is building at the
        next strike within 1R").
  BOOST if puts are being added below entry (put ΔOI > 0) AND call OI is strictly falling above entry
        (call ΔOI < 0), both within ATM +/- window.
SELL mirrors it with the put wall between T1 and entry.
UNCHECKED (NO_DATA) whenever the futures basis, the chain, or ΔOI is unavailable: never a silent PASS.

Price domain (FIX, review round 3, H12): an alert from a futures chart (NSE:NIFTY1!) carries futures prices; an alert
from the spot index chart (NSE:NIFTY) carries spot prices. `domain` says which (payload "px" wins, else the symbol).
The bridge moves spot levels to futures prices with the LIVE futures-minus-spot basis before anything uses them, and
refuses paper entries when that basis is unavailable. Strikes are then compared in spot terms (futures level - basis).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace

from .analytics import BEARISH, BULLISH, Summary


class SignalError(ValueError):
    pass


def _f(x, name: str, required: bool = True) -> float | None:
    if x is None:
        if required:
            raise SignalError(f"missing {name}")
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        raise SignalError(f"{name} is not a number")
    if not math.isfinite(v) or v <= 0:
        raise SignalError(f"{name} must be a positive finite number")
    return v


@dataclass
class Signal:
    symbol: str
    side: str            # BUY / SELL
    entry: float
    sl: float
    t1: float
    t2: float | None = None
    t3: float | None = None
    score: float | None = None
    grade: str = "A"
    oi: str = ""
    tf: str = ""
    sid: str = ""        # trade id from the indicator (idempotency key)
    bar_time_ms: int | None = None   # signal bar close time (ms since epoch)
    domain: str = "futures"          # price domain of the levels: "futures" or "spot"

    @property
    def R(self) -> float:
        return abs(self.entry - self.sl)

    def to_futures(self, basis: float) -> "Signal":
        """Every level moved from spot to futures prices (futures = spot + basis). Futures signals are returned as is."""
        if self.domain == "futures":
            return self
        mv = lambda x: None if x is None else x + basis   # noqa: E731
        return replace(self, entry=self.entry + basis, sl=self.sl + basis, t1=self.t1 + basis, t2=mv(self.t2),
                       t3=mv(self.t3), domain="futures")

    @classmethod
    def from_payload(cls, d: dict) -> "Signal":
        if not isinstance(d, dict):
            raise SignalError("payload must be a JSON object")
        side = str(d.get("side", "")).upper()
        if side not in ("BUY", "SELL"):
            raise SignalError(f"side must be BUY or SELL, got {side!r}")
        s = 1 if side == "BUY" else -1
        entry, sl = _f(d.get("entry"), "entry"), _f(d.get("sl"), "sl")
        r = abs(entry - sl)
        if r <= 0 or (entry - sl) * s <= 0:
            raise SignalError("stop must be below entry for BUY and above entry for SELL")
        if r / entry > 0.05:
            raise SignalError("risk above 5% of price: rejected as implausible")
        # FIX (M02): complete the default targets FIRST, then validate the whole ladder
        t1 = _f(d.get("t1"), "t1", required=False) or entry + s * r
        t2 = _f(d.get("t2"), "t2", required=False) or entry + 2 * s * r
        t3 = _f(d.get("t3"), "t3", required=False) or entry + 3 * s * r
        levels = [entry, t1, t2, t3]
        if any((b - a) * s <= 0 for a, b in zip(levels, levels[1:])):
            raise SignalError("targets must be beyond entry and in order (T1 < T2 < T3 for BUY; missing T2/T3 "
                              "default to 2R/3R)")
        score = d.get("score")
        try:
            score = float(score) if score is not None else None
        except (TypeError, ValueError):
            score = None
        if score is not None and not math.isfinite(score):           # FIX (fuzz): inf/nan score is "no score"
            score = None
        bar_t = d.get("t")
        try:
            bar_t = int(bar_t) if bar_t is not None else None
        except (TypeError, ValueError, OverflowError):               # FIX (fuzz): int(inf) raised OverflowError
            bar_t = None
        if bar_t is not None and not (946_684_800_000 <= bar_t <= 4_102_444_800_000):   # years 2000-2100 only
            bar_t = None
        sym = str(d.get("symbol", ""))[:40]
        px = str(d.get("px") or "").lower()
        domain = px if px in ("spot", "futures") else (
            "futures" if re.search(r"(\d!|FUT)$", sym.upper().split(":")[-1]) else "spot")
        return cls(symbol=sym, side=side, entry=entry, sl=sl, t1=t1, t2=t2, t3=t3,
                   score=score, grade=str(d.get("grade") or "A")[:3], oi=str(d.get("oi") or "")[:20],
                   tf=str(d.get("tf") or "")[:5], sid=str(d.get("id") or "")[:80], bar_time_ms=bar_t,
                   domain=domain)


@dataclass
class Decision:
    action: str                     # PASS / VETO / NO_DATA
    grade_in: str
    grade_out: str
    boosted: bool = False
    flow: str = "unavailable"
    reasons: list[str] = field(default_factory=list)


def _sum_or_none(values) -> float | None:
    vals = list(values)
    return None if any(v is None for v in vals) else float(sum(vals))


def evaluate(sig: Signal, s: Summary | None, basis: float | None, pcr_doi_veto: float = 0.7) -> Decision:
    if s is None:
        return Decision("NO_DATA", sig.grade, sig.grade, reasons=["option-chain data unavailable: signal NOT checked"])
    if basis is None:
        return Decision("NO_DATA", sig.grade, sig.grade, flow=s.flow,
                        reasons=["live futures/spot quotes unavailable, so strikes cannot be compared: NOT checked"])
    if not s.doi_available:
        return Decision("NO_DATA", sig.grade, sig.grade, flow=s.flow,
                        reasons=["previous-day OI missing in the chain, so ΔOI flow is unknown: NOT checked"])
    e, t1 = sig.entry - basis, sig.t1 - basis
    rows = s.window_rows
    reasons = [f"futures basis {basis:+.1f} (live quotes) → spot-terms entry {e:.1f}, T1 {t1:.1f}",
               f"ΔOI flow: {s.flow} (put ΔOI {s.put_doi:+,.0f}, call ΔOI {s.call_doi:+,.0f})"]
    if sig.side == "BUY":
        inside = [r for r in s.window_rows if e < r.strike <= t1]
        wall = max(inside, key=lambda r: r.call_oi) if inside else None
        building = wall is not None and wall.call_oi > 0 and wall.call_doi is not None and wall.call_doi > 0
        flow_against = s.flow in BEARISH
        writing = _sum_or_none(r.put_doi for r in rows if r.strike < e)
        unwinding = _sum_or_none(r.call_doi for r in rows if r.strike > e)
        if wall is not None:
            reasons.append(f"call wall in path {wall.strike:g} (call ΔOI {wall.call_doi:+,.0f}: "
                           f"{'building' if building else 'not building'})")
    else:
        inside = [r for r in s.window_rows if t1 <= r.strike < e]
        wall = max(inside, key=lambda r: r.put_oi) if inside else None
        building = wall is not None and wall.put_oi > 0 and wall.put_doi is not None and wall.put_doi > 0
        flow_against = s.flow in BULLISH
        writing = _sum_or_none(r.call_doi for r in rows if r.strike > e)
        unwinding = _sum_or_none(r.put_doi for r in rows if r.strike < e)
        if wall is not None:
            reasons.append(f"put wall in path {wall.strike:g} (put ΔOI {wall.put_doi:+,.0f}: "
                           f"{'building' if building else 'not building'})")
    if flow_against and building:
        reasons.append("flow against the trade and a building wall before T1 → VETO")
        return Decision("VETO", sig.grade, sig.grade, flow=s.flow, reasons=reasons)
    boost = writing is not None and unwinding is not None and writing > 0 and unwinding < 0
    grade_out = sig.grade
    if boost:
        grade_out = "A+" if sig.grade == "A" else sig.grade
        reasons.append("option writing on our side and unwinding against → boost")
    return Decision("PASS", sig.grade, grade_out, boosted=boost, flow=s.flow, reasons=reasons)
