"""Tests for tools/range_vs_implied.py on synthetic databases (no real data)."""
import math
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import range_vs_implied as rv  # noqa: E402


def test_trading_hours_left_counts_weekdays_and_today():
    assert rv.trading_hours_left(datetime(2026, 10, 26, 11, 30), date(2026, 10, 27)) == pytest.approx(4 + 6.25)
    # Friday 15:00 to Tuesday's close: 0.5 + Monday + Tuesday (the weekend is skipped)
    assert rv.trading_hours_left(datetime(2026, 10, 23, 15, 0), date(2026, 10, 27)) == pytest.approx(0.5 + 12.5)


def test_straddle_and_iv_routes_agree_when_hours_match_calendar_time():
    s, sigma, hours = 25000.0, 0.15, 6.25 * 5
    T = 7 / 365                                                     # a week of calendar time
    straddle = s * sigma * math.sqrt(T) * math.sqrt(2 / math.pi)
    a = rv.implied_range(straddle, s, hours)
    b = math.sqrt(8 / math.pi) * sigma * math.sqrt(T) / math.sqrt(hours)
    assert a == pytest.approx(b)


def make_dbs(tmp_path, realized):
    con = sqlite3.connect(tmp_path / "study_chain_20261026.db")
    con.execute("create table chain (ts text, underlying text, expiry text, spot real, strike real, typ text, key text,"
                " ltp real, bid real, ask real, bid_qty real, ask_qty real, volume real, oi real, iv real, delta real,"
                " gamma real, theta real, vega real)")
    for k in (24950.0, 25000.0, 25050.0):
        for typ in ("CE", "PE"):
            for e in ("2026-10-26", "2026-10-27"):
                con.execute("insert into chain values (?,?,?,?,?,?,'',0,?,?,0,0,0,0,15,0,0,0,0)",
                            ("2026-10-26T10:30:46", "NIFTY", e, 25010.0, k, typ, 99.0, 101.0))
    con.commit()
    con.close()
    con = sqlite3.connect(tmp_path / "nfce.db")
    con.execute("create table range_forecasts (root text, bar_close text, model text, ts text, price real, q10 real,"
                " q50 real, q90 real, realized real)")
    con.execute("insert into range_forecasts values ('NIFTY', '2026-10-26T10:30:00+05:30', 'M1', '', 25010, -5.8, -5.3,"
                " -4.8, ?)", (realized,))
    con.commit()
    con.close()


def test_measure_uses_the_first_snapshot_and_skips_the_expiring_contract(tmp_path):
    make_dbs(tmp_path, -5.2)
    m = rv.measure("2026-10-26", tmp_path)
    assert len(m) == 1 and m["expiry"].iloc[0] == "2026-10-27" and m["straddle"].iloc[0] == pytest.approx(200.0)
    hl = rv.trading_hours_left(datetime(2026, 10, 26, 10, 30), date(2026, 10, 27))
    assert m["log_implied"].iloc[0] == pytest.approx(math.log(rv.implied_range(200.0, 25010.0, hl)))
    s = rv.summarize(m).iloc[0]
    assert s["model_mae"] == pytest.approx(0.1) and s["band80"] == 1.0
    assert s["model_over_implied"] == pytest.approx(np.exp(-5.3 - m["log_implied"].iloc[0]))


def test_unrealized_forecasts_are_not_scored(tmp_path):
    make_dbs(tmp_path, None)
    assert rv.summarize(rv.measure("2026-10-26", tmp_path)).empty


def test_trading_hours_skip_exchange_holidays(monkeypatch):
    """GS phase 0 correction: 24 Nov 2026 (Guru Nanak Jayanti) is not a trading day."""
    now, exp = datetime(2026, 11, 23, 15, 0), date(2026, 11, 26)
    assert rv.trading_hours_left(now, exp) == pytest.approx(0.5 + 2 * 6.25)
    monkeypatch.setattr(rv, "HOLIDAY_FIX", False)
    assert rv.trading_hours_left(now, exp) == pytest.approx(0.5 + 3 * 6.25)    # the registered pilot's count
