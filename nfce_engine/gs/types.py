"""Immutable GS records (A section 3). Times are timezone-aware; session labels use Asia/Kolkata.

IDs are content hashes (`make_id`), so a replay of the same inputs produces the same intent and fill IDs, and a
restart can never duplicate an entry (the store ignores a second insert of the same ID).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime


def _canon(x):
    if isinstance(x, datetime):
        return x.isoformat()
    if isinstance(x, (tuple, list)):
        return [_canon(v) for v in x]
    if isinstance(x, dict):
        return {str(k): _canon(v) for k, v in sorted(x.items())}
    if hasattr(x, "__dataclass_fields__"):
        return _canon(asdict(x))
    if isinstance(x, float):
        return repr(round(x, 10))
    return x


def canonical_json(x) -> str:
    return json.dumps(_canon(x), sort_keys=True, separators=(",", ":"), default=str)


def make_id(prefix: str, *parts) -> str:
    return f"{prefix}-{hashlib.sha256(canonical_json(parts).encode()).hexdigest()[:20]}"


def _aware(t: datetime | None, name: str) -> None:
    if t is not None and (t.tzinfo is None or t.utcoffset() is None):
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class Event:
    """One raw observation. available_at = when our process could first use it (>= received_at)."""
    event_id: str
    instrument_id: str
    exchange_ts: datetime | None
    received_at: datetime
    available_at: datetime
    kind: str                      # "quote" | "bar3m" | "bar1d" | "chain" | "filing" | "vix" | ...
    payload: dict = field(default_factory=dict, hash=False)
    source_hash: str = ""

    def __post_init__(self):
        _aware(self.exchange_ts, "exchange_ts")
        _aware(self.received_at, "received_at")
        _aware(self.available_at, "available_at")
        if self.available_at < self.received_at:
            raise ValueError("available_at precedes received_at")

    @staticmethod
    def new(instrument_id: str, kind: str, received_at: datetime, payload: dict, exchange_ts: datetime | None = None,
            available_at: datetime | None = None, source_hash: str = "") -> "Event":
        av = available_at or received_at
        eid = make_id("ev", instrument_id, kind, received_at, exchange_ts, payload)
        return Event(eid, instrument_id, exchange_ts, received_at, av, kind, payload, source_hash)


@dataclass(frozen=True)
class Leg:
    instrument_id: str
    side: int                      # +1 buy, -1 sell
    qty: int                       # units (shares, or lots x lot size)
    limit: float | None = None     # None = marketable
    kind: str = "EQ"               # "EQ" | "OPT" | "FUT"
    role: str = "entry"            # "entry" | "wing" | "short"

    def __post_init__(self):
        if self.side not in (1, -1) or self.qty < 0:
            raise ValueError("side must be +1/-1 and qty >= 0")


@dataclass(frozen=True)
class StopRule:
    stop_price: float | None = None    # price stop on the position (None = no price stop)
    time_exit: datetime | None = None  # flat by this time


@dataclass(frozen=True)
class Intent:
    intent_id: str
    alpha_id: str
    decided_at: datetime
    legs: tuple[Leg, ...]
    activate_at: datetime              # earliest fill (decision + registered latency)
    expires_at: datetime
    stop_rule: StopRule
    risk_bound_inr: float
    input_event_ids: tuple[str, ...]
    protocol_hash: str
    branch: str = "P"                  # "P" passive (primary) | "M" marketable counterfactual
    meta: tuple = ()                   # ((key, value), ...): diagnostics only, never read by execution

    def __post_init__(self):
        for n in ("decided_at", "activate_at", "expires_at"):
            _aware(getattr(self, n), n)
        if not (self.decided_at <= self.activate_at <= self.expires_at):
            raise ValueError("need decided_at <= activate_at <= expires_at")

    @property
    def meta_dict(self) -> dict:
        return dict(self.meta)


@dataclass(frozen=True)
class Approval:
    intent: Intent
    approved: bool
    qty: int                           # approved units on the first leg (0 = skip)
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutionEvent:
    exec_id: str
    intent_id: str
    leg_index: int
    ts: datetime
    kind: str                          # "fill" | "expire" | "cancel" | "reject" | "exit"
    instrument_id: str = ""
    side: int = 0
    qty: int = 0
    price: float = 0.0
    fee: float = 0.0
    scenario: str = "market"           # "market" | "touch" | "strict" | "adverse"
    reason: str = ""
    meta: tuple = ()

    def __post_init__(self):
        _aware(self.ts, "ts")

    @staticmethod
    def new(intent_id: str, leg_index: int, ts: datetime, kind: str, **kw) -> "ExecutionEvent":
        eid = make_id("ex", intent_id, leg_index, ts, kind, kw.get("scenario", "market"), kw.get("reason", ""))
        return ExecutionEvent(eid, intent_id, leg_index, ts, kind, **kw)


@dataclass(frozen=True)
class FeatureSnapshot:
    decided_at: datetime
    values: dict = field(hash=False)
    max_available_at: datetime | None = None
    input_event_ids: tuple[str, ...] = ()

    def __post_init__(self):
        _aware(self.decided_at, "decided_at")
        if self.max_available_at is not None and self.max_available_at > self.decided_at:
            raise ValueError("a feature used data available after the decision time")


@dataclass(frozen=True)
class Verdict:
    protocol_id: str
    verdict: str                       # PASS | FAIL | INCONCLUSIVE | INFEASIBLE
    stats: dict = field(hash=False)
    reasons: tuple[str, ...] = ()

    def __post_init__(self):
        if self.verdict not in ("PASS", "FAIL", "INCONCLUSIVE", "INFEASIBLE"):
            raise ValueError(f"unknown verdict {self.verdict}")
