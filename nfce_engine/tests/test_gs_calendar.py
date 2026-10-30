"""gs/calendar.py and gs/instruments.py: sessions, holidays, special sessions, expiries, timezones, lots and ticks."""
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gs import calendar as cal  # noqa: E402
from gs import instruments as ins  # noqa: E402


def test_weekends_holidays_and_budget_sundays():
    assert cal.is_session(date(2026, 10, 26)) and cal.is_session(date(2026, 10, 27))
    assert not cal.is_session(date(2026, 10, 24))                     # Saturday
    assert not cal.is_session(date(2026, 10, 20))                     # Dussehra
    assert not cal.is_session(date(2026, 11, 10)) and not cal.is_session(date(2026, 11, 24))
    assert cal.is_session(date(2026, 2, 1))                           # Budget, a Sunday session
    assert cal.is_session(date(2024, 1, 20))                          # full Saturday session


def test_muhurat_and_dr_drills_are_special_not_regular():
    for d in (date(2026, 11, 8), date(2025, 10, 21), date(2024, 11, 1), date(2024, 3, 2)):
        assert cal.is_special(d) and not cal.is_session(d)


def test_next_and_previous_session_skip_holidays_and_weekends():
    assert cal.next_session(date(2026, 10, 23)) == date(2026, 10, 26)
    assert cal.next_session(date(2026, 11, 9)) == date(2026, 11, 11)  # over Balipratipada
    assert cal.next_session(date(2026, 11, 6)) == date(2026, 11, 9)   # over the Muhurat Sunday
    assert cal.prev_session(date(2026, 10, 21)) == date(2026, 10, 19)  # over Dussehra
    assert cal.prev_session(date(2026, 10, 26)) == date(2026, 10, 23)


def test_missing_calendar_is_an_error_not_a_guess():
    with pytest.raises(cal.CalendarError):
        cal.is_session(date(2027, 1, 4))
    with pytest.raises(cal.CalendarError):
        cal.next_session(date(2026, 12, 31))


def test_session_counting_for_pilot_windows():
    s = cal.sessions(date(2026, 10, 26), date(2026, 11, 30))
    assert s[0] == date(2026, 10, 26) and date(2026, 11, 10) not in s and date(2026, 11, 24) not in s
    assert cal.nth_session(date(2026, 10, 26), 1) == date(2026, 10, 26)
    assert cal.nth_session(date(2026, 10, 24), 1) == date(2026, 10, 26)
    assert cal.nth_session(date(2026, 10, 26), len(s)) == s[-1]


def test_session_bounds_are_ist_aware_and_naive_times_are_ist():
    o, c = cal.session_bounds(date(2026, 10, 26))
    assert o.utcoffset().total_seconds() == 5.5 * 3600 and o.hour == 9 and o.minute == 15 and c.hour == 15
    assert o.astimezone(timezone.utc).hour == 3 and o.astimezone(timezone.utc).minute == 45
    assert cal.to_ist(datetime(2026, 10, 26, 15, 20)).utcoffset() == o.utcoffset()
    assert cal.to_ist(datetime(2026, 10, 26, 9, 50, tzinfo=timezone.utc)).hour == 15
    with pytest.raises(cal.CalendarError):
        cal.session_bounds(date(2026, 10, 25))


def test_weekly_and_monthly_expiries_move_back_over_holidays():
    assert cal.weekly_expiry(date(2026, 10, 26)) == date(2026, 10, 27)          # NIFTY Tuesday
    assert cal.weekly_expiry(date(2026, 10, 28)) == date(2026, 11, 3)
    assert cal.weekly_expiry(date(2026, 11, 4)) == date(2026, 11, 9)            # 10 Nov holiday -> Monday
    assert cal.weekly_expiry(date(2026, 11, 24 - 3)) == date(2026, 11, 23)      # 24 Nov holiday
    assert cal.weekly_expiry(date(2026, 10, 26), weekday=3) == date(2026, 10, 29)   # SENSEX Thursday
    assert cal.monthly_expiry(2026, 10) == date(2026, 10, 27)
    assert cal.monthly_expiry(2026, 11) == date(2026, 11, 23)                   # last Tuesday 24 Nov is a holiday


def test_first_listed_expiry_after_a_date():
    listed = ["2026-10-27", "2026-11-03T00:00:00", date(2026, 11, 10)]
    assert cal.first_expiry_after(listed, date(2026, 10, 27)) == date(2026, 11, 3)
    assert cal.first_expiry_after(listed, date(2026, 11, 10)) is None


def test_events_spanning_an_interval():
    assert cal.events_between(date(2026, 12, 3), date(2026, 12, 4)) == [(date(2026, 12, 4), "rbi")]
    assert cal.events_between(date(2026, 10, 26), date(2026, 10, 27)) == []
    assert cal.events_between(date(2027, 1, 29), date(2027, 2, 1)) == [(date(2027, 2, 1), "budget")]


def test_lot_tick_and_unknown_instruments():
    assert ins.lot_size("NIFTY", date(2026, 10, 26)) == 65
    assert ins.spec("NIFTY", "OPT", date(2026, 10, 26)).strike_step == 50
    with pytest.raises(ins.UnknownInstrument):
        ins.lot_size("NIFTY", date(2025, 6, 1))
    with pytest.raises(ins.UnknownInstrument):
        ins.lot_size("FINNIFTY", date(2026, 10, 26))


def test_limit_prices_round_against_aggressiveness():
    assert ins.round_to_tick(100.03, 0.05, 1) == 100.0                # a buy rounds down
    assert ins.round_to_tick(100.03, 0.05, -1) == 100.05              # a sale rounds up
    assert ins.round_to_tick(100.05, 0.05, 1) == 100.05 and ins.round_to_tick(100.05, 0.05, -1) == 100.05


def test_sessions_to_2026_never_change():
    """GS-SIP-1 is frozen on this calendar: an extension (e.g. NSE's 2027 holidays) may only ADD later dates."""
    import hashlib
    xs = cal.sessions(date(2022, 1, 1), date(2026, 12, 31))
    assert len(xs) == 1232
    assert hashlib.sha256(",".join(d.isoformat() for d in xs).encode()).hexdigest() == "d63eb48dd1f31eb3b0458b638a8af2fd1938411449ea128a9b173ad46ccc67de"

