"""Tests for the overnight test v2 (tools/overnight_options.py score_v2; ../evidence/overnight_options_v2_protocol.md)
on synthetic chain databases and synthetic daily bars. Never reads real data."""
import math
import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gs import calendar as cal  # noqa: E402
from gs import costs as gcosts  # noqa: E402
from nfce import costs  # noqa: E402
from tools import overnight_options as oo  # noqa: E402

COLS = ("ts text, underlying text, expiry text, spot real, strike real, typ text, key text, ltp real, bid real, "
        "ask real, bid_qty real, ask_qty real, volume real, oi real, iv real, delta real, gamma real, theta real, vega real")


def premium(spot, k, typ, scale, width=250.0):
    intrinsic = max(0.0, spot - k) if typ == "CE" else max(0.0, k - spot)
    return intrinsic + scale * math.exp(-((k - spot) / width) ** 2)


def write_day(path, day, times, spot, scale, expiries=("2026-10-27", "2026-11-03"), qty=650, drop=(), half=0.5):
    con = sqlite3.connect(path)
    con.execute(f"create table if not exists chain ({COLS})")
    rows = []
    for t in times:
        for e in expiries:
            for k in np.arange(21000, 24001, 50.0):
                for typ in ("CE", "PE"):
                    p = premium(spot, k, typ, scale)
                    bid, ask = (p - half, p + half) if (t, typ, k) not in drop else (0.0, 0.0)
                    rows.append((f"{day}T{t}", "NIFTY", e, spot, k, typ, "", p, bid, ask, qty, qty, 0, 0, 15.0,
                                 0, 0, 0, 0))
    con.executemany(f"insert into chain values ({','.join('?' * 19)})", rows)
    con.commit()
    con.close()


def write_daily(dirp, last_day, rng_pts=280.0, vix=15.0, vix_5_ago=None, n=40):
    days = [last_day]
    while len(days) < n:
        days.append(cal.prev_session(days[-1]))
    days = pd.DatetimeIndex(sorted(days))
    c = np.full(len(days), 22600.0)
    pd.DataFrame({"open": c, "high": c + rng_pts / 2, "low": c - rng_pts / 2, "close": c, "volume": 0, "oi": 0},
                 index=days).to_pickle(dirp / "NIFTY_1d.pkl")
    v = np.full(len(days), vix)
    if vix_5_ago is not None:
        v[:-1] = vix_5_ago
    pd.DataFrame({"open": v, "high": v, "low": v, "close": v, "volume": 0, "oi": 0}, index=days).to_pickle(
        dirp / "INDIAVIX_1d.pkl")


@pytest.fixture
def env(tmp_path):
    (tmp_path / "daily").mkdir()
    return tmp_path


def test_atr14_wilder_and_causality(env):
    write_daily(env / "daily", date(2026, 10, 23), rng_pts=280.0)
    d = oo.read_daily(env / "daily" / "NIFTY_1d.pkl")
    assert oo.atr14_asof(d, date(2026, 10, 23)) == pytest.approx(280.0)
    assert oo.atr14_asof(d, date(2026, 10, 26)) is None            # 26 Oct's own bar is not there: not available


def test_wings_are_one_atr_rounded_up_to_the_step():
    snap = pd.DataFrame({"expiry": "2026-11-03", "spot": 22661.7, "strike": np.arange(21000, 24001, 50.0)})
    st = oo.pick_strikes(snap, "2026-11-03", 288.9)
    assert st["K"] == 22650 and st["target"] == 300 and st["Kc"] == 22950 and st["Kp"] == 22350
    tie = oo.pick_strikes(snap.assign(spot=22675.0), "2026-11-03", 250.0)
    assert tie["K"] == 22650 and tie["target"] == 250               # a tie goes to the lower strike


def test_next_session_comes_from_the_calendar_not_the_next_file(env):
    """26 Oct entry; there is no 27 Oct file but a 28 Oct one. v1 would pair 26 -> 28; v2 exits on 27 Oct (missing),
    so the structure stays open and only then is closed from 28 Oct's quotes, flagged late."""
    write_daily(env / "daily", date(2026, 10, 23))
    write_day(env / "study_chain_20261026.db", "2026-10-26", ["15:20:30"], 22660.0, 160.0)
    write_day(env / "study_chain_20261028.db", "2026-10-28", ["09:20:10", "15:20:30"], 22660.0, 140.0,
              expiries=("2026-11-03", "2026-11-10"))
    t = oo.score_v2(env, env / "daily", date(2026, 10, 26), date(2026, 10, 28))
    r = t[t["day"] == "2026-10-26"].iloc[0]
    assert r["exit_day"] == "2026-10-27" and r["status"] == "ok" and bool(r["exit_session_late"])
    assert r["expiry"] == "2026-11-03"
    assert t[t["day"] == "2026-10-27"].iloc[0]["status"].startswith("blocked")     # no entry while legs are open
    assert t[t["day"] == "2026-10-28"].iloc[0]["status"] != "blocked (an earlier structure is unresolved)"


def test_no_ltp_substitution_unresolved_instead(env):
    write_daily(env / "daily", date(2026, 10, 23))
    write_day(env / "study_chain_20261026.db", "2026-10-26", ["15:20:30"], 22660.0, 160.0)
    drop = {(t, "CE", 22650.0) for t in ("09:20:10",)}
    write_day(env / "study_chain_20261027.db", "2026-10-27", ["09:20:10"], 22660.0, 140.0, drop=drop)
    t = oo.score_v2(env, env / "daily", date(2026, 10, 26), date(2026, 10, 27))
    r = t[t["day"] == "2026-10-26"].iloc[0]
    assert r["status"] == "unresolved (open legs)" and pd.isna(r["units"]) and pd.isna(r["net"])
    assert r["units_worst"] == pytest.approx(-r["reserve"] / 5000)
    assert t[t["day"] == "2026-10-27"].iloc[0]["status"].startswith("blocked")


def test_wings_are_not_sold_before_the_shorts_are_bought_back(env):
    write_daily(env / "daily", date(2026, 10, 23))
    write_day(env / "study_chain_20261026.db", "2026-10-26", ["15:20:30"], 22660.0, 160.0)
    drop = {("09:20:10", "PE", 22650.0)}                             # short put has no quote at 09:20, only at 09:21
    write_day(env / "study_chain_20261027.db", "2026-10-27", ["09:20:10", "09:21:10"], 22660.0, 140.0, drop=drop)
    later = [(date(2026, 10, 27), env / "study_chain_20261027.db")]
    st = {"spot": 22660.0, "K": 22650.0, "Kc": 22950.0, "Kp": 22350.0}
    es = oo.read_chain2(env / "study_chain_20261026.db")
    legs_q = [((t, k, s), oo.quote(es, "2026-11-03", t, k)) for t, k, s in oo.v2_legs(st)]
    ex = oo.close_legs(legs_q, later, "2026-11-03")
    times = {legs_q[i][0]: o[0][11:19] for i, o in enumerate(ex)}
    assert times[("PE", 22650.0, -1)] == "09:21:10" and times[("CE", 22650.0, -1)] == "09:20:10"
    assert times[("CE", 22950.0, 1)] == "09:21:10" and times[("PE", 22350.0, 1)] == "09:21:10"


def test_exit_fee_reserve_is_separate_and_covers_realized_exit_fees(env):
    write_daily(env / "daily", date(2026, 10, 23))
    write_day(env / "study_chain_20261026.db", "2026-10-26", ["15:20:30"], 22660.0, 160.0)
    write_day(env / "study_chain_20261027.db", "2026-10-27", ["09:20:10"], 22660.0, 140.0)
    t = oo.score_v2(env, env / "daily", date(2026, 10, 26), date(2026, 10, 27))
    r = t[t["day"] == "2026-10-26"].iloc[0]
    assert r["status"] == "ok" and r["lots"] >= 1
    # entry fees are computed from the four entry fills only
    es = oo.read_chain2(env / "study_chain_20261026.db")
    st = {"K": r["atm"], "Kc": r["Kc"], "Kp": r["Kp"]}
    legs_q = [((ty, k, s), oo.quote(es, "2026-11-03", ty, k)) for ty, k, s in oo.v2_legs(st)]
    ef = sum(gcosts.option_fill_fee(s, oo.fill2(q, s), r["qty"], date(2026, 10, 26)).total for (_, _, s), q in legs_q)
    assert r["entry_fees"] == pytest.approx(ef)
    exit_fees = r["fees"] - r["entry_fees"]
    assert 0 < exit_fees <= r["exit_fee_reserve"]
    assert r["reserve"] == pytest.approx((max(r["Wc"], r["Wp"]) - r["credit_pts"]) * r["qty"] + r["entry_fees"]
                                         + r["exit_fee_reserve"])
    assert r["reserve"] <= 5000 and r["units"] == pytest.approx(r["net"] / 5000)
    assert r["net_widened"] < r["net"]


def test_budget_rejects_a_lot_that_risks_too_much(env):
    write_daily(env / "daily", date(2026, 10, 23), rng_pts=450.0)   # ATR 450 -> 450-pt wings: one lot risks > 5k
    write_day(env / "study_chain_20261026.db", "2026-10-26", ["15:20:30"], 22660.0, 160.0)
    t = oo.score_v2(env, env / "daily", date(2026, 10, 26), date(2026, 10, 26))
    r = t.iloc[0]
    assert r["status"].startswith("one lot exceeds") and r["units"] == 0 and r["reserve"] > 5000


def test_vix_gates_and_half_size(env):
    write_daily(env / "daily", date(2026, 10, 23), vix=26.0)
    write_day(env / "study_chain_20261026.db", "2026-10-26", ["15:20:30"], 22660.0, 160.0)
    assert oo.score_v2(env, env / "daily", date(2026, 10, 26), date(2026, 10, 26)).iloc[0]["status"] == "skip: VIX gate"
    write_daily(env / "daily", date(2026, 10, 23), vix=18.5, vix_5_ago=15.0)       # +23% in 5 sessions
    assert oo.score_v2(env, env / "daily", date(2026, 10, 26), date(2026, 10, 26)).iloc[0]["status"] == "skip: VIX gate"
    write_daily(env / "daily", date(2026, 10, 23), vix=22.0)
    r = oo.score_v2(env, env / "daily", date(2026, 10, 26), date(2026, 10, 26)).iloc[0]
    assert r["budget"] == pytest.approx(2500)


def test_event_spanning_the_night_skips():
    assert cal.events_between(date(2026, 12, 3), date(2026, 12, 4)) == [(date(2026, 12, 4), "rbi")]
    assert cal.events_between(date(2026, 12, 4), date(2026, 12, 7)) == []


def test_entry_must_be_in_the_1520_minute(env):
    write_daily(env / "daily", date(2026, 10, 23))
    write_day(env / "study_chain_20261026.db", "2026-10-26", ["15:19:50", "15:21:05"], 22660.0, 160.0)
    r = oo.score_v2(env, env / "daily", date(2026, 10, 26), date(2026, 10, 26)).iloc[0]
    assert r["status"] == "no entry snapshot (15:20-15:21)" and not r["covered"]


def test_missing_chain_file_counts_against_coverage(env):
    write_daily(env / "daily", date(2026, 10, 23))
    write_day(env / "study_chain_20261027.db", "2026-10-27", ["09:20:10"], 22660.0, 140.0)
    t = oo.score_v2(env, env / "daily", date(2026, 10, 26), date(2026, 10, 27))
    assert t.iloc[0]["status"] == "missing data (no chain file)" and not t.iloc[0]["covered"]


def test_option_fill_fees_add_up_to_the_frozen_round_trip():
    when = date(2026, 10, 26)
    a = gcosts.option_fill_fee(1, 80.0, 65, when).total + gcosts.option_fill_fee(-1, 100.0, 65, when).total
    assert a == pytest.approx(costs.option_fees(80.0, 100.0, 65, when).total, abs=1e-9)


def test_v1_path_is_unchanged(env):
    """v1 still pairs consecutive files (its registered behaviour), so its old results reproduce."""
    write_day(env / "study_chain_20261026.db", "2026-10-26", ["15:20:30"], 22660.0, 160.0)
    write_day(env / "study_chain_20261028.db", "2026-10-28", ["09:16:10"], 22660.0, 140.0,
              expiries=("2026-11-03", "2026-11-10"))
    con = sqlite3.connect(env / "nfce.db")
    con.execute("create table range_forecasts (root text, bar_close text, model text, ts text, price real, q10 real,"
                " q50 real, q90 real, realized real)")
    con.commit()
    con.close()
    t = oo.score(env)
    r = t[(t["day"] == "2026-10-26") & (t["kind"] == "IF")].iloc[0]
    assert r["exit_day"] == "2026-10-28"
