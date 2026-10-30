"""Daily candles: today's bar comes from the intraday endpoint (the historical one ends yesterday). No network here."""
import datetime as dt

from ops import pull_daily as pdl

HIST = [["2026-10-27T00:00:00+05:30", 22600, 22760, 22560, 22749.75, 0, 0],
        ["2026-10-26T00:00:00+05:30", 22700, 22780, 22590, 22650.0, 0, 0]]
TODAY = [["2026-10-28T00:00:00+05:30", 22594.3, 22720, 22550, 22698.0, 0, 0]]


def test_frame_is_sorted_by_date():
    d = pdl.frame(HIST)
    assert [x.isoformat() for x in d.index.date] == ["2026-10-26", "2026-10-27"] and d.close.iloc[-1] == 22749.75


def test_today_is_appended_once_and_only_when_dated_today():
    d = pdl.with_today(pdl.frame(HIST), TODAY, dt.date(2026, 10, 28))
    assert d.index[-1].date() == dt.date(2026, 10, 28) and d.close.iloc[-1] == 22698.0 and len(d) == 3
    again = pdl.with_today(d, TODAY, dt.date(2026, 10, 28))
    assert len(again) == 3                                            # not duplicated on a second run
    assert len(pdl.with_today(pdl.frame(HIST), TODAY, dt.date(2026, 10, 29))) == 2   # a stale "today" is ignored
    assert len(pdl.with_today(pdl.frame(HIST), [], dt.date(2026, 10, 28))) == 2
