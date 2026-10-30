"""NSE exchange calendar (equity + equity-derivative segments): sessions, holidays, special sessions, expiries, events.

The calendar is a static, hashable snapshot. Sources:
  * 2022-01-01 .. 2026-10-21: weekdays without a NIFTY daily candle in ~/Downloads/nfce_data/daily/NIFTY_1d.pkl
    (checked 26 Oct 2026); weekend sessions likewise.
  * 2026-10-22 .. 2026-12-31: the published NSE 2026 holiday list (secondary sources agree, checked 26 Oct 2026):
    10 Nov (Diwali Balipratipada), 24 Nov (Guru Nanak Jayanti), 25 Dec (Christmas). Muhurat 8 Nov (Sunday).
  * Events (RBI policy days, Union Budget): RBI press release of 23 Mar 2026 (MPC FY27 dates).
Dates after COVERED_UNTIL are unknown: asking about them raises, so a missing calendar is a data failure, never a guess.

Muhurat sessions are SPECIAL: they are not regular sessions (no GS entry or scheduled exit uses them).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
OPEN, CLOSE = time(9, 15), time(15, 30)
COVERED_FROM, COVERED_UNTIL = date(2022, 1, 1), date(2026, 12, 31)

_HOLIDAYS = """
2022-01-26 2022-03-01 2022-03-18 2022-04-14 2022-04-15 2022-05-03 2022-08-09 2022-08-15 2022-08-31 2022-10-05
2022-10-26 2022-11-08
2023-01-26 2023-03-07 2023-03-30 2023-04-04 2023-04-07 2023-04-14 2023-05-01 2023-06-29 2023-08-15 2023-09-19
2023-10-02 2023-10-24 2023-11-14 2023-11-27 2023-12-25
2024-01-22 2024-01-26 2024-03-08 2024-03-25 2024-03-29 2024-04-11 2024-04-17 2024-05-01 2024-05-20 2024-06-17
2024-07-17 2024-08-15 2024-10-02 2024-11-15 2024-11-20 2024-12-25
2025-02-26 2025-03-14 2025-03-31 2025-04-10 2025-04-14 2025-04-18 2025-05-01 2025-08-15 2025-08-27 2025-10-02
2025-10-22 2025-11-05 2025-12-25
2026-01-15 2026-01-26 2026-03-03 2026-03-26 2026-03-31 2026-04-03 2026-04-14 2026-05-01 2026-05-28 2026-06-26
2026-09-14 2026-10-02 2026-10-20 2026-11-10 2026-11-24 2026-12-25
"""
HOLIDAYS = frozenset(date.fromisoformat(x) for x in _HOLIDAYS.split())
# Muhurat (evening, about one hour): a weekday Muhurat day is otherwise a holiday.
MUHURAT = frozenset(date.fromisoformat(x) for x in
                    ("2022-10-24", "2023-11-12", "2024-11-01", "2025-10-21", "2026-11-08"))
# weekend days with a full regular session (Budget days, the 20 Jan 2024 session)
WEEKEND_SESSIONS = frozenset(date.fromisoformat(x) for x in ("2024-01-20", "2025-02-01", "2026-02-01"))
# short weekend disaster-recovery drills: special, not regular
DR_SESSIONS = frozenset(date.fromisoformat(x) for x in ("2024-03-02", "2024-05-18"))

# scheduled market-wide events (date, kind). RBI: the announcement (last MPC day, ~10:00 IST).
EVENTS = tuple((date.fromisoformat(d), k) for d, k in (
    ("2026-02-01", "budget"), ("2026-04-08", "rbi"), ("2026-06-05", "rbi"), ("2026-08-05", "rbi"),
    ("2026-10-07", "rbi"), ("2026-12-04", "rbi"), ("2027-02-01", "budget"), ("2027-02-05", "rbi")))


class CalendarError(ValueError):
    """The date is outside the calendar snapshot."""


def _check(d: date) -> None:
    if not (COVERED_FROM <= d <= COVERED_UNTIL):
        raise CalendarError(f"{d} is outside the calendar snapshot {COVERED_FROM}..{COVERED_UNTIL}")


def is_session(d: date) -> bool:
    """A regular NSE trading session (09:15-15:30)."""
    _check(d)
    if d in WEEKEND_SESSIONS:
        return True
    return d.weekday() < 5 and d not in HOLIDAYS and d not in MUHURAT


def is_special(d: date) -> bool:
    return d in MUHURAT or d in DR_SESSIONS


def next_session(d: date) -> date:
    """The first regular session strictly after d."""
    x = d + timedelta(days=1)
    while not is_session(x):
        x += timedelta(days=1)
    return x


def prev_session(d: date) -> date:
    """The last regular session strictly before d."""
    x = d - timedelta(days=1)
    while not is_session(x):
        x -= timedelta(days=1)
    return x


def sessions(start: date, end: date) -> list[date]:
    """Regular sessions in [start, end]."""
    out, x = [], start
    while x <= end:
        if is_session(x):
            out.append(x)
        x += timedelta(days=1)
    return out


def nth_session(start: date, n: int) -> date:
    """The n-th regular session counting `start` as the first (if it is a session)."""
    x = start if is_session(start) else next_session(start)
    for _ in range(n - 1):
        x = next_session(x)
    return x


def session_bounds(d: date) -> tuple[datetime, datetime]:
    """(open, close) as timezone-aware IST datetimes."""
    if not is_session(d):
        raise CalendarError(f"{d} is not a regular session")
    return datetime.combine(d, OPEN, IST), datetime.combine(d, CLOSE, IST)


def to_ist(ts: datetime) -> datetime:
    """Naive timestamps are taken as IST (the recorders' local clock)."""
    return ts.replace(tzinfo=IST) if ts.tzinfo is None else ts.astimezone(IST)


# ---------------------------------------------------------------- expiries
def _adjust_back(d: date) -> date:
    """Expiry falling on a non-session moves to the previous regular session."""
    while not is_session(d):
        d -= timedelta(days=1)
    return d


def weekly_expiry(d: date, weekday: int = 1) -> date:
    """The first weekly expiry on or after d. NIFTY weekly = Tuesday (weekday 1) since Sep 2025; SENSEX = Thursday."""
    x = d
    while True:
        target = x + timedelta(days=(weekday - x.weekday()) % 7)
        e = _adjust_back(target)
        if e >= d:
            return e
        x = target + timedelta(days=1)


def monthly_expiry(year: int, month: int, weekday: int = 1) -> date:
    """The last `weekday` of the month (holiday-adjusted back). Stock/BANKNIFTY monthly = last Tuesday."""
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    x = nxt - timedelta(days=1)
    while x.weekday() != weekday:
        x -= timedelta(days=1)
    return _adjust_back(x)


def first_expiry_after(listed, d: date) -> date | None:
    """The nearest LISTED expiry strictly after d (listed: iterable of date or ISO strings)."""
    xs = sorted(e if isinstance(e, date) else date.fromisoformat(str(e)[:10]) for e in listed)
    later = [e for e in xs if e > d]
    return later[0] if later else None


def events_between(after: date, upto: date) -> list[tuple[date, str]]:
    """Scheduled events with after < date <= upto (an event that the overnight interval after->upto spans)."""
    return [(d, k) for d, k in EVENTS if after < d <= upto]
