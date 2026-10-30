import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce.research import daily_atr_prev, expiry_dates, momentum, orb, vwap_trend  # noqa: E402

TZ = "Asia/Kolkata"


def day5(date, path, vol=1000.0):
    """path: list of (o, h, l, c) for consecutive 5m bars from 09:15."""
    idx = pd.date_range(f"{date} 09:15", periods=len(path), freq="5min", tz=TZ)
    return pd.DataFrame(path, columns=["open", "high", "low", "close"], index=idx).assign(volume=vol)


def flat_day(date, px=100.0, n=75):
    return day5(date, [(px, px + 0.5, px - 0.5, px)] * n)


def test_orb_long_breakout_eod_and_one_trade_a_day():
    path = [(100, 102, 98, 100)] * 6 + [(100, 103, 100, 102.5)] + [(102.5, 104, 102, 103)] * 68   # 30m range 98-102
    (t,) = orb(day5("2026-01-05", path), or_min=30)
    assert t["side"] == 1 and t["entry"] == 102.5 and t["risk"] == pytest.approx(4.5) and t["reason"] == "eod"
    assert t["exit"] == 103 and str(t["entry_time"].time()) == "09:50:00"


def test_orb_stop_is_checked_first_and_gap_fills_at_open():
    path = [(100, 102, 98, 100)] * 6 + [(100, 103, 100, 102.5)] + [(97, 97.5, 96, 96.5)] + [(96, 97, 95, 96)] * 67
    (t,) = orb(day5("2026-01-05", path), or_min=30)                # opens below the 98 stop -> filled at the open 97
    assert t["reason"] == "stop" and t["exit"] == 97


def test_orb_two_r_target_and_mid_stop():
    path = [(100, 102, 98, 100)] * 6 + [(100, 103, 100, 102.5)] + [(102.5, 108, 102.4, 107)] + [(107, 107, 106, 106)] * 67
    (t,) = orb(day5("2026-01-05", path), or_min=30, stop="mid", exit="2R")      # mid 100, risk 2.5, target 107.5
    assert t["reason"] == "target" and t["exit"] == pytest.approx(107.5)


def test_orb_skips_incomplete_opening_range_and_late_breakouts():
    assert orb(day5("2026-01-05", [(100, 102, 98, 100)] * 3), or_min=30) == []
    late = [(100, 102, 98, 100)] * 50 + [(100, 103, 100, 102.5)] * 25           # first breakout after 13:00
    assert orb(day5("2026-01-05", late), or_min=30) == []


def test_momentum_uses_previous_complete_close_and_trades_afternoon():
    d1 = flat_day("2026-01-05", 100)
    p = [(100, 100.5, 99.5, 100)] * 11 + [(100, 101.5, 100, 101)] + [(101, 101.5, 100.5, 101)] * 63   # bar 11 = 10:10, closes 101
    p[63] = (101, 101, 101, 101)                                                  # 14:30 bar opens 101
    p[74] = (102, 102, 102, 102)                                                  # 15:25 bar closes 102
    d2 = day5("2026-01-06", p)
    hist = pd.concat([flat_day(f"2025-12-{d:02d}") for d in range(1, 20)] + [d1, d2])
    t = [x for x in momentum(hist) if x["day"] == dt.date(2026, 1, 6)]
    assert len(t) == 1 and t[0]["side"] == 1 and t[0]["entry"] == 101 and t[0]["exit"] == 102


def test_vwap_trend_needs_vwap_and_ema_agreement():
    def up(k):                                                                     # one steady uptrend across days
        return [(100 + (k * 75 + i) * 0.1, 100.2 + (k * 75 + i) * 0.1, 99.9 + (k * 75 + i) * 0.1,
                 100.1 + (k * 75 + i) * 0.1) for i in range(75)]
    hist = pd.concat([day5(f"2026-01-0{d}", up(k)) for k, d in enumerate((5, 6, 7))])
    t = vwap_trend(hist)
    assert t and all(x["side"] == 1 for x in t) and all(str(x["entry_time"].time()) == "10:15:00" for x in t)


def test_daily_atr_is_previous_days_only():
    hist = pd.concat([flat_day(f"2025-12-{d:02d}") for d in range(1, 25)])
    a = daily_atr_prev(hist)
    assert np.isnan(a.iloc[0]) and a.iloc[-1] == pytest.approx(1.0)


def test_historical_expiry_calendar():
    sess = [d.date() for d in pd.bdate_range("2025-08-18", "2025-09-12")]
    sess.remove(dt.date(2025, 8, 28))                                             # a Thursday holiday
    e = expiry_dates(sess, "NIFTY")
    assert dt.date(2025, 8, 21) in e and dt.date(2025, 8, 27) in e                # Thursday; holiday -> Wednesday
    assert dt.date(2025, 9, 2) in e and dt.date(2025, 9, 9) in e                  # Tuesday from Sep 2025
    b = expiry_dates([d.date() for d in pd.bdate_range("2023-08-28", "2023-09-15")], "BANKNIFTY")
    assert dt.date(2023, 8, 31) in b and dt.date(2023, 9, 6) in b and dt.date(2023, 9, 13) in b   # Thu -> Wed
