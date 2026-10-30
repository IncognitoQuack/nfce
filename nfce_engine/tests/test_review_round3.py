"""Independent review, round 3: engine findings, each reproduced with the reviewer's failure scenario."""
import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce import Params, prepare, run  # noqa: E402
from nfce.data import DataError, validate  # noqa: E402
from nfce.options_exec import execute  # noqa: E402
from nfce.registry import day_means, judge_r1, judge_r3  # noqa: E402
from nfce.registry_r4 import judge_r4  # noqa: E402
from nfce.research2 import _walk, noise_area  # noqa: E402

TZ = "Asia/Kolkata"
T = pd.Timestamp("2026-10-21 10:00:00", tz=TZ)
DAYS = [date(2026, 10, d) for d in (21, 22, 23, 26, 27, 28)]


# ---------- H01: option fills in time order ----------
def oq(rows):
    return pd.DataFrame([{"time": T + pd.Timedelta(seconds=s), "expiry": date(2026, 10, 27), "strike": 24950.0,
                          "type": "CE", "bid": b, "ask": a} for s, b, a in rows])


def test_H01_exit_before_entry_is_skipped_not_booked():
    q = oq([(5, 100, 101), (1, 110, 111)])
    (f,) = execute([{"decision_time": T, "exit_time": T + pd.Timedelta(seconds=1), "side": 1, "spot": 25000}], q, DAYS)
    assert f.skipped and f.net_inr == 0.0


def test_H01_entry_quote_after_the_exit_decision_is_skipped():
    q = oq([(120, 100, 101), (130, 110, 111)])                     # first entry quote only after the exit decision
    (f,) = execute([{"decision_time": T, "exit_time": T + pd.Timedelta(seconds=60), "side": 1, "spot": 25000}], q, DAYS,
                   max_quote_gap_s=200)
    assert f.skipped == "entry quote arrives after the exit decision"


def test_H01_crossed_or_infinite_quotes_are_ignored():
    q = oq([(10, 105, 101), (11, np.inf, 102), (3600, 120, 121)])  # crossed, infinite: no valid entry quote nearby
    (f,) = execute([{"decision_time": T, "exit_time": T + pd.Timedelta(seconds=3600), "side": 1, "spot": 25000}], q, DAYS)
    assert f.skipped


def test_H01_stress_widens_both_spreads():
    q = oq([(10, 100, 102), (3600, 120, 122)])
    (f,) = execute([{"decision_time": T, "exit_time": T + pd.Timedelta(seconds=3600), "side": 1, "spot": 25000}], q, DAYS)
    assert f.stressed_net_inr == pytest.approx(f.net_inr - 0.25 * (2 + 2) * 65)


# ---------- H08: futures leg uses the day's front contract and bounded, same-session quotes ----------
def test_H08_futures_quotes_from_another_session_never_pair():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools.registry_eval import _fill, _futures_quotes
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE quotes (ts TEXT, key TEXT, bid REAL, ask REAL)")
    con.execute("CREATE TABLE contracts (key TEXT, root TEXT, expiry TEXT, lot_size INTEGER, day TEXT)")
    nxt = (T + pd.Timedelta(days=1)).tz_convert("UTC").isoformat()
    con.execute("INSERT INTO quotes VALUES (?, 'NSE_FO|OCT', 25000, 25000.2)", (nxt,))
    con.execute("INSERT INTO contracts VALUES ('NSE_FO|OCT', 'NIFTY', '2026-10-27', 65, '2026-10-22')")
    fq = _futures_quotes(con, None)
    assert _fill(fq, T, T, 60) is None                           # only next-day quotes: no pair


def test_H08_each_day_uses_the_contract_that_was_front_that_day():
    from tools.registry_eval import _futures_quotes
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE quotes (ts TEXT, key TEXT, bid REAL, ask REAL)")
    con.execute("CREATE TABLE contracts (key TEXT, root TEXT, expiry TEXT, lot_size INTEGER, day TEXT)")
    for key, day in (("NSE_FO|OCT", "2026-10-27"), ("NSE_FO|NOV", "2026-10-28")):
        for k2 in ("NSE_FO|OCT", "NSE_FO|NOV"):                  # both contracts quoted on both days
            ts = pd.Timestamp(f"{day} 10:00", tz=TZ).tz_convert("UTC").isoformat()
            con.execute("INSERT INTO quotes VALUES (?, ?, 1, 2)", (ts, k2))
        con.execute("INSERT INTO contracts VALUES (?, 'NIFTY', '', 65, ?)", (key, day))
    fq = _futures_quotes(con, None)
    assert sorted(zip(fq.day, fq.key)) == [("2026-10-27", "NSE_FO|OCT"), ("2026-10-28", "NSE_FO|NOV")]


# ---------- H09: target on the entry bar ----------
def bars_hm(rows):
    d = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    d["hm"] = [600 + 5 * i for i in range(len(d))]
    return d


def test_H09_target_reached_on_the_entry_bar_is_taken():
    d = bars_hm([(100, 112, 99, 111), (111, 111, 89, 90)])        # entry 100 at the open, target 110 that bar
    assert _walk(d, 0, 1, 90.0, 110.0)[:2] == (110.0, "target")


def test_H09_stop_and_target_in_the_entry_bar_takes_the_stop():
    d = bars_hm([(100, 112, 89, 100), (100, 101, 99, 100)])
    assert _walk(d, 0, 1, 90.0, 110.0)[:2] == (90.0, "stop")


# ---------- H10: an incomplete day keeps its open trade ----------
def session(day, n, start=100.0, drift=0.0):
    idx = pd.date_range(pd.Timestamp(f"{day} 09:15", tz=TZ), periods=n, freq="5min")
    c = start * np.exp(np.cumsum(np.full(n, drift)))
    o = np.r_[start, c[:-1]]
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.0001, "low": np.minimum(o, c) * 0.9999, "close": c,
                         "volume": 1000.0}, index=idx)


def test_H10_noise_area_never_drops_an_open_position():
    days = pd.bdate_range("2026-08-03", periods=20)
    full = pd.concat([session(d.date(), 75, 100 * (1.0005 ** k), 0.0) for k, d in enumerate(days[:-1])]
                     + [session(days[-1].date(), 75, 100 * 1.01, 0.002)])
    cut = full[full.index < pd.Timestamp(f"{days[-1].date()} 12:00", tz=TZ)]
    a = [t for t in noise_area(full) if t["day"] == days[-1].date()]
    b = [t for t in noise_area(cut) if t["day"] == days[-1].date()]
    assert a and b and len(a) == len(b)
    assert b[-1]["reason"] == "eod_incomplete"


# ---------- H13: a missing square-off bar never becomes a next-day "normal" exit ----------
def test_H13_session_without_its_closing_bars_is_unresolved():
    from test_engine import LOOSE, sim_bars
    bars = sim_bars()
    base = run(prepare(bars, 5, LOOSE), LOOSE)
    t0 = next(t for t in base if t.exit == "Q")                   # a trade squared off at 15:15 on its day
    day = t0.entry_time.tz_convert(TZ).normalize()
    hm = bars.index.hour * 60 + bars.index.minute
    cut = bars[~((bars.index.normalize() == day) & (hm >= 15 * 60 + 10))]   # that day's closing bars are missing
    out = run(prepare(cut, 5, LOOSE), LOOSE)
    (t1,) = [t for t in out if t.entry_time == t0.entry_time]
    assert t1.exit == "U" and t1.exit_time.tz_convert(TZ).normalize() == day   # never a "normal" next-day exit


def test_H13_unresolved_trades_are_excluded_from_reports():
    from nfce.stats import CostModel, report
    from nfce.engine import Trade
    t = lambda ex: Trade(T, "L", 70, False, 25000, 40, 10, ex, 3, T + pd.Timedelta(minutes=15))   # noqa: E731
    r = report([t("3"), t("U")], CostModel("current", lot_units=65, lots=10))
    assert r["n"] == 1 and r["unresolved"] == 1


# ---------- H11: parity verdict ----------
def test_H11_any_position_or_ledger_difference_fails_parity():
    from tools.golden_parity import judge
    assert judge([], True, True, True, True, 0) == ("PARITY", [])
    assert judge([], True, True, False, True, 0)[0] == "DIFFERENCES"            # 99.56% position agreement
    assert judge([], True, True, True, True, 1)[0] == "DIFFERENCES"             # one trade field off
    assert judge([], True, True, True, False, 0)[0] != "PARITY"                 # no ledger: never plain PARITY


# ---------- M04 / M05: registry statistics ----------
def test_M04_empty_pass_group_is_inconclusive_not_an_exception():
    assert judge_r3([], [0.1] * 200).result == "INCONCLUSIVE"


def test_M05_tests_run_on_day_means():
    assert day_means([1.0, 3.0, 5.0], ["a", "a", "b"]) == [2.0, 5.0]
    # 200 trades, but all on 5 days: clustered inference must not be as confident as 200 independent trades
    rng = np.random.default_rng(1)
    days = [f"d{i % 5}" for i in range(200)]
    shock = {f"d{k}": rng.normal(0, 1) for k in range(5)}
    opt = [0.3 + shock[d] + rng.normal(0, 0.1) for d in days]
    fut = [0.0] * 200
    v_iid = judge_r1(opt, fut, 0)
    v_day = judge_r1(opt, fut, 0, days)
    assert v_day.result == "INCONCLUSIVE"                       # 5 sessions < 100 required
    assert v_iid.result in ("PASS", "FAIL")


def test_M05_r4_reports_absolute_results_next_to_the_relative_test():
    pairs = [(-0.3, -0.2)] * 120
    v = judge_r4(pairs, [f"d{i % 60}" for i in range(120)])
    assert "absolute results" in v.note and "not a reason to trade" in v.note


# ---------- M06: preparation fingerprint ----------
def test_M06_extra_expiry_dates_are_part_of_the_fingerprint():
    from test_engine import sim_bars
    bars = sim_bars(days=10)
    pr = prepare(bars, 5, Params(instr="NIFTY"))
    with pytest.raises(ValueError, match="prepare"):
        run(pr, Params(instr="NIFTY", extra_expiry_dates=frozenset({date(2026, 6, 4)})))


# ---------- M07: validation ----------
def test_M07_infinite_or_non_positive_prices_are_rejected():
    d = session(date(2026, 8, 3), 75)
    d.iloc[3, 0:4] = np.inf
    with pytest.raises(DataError, match="infinite"):
        validate(d, "x", 5)
    d = session(date(2026, 8, 3), 75)
    d.index = d.index.tz_localize(None)
    with pytest.raises(DataError, match="time zone"):
        validate(d, "x", 5)
