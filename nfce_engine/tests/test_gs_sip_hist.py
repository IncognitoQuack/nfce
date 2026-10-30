"""tools/gs_sip_hist.py (GS-SIP-1 on 3-minute history) on synthetic stocks: no real data is read."""
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gs import calendar as cal  # noqa: E402
from gs import costs as gc  # noqa: E402
from tools import gs_sip_hist as gh  # noqa: E402

IST = "Asia/Kolkata"
SPREADS = {"_all": {b: 0.0002 for _, b in gh.BUCKETS}}              # 2 bp everywhere


def day_bars(d, path, vol=500.0, first_vol=None):
    """path: list of (o, h, l, c) for the first bars; the rest flat at the last close."""
    n = gh.SLOTS
    full = list(path) + [(path[-1][3],) * 4] * (n - len(path))
    idx = pd.date_range(f"{d} 09:15", periods=n, freq="3min", tz=IST)
    v = np.full(n, vol)
    if first_vol is not None:
        v[:2] = first_vol
    return pd.DataFrame(full, columns=["open", "high", "low", "close"], index=idx).assign(volume=v, oi=0.0)


def make_stock(tmp_path, last_day_path, n_prev=20, first_vol=1500.0):
    sessions, x = [], date(2026, 10, 14)
    while len(sessions) < n_prev + 1:
        sessions.append(x)
        x = cal.prev_session(x)
    sessions = sorted(sessions)
    frames = [day_bars(d, [(1000.0, 1010.0, 990.0, 1000.0)]) for d in sessions[:-1]]
    frames.append(day_bars(sessions[-1], last_day_path, first_vol=first_vol))
    pd.concat(frames).to_pickle(tmp_path / "AAA_3m.pkl")
    daily = pd.DataFrame({"open": 1000.0, "high": 1010.0, "low": 990.0, "close": 1000.0, "volume": 0.0, "oi": 0.0},
                         index=pd.DatetimeIndex(sessions[:-1]))
    (tmp_path / "daily").mkdir(exist_ok=True)
    daily.to_pickle(tmp_path / "daily" / "AAA_1d.pkl")
    return sessions


def breakout_path():
    p = [(1000.0, 1003.0, 999.0, 1002.0), (1002.0, 1006.0, 1001.0, 1005.0)]        # OR 999..1006, up
    p += [(1005.0, 1005.5, 1004.0, 1005.0)] * 3                                     # 09:21-09:27 inside
    p += [(1005.0, 1008.0, 1004.5, 1007.0)]                                          # 09:30 closes above 1006
    p += [(1007.2, 1007.5, 1005.0, 1006.5)]                                          # 09:33: low 1005 < limit - tick
    p += [(1006.5, 1020.0, 1006.0, 1019.0)] * 3
    return p


def test_vectorized_fees_match_the_fill_fees():
    d = date(2026, 10, 27)
    want = gc.equity_fill_fee(1, 1000.0, 83, d).total + gc.equity_fill_fee(-1, 1012.0, 83, d).total
    assert gh.equity_fees(np.array([1000.0]), np.array([1012.0]), np.array([83.0]))[0] == pytest.approx(want)


def test_stock_rows_trigger_entries_and_exits(tmp_path, monkeypatch):
    monkeypatch.setattr(gh, "DAILY", tmp_path / "daily")
    sessions = make_stock(tmp_path, breakout_path())
    rows = gh.stock_rows("AAA", tmp_path / "AAA_3m.pkl", sessions, SPREADS)
    r = rows[rows["day"] == sessions[-1]].iloc[0]
    assert r["side"] == 1 and r["boundary"] == 1006.0 and r["rvol"] == pytest.approx(3.0)
    assert r["atr"] == pytest.approx(20.0) and r["A0_trig"] == 5                      # the 09:30 bar
    assert r["A0_M_entry"] == pytest.approx(1007.2 * 1.0002)                        # next open + half-spread
    assert r["A0_P_entry"] == 1006.0                                                 # min(boundary, close - hs)
    assert bool(r["A0_P_strict"]) and bool(r["A0_P_touch"])
    assert r["A0_P_exit"] == pytest.approx(1019.0 * (1 - 0.0002))                   # out at the 15:15 open
    assert r["C3_trig"] == 5                                                          # inside 10:30 as well


def test_stop_and_gap_exits(tmp_path, monkeypatch):
    monkeypatch.setattr(gh, "DAILY", tmp_path / "daily")
    p = breakout_path()[:7] + [(1000.0, 1001.0, 990.0, 991.0)]                       # 09:36 gaps below the stop
    sessions = make_stock(tmp_path, p)
    r = gh.stock_rows("AAA", tmp_path / "AAA_3m.pkl", sessions, SPREADS)
    r = r[r["day"] == sessions[-1]].iloc[0]
    # P: filled at 1006, stop 996; the 09:36 bar opens 1000 (above), trades to 990: out at the stop, minus 2 bp
    assert r["A0_P_exit"] == pytest.approx(996.0 * (1 - 0.0002))
    # C1 (stop 1.0 ATR = 986): not hit, out at 15:15
    assert r["C1_P_exit"] == pytest.approx(991.0 * (1 - 0.0002))


def test_no_fill_when_the_next_bar_only_touches(tmp_path, monkeypatch):
    monkeypatch.setattr(gh, "DAILY", tmp_path / "daily")
    p = breakout_path()
    p[6] = (1007.2, 1007.5, 1006.0, 1006.5)                                          # low exactly at the limit
    sessions = make_stock(tmp_path, p)
    r = gh.stock_rows("AAA", tmp_path / "AAA_3m.pkl", sessions, SPREADS)
    r = r[r["day"] == sessions[-1]].iloc[0]
    assert not bool(r["A0_P_strict"]) and bool(r["A0_P_touch"])


def test_rvol_needs_14_previous_calendar_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(gh, "DAILY", tmp_path / "daily")
    sessions = make_stock(tmp_path, breakout_path(), n_prev=12)
    rows = gh.stock_rows("AAA", tmp_path / "AAA_3m.pkl", sessions, SPREADS)
    assert rows.empty or sessions[-1] not in set(rows["day"])


def fake_pool(n_stocks=6, day=date(2026, 10, 27), trig=5, net_side=1):
    rows = []
    for i in range(n_stocks):
        rows.append({"day": day, "sym": f"S{i}", "rvol": 3.0 - i * 0.1, "atr": 20.0, "pc": 1000.0, "side": 1,
                     "boundary": 1006.0, "A0_trig": trig + i, "A0_M_entry": 1000.0, "A0_M_exit": 1010.0,
                     "A0_M_xslot": 100, "A0_P_entry": 1000.0, "A0_P_exit": 1010.0, "A0_P_xslot": 100,
                     "A0_P_strict": True, "A0_P_touch": True, "A0_hs": 0.0002})
    return pd.DataFrame(rows)


def test_portfolio_caps_four_open_and_skips_budget_days():
    day = date(2026, 10, 27)
    tr, daily = gh.portfolio(fake_pool(), [day], {day: 1.0}, "A0", "M")
    assert len(tr) == 4 and set(tr["sym"]) == {"S0", "S1", "S2", "S3"}               # first come, four at once
    assert daily[day] == pytest.approx(tr["net"].sum()) and (tr["qty"] > 0).all()
    q = tr["qty"].iloc[0]
    assert q * 1000.0 <= 100_000 and q * (0.75 * 20 + 0.2) <= 1250 + 1e-6
    bday = date(2026, 2, 1)
    tr2, d2 = gh.portfolio(fake_pool(day=bday), [bday], {bday: 1.0}, "A0", "M")
    assert tr2.empty and d2[bday] == 0.0


def test_rvol_2_filter_and_quarter_size():
    day = date(2026, 10, 27)
    tr, _ = gh.portfolio(fake_pool(), [day], {day: 1.0}, "A0", "M", rvol_min=2.75)
    assert set(tr["sym"]) == {"S0", "S1", "S2"}
    full, _ = gh.portfolio(fake_pool(), [day], {day: 1.0}, "A0", "M")
    quarter, _ = gh.portfolio(fake_pool(), [day], {day: 0.25}, "A0", "M")
    assert (quarter["qty"].to_numpy() < full["qty"].to_numpy()).all()


def test_adverse_drops_the_best_quarter_and_charges_2bp():
    day = date(2026, 10, 27)
    tr = pd.DataFrame({"day": day, "sym": list("abcd"), "net": [400.0, 100.0, -50.0, 10.0], "filled": True,
                       "notional": 100_000.0})
    out = gh.adverse(tr, [day])
    assert out[day] == pytest.approx(100.0 - 50.0 + 10.0 - 3 * 20.0)
