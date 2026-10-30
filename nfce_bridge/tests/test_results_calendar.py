"""📰 results flag on stock alerts (admin, 23 Oct 11:13: "consider news, like results announcements").
Tested first (evidence/results_days_protocol.md): signals on results days did NOT do worse, so it is a flag, not a skip."""
from datetime import date

from bridge.events import ResultsCalendar


def cal(tmp_path, rows, fail=False):
    calls = []

    def fetch(d0, d1):
        calls.append((d0, d1))
        if fail:
            raise OSError("NSE unreachable")
        return rows
    return ResultsCalendar(tmp_path, fetch=fetch), calls


def test_flags_results_today_yesterday_and_tomorrow(tmp_path):
    c, calls = cal(tmp_path, [("TCS", date(2026, 10, 23)), ("INFY", date(2026, 10, 22)), ("BHEL", date(2026, 10, 26))])
    today = date(2026, 10, 23)                                          # a Friday
    c.refresh(today)
    assert "today" in c.flag("TCS", today)
    assert "yesterday" in c.flag("INFY", today) and "reaction" in c.flag("INFY", today)
    assert "Monday" in c.flag("BHEL", today) or "next trading day" in c.flag("BHEL", today)
    assert c.flag("RELIANCE", today) == ""
    c.refresh(today)
    assert len(calls) == 1                                              # once a day, cached


def test_a_failed_fetch_never_blocks_an_alert(tmp_path):
    c, _ = cal(tmp_path, [], fail=True)
    c.refresh(date(2026, 10, 23))
    assert c.flag("TCS", date(2026, 10, 23)) == ""
