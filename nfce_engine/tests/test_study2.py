"""Tests for study engine v2 (tools/study2.py), on synthetic frames: no real data files are read."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import study as s1  # noqa: E402
from tools import study2 as s2  # noqa: E402

TZ = "Asia/Kolkata"


def day_bars(date, path, tf=3, vol=1000.0):
    """path: list of (o, h, l, c); the rest of the session is flat at the last close."""
    n = 375 // tf
    full = list(path) + [(path[-1][3],) * 4] * (n - len(path))
    idx = pd.date_range(f"{date} 09:15", periods=n, freq=f"{tf}min", tz=TZ)
    v = np.full(n, vol)
    return pd.DataFrame(full, columns=["open", "high", "low", "close"], index=idx).assign(volume=v, oi=0.0)


def history(n, px=100.0, rng=2.0, start="2023-01-02", tf=3, vol=1000.0):
    return [day_bars(d.date(), [(px, px + rng / 2, px - rng / 2, px)], tf, vol) for d in pd.bdate_range(start, periods=n)]


# ---------------------------------------------------------------- costs
def test_equity_intraday_fees_by_hand():
    f = s2.equity_intraday_fees(1000.0, 1010.0, 1, 300)
    bv, sv = 300_000.0, 303_000.0
    brk, exch, sebi = 40.0, 0.0000322 * (bv + sv), 1e-6 * (bv + sv)
    assert f == pytest.approx(0.00025 * sv + exch + sebi + 0.00003 * bv + brk + 0.18 * (brk + exch + sebi))
    # a short pays STT on the entry (the sale)
    fs = s2.equity_intraday_fees(1000.0, 990.0, -1, 300)
    assert fs == pytest.approx(0.00025 * 300_000 + 0.0000322 * 597_000 + 1e-6 * 597_000 + 0.00003 * 297_000 + 40
                               + 0.18 * (40 + 0.0000322 * 597_000 + 1e-6 * 597_000))


def test_cash_equity_is_cheaper_than_futures_and_the_open_costs_more():
    e, x = np.array([1000.0]), np.array([1005.0])
    eq, _ = s2.stock_cost(e, x, 1, np.array([False]))
    fut, _ = s2.stock_cost(e, x, 1, np.array([False]), "FUT")
    eq_open, _ = s2.stock_cost(e, x, 1, np.array([True]))
    assert eq[0] < fut[0] and eq_open[0] > eq[0]
    assert 0.0010 < eq[0] / 1000 < 0.0016                      # ~12-13 bp round trip


def test_depth_cost_walks_the_book():
    book = [{"price": 100.1, "quantity": 1000}, {"price": 100.2, "quantity": 1000}]
    assert s2.depth_cost(book, 100_100, 100.0) == pytest.approx(0.001)
    two = s2.depth_cost(book, 100_100 + 100_200, 100.0)
    assert two == pytest.approx((100_100 * 0.001 + 100_200 * 0.002) / 200_300)
    beyond = s2.depth_cost(book, 400_000, 100.0)
    assert beyond > 0.002


# ---------------------------------------------------------------- ORB (H1/H2/H3)
def orb_frame():
    hist = history(15)
    # day 16: opening range 100..101 (up candle), breakout at bar 5 above 101.0, then drifts up to 103
    path = [(100.0, 100.8, 100.0, 100.6), (100.6, 101.0, 100.4, 100.9), (100.9, 100.95, 100.7, 100.8),
            (100.8, 100.9, 100.6, 100.7), (100.7, 100.95, 100.6, 100.9), (100.9, 101.5, 100.9, 101.4),
            (101.4, 103.0, 101.3, 103.0)]
    last = day_bars(pd.bdate_range("2023-01-02", periods=16)[-1].date(), path, vol=3000.0)
    return s1.frame(pd.concat(hist + [last]), 3)


def test_orb_enters_at_the_range_high_after_the_range_and_holds_to_the_close():
    d = orb_frame()
    g = s1.make_grid(d, 3)
    c = s2.orb_candidates(d, g, "XYZ", set())
    el = c[c["hyp"] == "ELIG"]
    assert len(el) == 1 and el["rvol"].iloc[0] == pytest.approx(3.0)
    h1 = c[c["hyp"] == "H1"].iloc[0]
    atr = d["atr_prev"].iloc[-1]
    assert h1["side"] == 1 and h1["entry"] == pytest.approx(101.0)
    assert h1["R"] == pytest.approx(0.10 * atr) and h1["exit"] == pytest.approx(103.0)
    assert h1["net_r"] < h1["gross_r"] and not h1["results"]


def test_orb_entries_before_0930_pay_the_open_slippage(monkeypatch):
    """GS phase 0 correction (review A finding 1): the 09:21-09:27 entry bars pay EQ_SLIP_OPEN; 09:30 on does not."""
    hist = history(15)
    early = [(100.0, 100.8, 100.0, 100.6), (100.6, 101.0, 100.4, 100.9), (100.9, 101.6, 100.9, 101.5),
             (101.5, 103.0, 101.4, 103.0)]                               # breaks out in the 09:21 bar
    day = pd.bdate_range("2023-01-02", periods=16)[-1].date()
    d = s1.frame(pd.concat(hist + [day_bars(day, early, vol=3000.0)]), 3)
    g = s1.make_grid(d, 3)
    h2 = s2.orb_candidates(d, g, "XYZ", set()).query("hyp == 'H2'").iloc[0]
    assert bool(h2["open_entry"])
    c_open, u = s2.stock_cost(np.array([h2["entry"]]), np.array([h2["exit"]]), 1, np.array([True]))
    assert h2["net_inr"] == pytest.approx(((h2["exit"] - h2["entry"]) - c_open[0]) * u[0])
    monkeypatch.setattr(s2, "ORB_OPEN_COST_FIX", False)                 # the registered run's behaviour
    old = s2.orb_candidates(d, g, "XYZ", set()).query("hyp == 'H2'").iloc[0]
    assert not bool(old["open_entry"]) and old["net_inr"] > h2["net_inr"]
    late = orb_frame()                                                   # breaks out in the 09:30 bar
    monkeypatch.setattr(s2, "ORB_OPEN_COST_FIX", True)
    h2l = s2.orb_candidates(late, s1.make_grid(late, 3), "XYZ", set()).query("hyp == 'H2'").iloc[0]
    assert not bool(h2l["open_entry"])


def test_orb_skips_days_without_14_days_of_opening_volume():
    d = s1.frame(pd.concat(history(10)), 3)
    c = s2.orb_candidates(d, s1.make_grid(d, 3), "XYZ", set())
    assert c.empty or (c["hyp"] == "ELIG").sum() == 0


def test_top20_is_chosen_from_all_eligible_stocks_not_only_triggered_ones():
    day = pd.Timestamp("2024-01-02")
    el = pd.DataFrame({"day": day, "sym": [f"S{i:02d}" for i in range(25)], "hyp": "ELIG", "rvol": np.arange(25, 0, -1.0)})
    tr = pd.DataFrame({"day": day, "sym": ["S00", "S22"], "hyp": "H2", "rvol": [25.0, 3.0], "side": 1,
                       "results": [False, True], "net_r": [0.1, 0.2]})
    out = s2.select(pd.concat([el, tr], ignore_index=True))
    assert out["H2"]["sym"].tolist() == ["S00"]                 # S22 triggered but ranked 23rd at 09:21
    assert out["H3"]["sym"].tolist() == ["S22"]                 # results days take every eligible stock


def test_results_days_are_the_meeting_session_and_the_next():
    ses = pd.bdate_range("2024-01-01", periods=10).to_numpy()
    cal = pd.DataFrame({"symbol": ["XYZ", "XYZ", "ABC"], "date": pd.to_datetime(["2024-01-06", "2024-01-03", "2024-01-03"]),
                        "results": [1, 0, 1]})
    got = s2.results_days_of("XYZ", cal, ses)
    assert got == {pd.Timestamp("2024-01-08"), pd.Timestamp("2024-01-09")}   # Saturday meeting -> Monday, Tuesday


# ---------------------------------------------------------------- H6 / H4-H5 / gaps
def test_eod_reversal_buys_the_day_losers_and_sells_the_winners():
    rows = []
    for i in range(30):
        for side in (1, -1):
            rows.append({"day": pd.Timestamp("2024-01-02"), "sym": f"S{i:02d}", "hyp": "H6", "side": side, "ret": i / 100})
    out = s2.select(pd.DataFrame(rows))["H6"]
    assert set(out.loc[out["side"] > 0, "sym"]) == {f"S{i:02d}" for i in range(10)}
    assert set(out.loc[out["side"] < 0, "sym"]) == {f"S{i:02d}" for i in range(20, 30)}


def test_eod_candidates_use_the_1457_close_and_trade_1457_to_1518():
    hist = history(15)
    path = [(100.0, 100.5, 99.5, 100.0)] * 113 + [(100.0, 102.1, 99.9, 102.0), (102.0, 102.2, 101.8, 102.1)] \
        + [(102.1, 102.2, 101.5, 101.6)] * 6
    last = day_bars(pd.bdate_range("2023-01-02", periods=16)[-1].date(), path)
    d = s1.frame(pd.concat(hist + [last]), 3)
    c = s2.eod_candidates(d, s1.make_grid(d, 3), "XYZ")
    r = c[c["day"] == c["day"].max()]
    assert r["ret"].iloc[0] == pytest.approx(0.02)
    assert r["entry"].iloc[0] == pytest.approx(102.0) and r["exit"].iloc[0] == pytest.approx(101.6)


def test_index_momentum_follows_the_sign_of_the_signal():
    hist = history(15, px=20000.0, rng=100.0, tf=5)
    path = [(20000.0, 20010.0, 19990.0, 20000.0)] * 5 + [(20000.0, 20110.0, 20000.0, 20100.0)] \
        + [(20100.0, 20110.0, 20090.0, 20100.0)] * 63 + [(20100.0, 20150.0, 20100.0, 20150.0)] * 6
    last = day_bars(pd.bdate_range("2023-01-02", periods=16)[-1].date(), path, tf=5)
    d = s1.frame(pd.concat(hist + [last]), 5)
    t = s2.index_trades(d, "NIFTY", (65, 0.1))
    h4 = t[(t["hyp"] == "H4") & (t["day"] == t["day"].max())].iloc[0]
    assert h4["side"] == 1 and h4["entry"] == pytest.approx(20100.0) and h4["exit"] == pytest.approx(20150.0)


def test_gap_in_atr_units_and_the_v1_lead_rule():
    hist = history(20, rng=2.0)                                  # ATR ~ 2 points
    path = [(97.0, 97.5, 96.8, 97.2), (97.2, 97.4, 97.0, 97.3)]  # opens 3 below the prior close: -3%, -1.5 ATR
    last = day_bars(pd.bdate_range("2023-01-02", periods=21)[-1].date(), path)
    d = s1.frame(pd.concat(hist + [last]), 3)
    lo = pd.Series("VIXLO", index=pd.DatetimeIndex(d["day"].unique()))
    t = s2.gap_trades(d, s1.make_grid(d, 3), "XYZ", lo)
    assert set(t["hyp"]) == {"H7", "H8"} and (t["side"] == 1).all()
    hi = pd.Series("VIXHI", index=pd.DatetimeIndex(d["day"].unique()))
    assert set(s2.gap_trades(d, s1.make_grid(d, 3), "XYZ", hi)["hyp"]) == {"H8"}


# ---------------------------------------------------------------- statistics glue
def test_acc_of_and_summarize_agree_with_the_trades():
    days = pd.bdate_range("2024-01-01", periods=60)
    rng = np.random.default_rng(0)
    t = pd.DataFrame({"day": np.repeat(days, 3), "side": 1, "entry": 100.0, "exit": 100.0, "R": 1.0,
                      "gross_r": rng.normal(0.1, 1, 180), "reason": "eod"})
    t["net_r"] = t["gross_r"] - 0.05
    t["net_bp"] = t["net_r"] * 10
    t["net_inr"] = t["net_r"] * 100
    s = s2.summarize({"trades": {"H2": t}, "days": days})["H2"]
    assert s["n"] == 180 and s["net_r"] == pytest.approx(t["net_r"].mean())
    assert s["ci"][0] < s["net_r"] < s["ci"][1]
    assert s2.gate(s) == (s["net_r"] > 0)
