"""As-of features (blueprint section 3; A section 3). Every function takes inputs that carry `available_at` and
returns (value, max available_at used). `features_asof` refuses any input available after the decision time, so no
feature can read the future. Pure; numpy only.

Features: ATR14 (Wilder, completed sessions only), the opening-window volume and RVOL (14 previous valid windows),
ER20 (diagnostic only), VIX state, top-of-book imbalance (diagnostic only).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from . import calendar as cal
from .types import FeatureSnapshot

ATR_N = 14
RVOL_N = 14


@dataclass(frozen=True)
class Bar:
    """A completed bar [start, start + minutes). available_at: when our process had it (>= its close)."""
    instrument_id: str
    start: datetime
    minutes: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    available_at: datetime

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=self.minutes)

    def __post_init__(self):
        if self.available_at < self.start + timedelta(minutes=self.minutes):
            raise ValueError("a bar cannot be available before it closes")


@dataclass(frozen=True)
class DailyBar:
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    available_at: datetime | None = None

    def avail(self) -> datetime:
        return self.available_at or datetime.combine(self.day, cal.CLOSE, cal.IST)


def _check(avail: datetime, decided_at: datetime) -> None:
    if avail > decided_at:
        raise ValueError(f"input available at {avail} is after the decision time {decided_at}")


def atr14_wilder(daily: list[DailyBar], decided_at: datetime, n: int = ATR_N,
                 window: int = 100) -> tuple[float | None, datetime | None]:
    """Wilder ATR over the `window` completed sessions BEFORE the decision's session, seeded with the mean of the
    window's first n true ranges (as the OVN v2 scorer). None if fewer than n + 1 bars, or if the previous
    session's bar is missing."""
    d0 = decided_at.astimezone(cal.IST).date()
    xs = sorted((b for b in daily if b.day < d0), key=lambda b: b.day)[-(window + 1):]
    if len(xs) < n + 1 or xs[-1].day != cal.prev_session(d0):
        return None, None
    tr = [max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close)) for a, b in zip(xs, xs[1:])]
    a = sum(tr[:n]) / n
    for x in tr[n:]:
        a = (a * (n - 1) + x) / n
    av = max(b.avail() for b in xs)
    _check(av, decided_at)
    return a, av


def prev_close(daily: list[DailyBar], decided_at: datetime) -> tuple[float | None, datetime | None]:
    d0 = decided_at.astimezone(cal.IST).date()
    xs = [b for b in daily if b.day < d0]
    if not xs:
        return None, None
    b = max(xs, key=lambda b: b.day)
    if b.day != cal.prev_session(d0):
        return None, None
    _check(b.avail(), decided_at)
    return b.close, b.avail()


def opening_window(bars: list[Bar], day: date, decided_at: datetime, n_bars: int = 2,
                   bar_min: int = 3) -> tuple[dict | None, datetime | None]:
    """The first n_bars bars of `day` (09:15, 09:18 for 3-minute bars), all completed and available by decided_at:
    {open, high, low, close, volume}; None if any is missing (a missing window makes the stock ineligible)."""
    o = datetime.combine(day, cal.OPEN, cal.IST)
    want = [o + timedelta(minutes=bar_min * i) for i in range(n_bars)]
    got = {b.start.astimezone(cal.IST): b for b in bars if b.minutes == bar_min and b.available_at <= decided_at}
    if not all(w in got for w in want):
        return None, None
    bs = [got[w] for w in want]
    return ({"open": bs[0].open, "high": max(b.high for b in bs), "low": min(b.low for b in bs), "close": bs[-1].close,
             "volume": sum(b.volume for b in bs)}, max(b.available_at for b in bs))


def rvol(today_volume: float, prior_windows: list[tuple[date, float]], day: date,
         n: int = RVOL_N, min_valid: int | None = None) -> float | None:
    """today's opening-window volume / mean of the same window over the n previous SESSIONS; every one of those n
    sessions must have a valid (positive) window, else None (ineligible). min_valid < n is for exploratory smoke
    runs only (the registered rule is all n)."""
    want, x = [], day
    for _ in range(n):
        x = cal.prev_session(x)
        want.append(x)
    have = dict(prior_windows)
    vals = [have.get(d) for d in want]
    good = [v for v in vals if v is not None and v > 0]
    if len(good) < (n if min_valid is None else min_valid):
        return None
    base = sum(good) / len(good)
    return today_volume / base if base > 0 else None


def er20(closes: list[float]) -> float:
    """Efficiency ratio over the last 20 one-minute changes; zero denominator -> 0. Diagnostic only (v1)."""
    c = closes[-21:]
    if len(c) < 21:
        return float("nan")
    den = sum(abs(b - a) for a, b in zip(c, c[1:]))
    return abs(c[-1] - c[0]) / den if den > 0 else 0.0


def er_label(x: float) -> str:
    return "trend" if x >= 0.6 else ("chop" if x <= 0.3 else "neutral")


def vix_state(vix_daily: list[DailyBar], decided_at: datetime) -> tuple[tuple[float | None, float | None], datetime | None]:
    """(previous close, change over 5 sessions) from completed sessions only."""
    d0 = decided_at.astimezone(cal.IST).date()
    xs = sorted((b for b in vix_daily if b.day < d0), key=lambda b: b.day)
    if len(xs) < 6 or xs[-1].day != cal.prev_session(d0):
        return (None, None), None
    _check(max(b.avail() for b in xs[-6:]), decided_at)
    return (xs[-1].close, xs[-1].close / xs[-6].close - 1), max(b.avail() for b in xs[-6:])


def book_imbalance(book) -> float | None:
    """(bid size - ask size) / (sum) over the displayed levels. Diagnostic only (B's GS-A5), never a gate in v1."""
    b = sum(q for _, q in book.bids)
    a = sum(q for _, q in book.asks)
    return (b - a) / (a + b) if a + b > 0 else None


def features_asof(decided_at: datetime, items: dict) -> FeatureSnapshot:
    """Bundle named (value, available_at) pairs; raises if any input postdates the decision."""
    vals, avs = {}, []
    for k, (v, av) in items.items():
        vals[k] = v
        if av is not None:
            avs.append(av)
    return FeatureSnapshot(decided_at, vals, max(avs) if avs else None)


def bar_slot_time(day: date, hhmm: time) -> datetime:
    return datetime.combine(day, hhmm, cal.IST)
