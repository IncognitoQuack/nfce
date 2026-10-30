import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce import costs  # noqa: E402
from nfce.options_exec import execute, pick_contract  # noqa: E402

T = pd.Timestamp("2026-10-21 10:15:00", tz="Asia/Kolkata")
DAYS = [date(2026, 10, d) for d in (21, 22, 23, 26, 27, 28)]


def quotes():
    rows = []
    for exp in (date(2026, 10, 21), date(2026, 10, 27)):
        for strike in (24900, 24950, 25000, 25050, 25100):
            for typ in ("CE", "PE"):
                for k, dt in enumerate((0, 10, 3600)):
                    rows.append({"time": T + pd.Timedelta(seconds=dt), "expiry": exp, "strike": strike, "type": typ,
                                 "bid": 100.0 + k * 10, "ask": 101.0 + k * 10})
    return pd.DataFrame(rows)


def test_contract_rule_itm_and_expiry_with_two_sessions_left():
    q = quotes()
    assert pick_contract(q, 25020, +1, T, DAYS) == (25000.0, "CE", date(2026, 10, 27))   # 21 Oct expiry = 0DTE: skipped
    assert pick_contract(q, 25020, -1, T, DAYS) == (25050.0, "PE", date(2026, 10, 27))


def test_fills_at_ask_after_delay_and_bid_at_exit_with_fees():
    (f,) = execute([{"decision_time": T, "exit_time": T + pd.Timedelta(seconds=3600), "side": 1, "spot": 25020}],
                   quotes(), DAYS)
    assert f.entry_ask == 111.0 and f.exit_bid == 120.0 and not f.skipped       # entry = first quote >= T+5s (T+10s)
    fees = costs.option_fees(111.0, 120.0, 65, date(2026, 10, 21)).total
    assert f.net_inr == pytest.approx((120.0 - 111.0) * 65 - fees)


def test_missing_quotes_are_skipped_not_imputed():
    q = quotes()
    q = q[q.time < T + pd.Timedelta(seconds=100)]
    (f,) = execute([{"decision_time": T, "exit_time": T + pd.Timedelta(seconds=3600), "side": 1, "spot": 25020}], q, DAYS)
    assert f.skipped and f.net_inr == 0.0
