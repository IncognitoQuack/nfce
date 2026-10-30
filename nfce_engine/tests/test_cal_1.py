"""CAL-1 trade dates (tools/cal_1.py, ../evidence/cal_1_protocol.md) on a hand-made calendar."""
import pandas as pd

from tools import cal_1 as c


def test_turn_of_month_and_pre_holiday_dates():
    idx = pd.bdate_range("2026-03-25", "2026-04-10")
    idx = idx[idx != pd.Timestamp("2026-04-03")]                       # a Friday holiday
    close = pd.Series(range(100, 100 + len(idx)), index=idx, dtype=float)
    p = c.trades(close)
    d = lambda i: close.index[i].date().isoformat()                   # noqa: E731
    assert [(d(i), d(j)) for i, j in p["C1"]] == [("2026-03-30", "2026-04-06")]   # close day -2 -> close day +3
    assert [(d(i), d(j)) for i, j in p["C2"]] == [("2026-04-01", "2026-04-02")]   # into the pre-holiday session
    assert c.holidays(close.index) == {pd.Timestamp("2026-04-03").date()}


def test_costs_and_carry_are_deducted():
    idx = pd.bdate_range("2026-03-25", "2026-04-10")
    close = pd.Series(22000.0, index=idx)
    r = c.score(close, [(0, 5)], idx[0].date(), idx[-1].date())[0]
    assert r["gross_bp"] == 0 and r["net_bp"] < -10                  # flat price still pays fees + carry
