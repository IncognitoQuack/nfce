"""Tests for the overnight option-selling scorer (tools/overnight_options.py) on synthetic chain databases."""
import math
import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce import costs  # noqa: E402
from tools import overnight_options as oo  # noqa: E402

COLS = ("ts text, underlying text, expiry text, spot real, strike real, typ text, key text, ltp real, bid real, "
        "ask real, bid_qty real, ask_qty real, volume real, oi real, iv real, delta real, gamma real, theta real, vega real")


def premium(spot, k, typ, scale):
    intrinsic = max(0.0, spot - k) if typ == "CE" else max(0.0, k - spot)
    return intrinsic + scale * math.exp(-((k - spot) / 400) ** 2)


def write_day(path, day, times, spot, scale, iv, expiries=("2026-10-27", "2026-11-03")):
    con = sqlite3.connect(path)
    con.execute(f"create table chain ({COLS})")
    rows = []
    for t in times:
        for e in expiries:
            for k in np.arange(23000, 26001, 50.0):
                for typ in ("CE", "PE"):
                    p = premium(spot, k, typ, scale)
                    rows.append((f"{day}T{t}", "NIFTY", e, spot, k, typ, "", p, p - 0.5, p + 0.5, 100, 100, 0, 0, iv,
                                 0, 0, 0, 0))
    con.executemany(f"insert into chain values ({','.join('?' * 19)})", rows)
    con.commit()
    con.close()


def forecasts_db(path, days_vals):
    con = sqlite3.connect(path)
    con.execute("create table range_forecasts (root text, bar_close text, model text, ts text, price real, q10 real,"
                " q50 real, q90 real, realized real)")
    for d, v in days_vals:
        con.execute("insert into range_forecasts values ('NIFTY', ?, 'M1', '', 0, 0, ?, 0, null)", (f"{d}T14:15:00+05:30", math.log(v)))
    con.commit()
    con.close()


def test_iron_fly_legs_and_wing_width():
    lg = oo.legs(25000.0, 25000.0, 16.0, "IF")
    sd = 25000 * 0.16 * math.sqrt(1 / 252)                     # ~252 points
    w = 50 * math.ceil(2 * sd / 50)
    assert lg == [("CE", 25000, -1), ("PE", 25000, -1), ("CE", 25000 + w, 1), ("PE", 25000 - w, 1)]
    ic = oo.legs(25000.0, 25000.0, 16.0, "IC")
    assert ic[0] == ("CE", 25000 + 250, -1) and ic[3] == ("PE", 25000 - 250 - w, 1)


def test_expiry_is_never_the_next_session():
    assert oo.pick_expiry(["2026-10-27", "2026-11-03"], date(2026, 10, 27)) == "2026-11-03"
    assert oo.pick_expiry(["2026-10-27", "2026-11-03"], date(2026, 10, 26)) == "2026-10-27"
    assert oo.pick_expiry(["2026-10-27"], date(2026, 10, 27)) is None


def test_fills_pay_the_spread_both_ways():
    q = pd.Series({"bid": 99.0, "ask": 101.0})
    assert oo.fill(q, -1, True) == 99.0 and oo.fill(q, 1, True) == 101.0
    assert oo.fill(q, -1, False) == 101.0 and oo.fill(q, 1, False) == 99.0
    assert oo.fill(q, -1, True, 1.5) == 98.5
    assert oo.fill(pd.Series({"bid": 0.0, "ask": 5.0}), 1, True) is None


def test_quiet_night_with_decay_is_a_profit_and_costs_are_counted(tmp_path):
    write_day(tmp_path / "study_chain_20261026.db", "2026-10-26", ["11:00:00", "15:20:30"], 25000.0, 200.0, 15.0)
    write_day(tmp_path / "study_chain_20261027.db", "2026-10-27", ["09:15:30", "09:16:10"], 25000.0, 170.0, 15.0)
    forecasts_db(tmp_path / "nfce.db", [("2026-10-26", 0.004)])
    t = oo.score(tmp_path)
    r = t[(t["kind"] == "IF") & (t["day"] == "2026-10-26")].iloc[0]
    assert r["status"] == "ok" and r["expiry"] == "2026-11-03" and r["skip"] == ""
    assert r["gross"] > 0 and 0 < r["fees"] < r["gross"] and r["net"] == pytest.approx(r["gross"] - r["fees"])
    assert r["net_widened"] < r["net"]
    assert pd.isna(r["f2"])                                      # fewer than 5 earlier sessions: F2 not active
    last = t[t["day"] == "2026-10-27"].iloc[0]
    assert last["status"] == "no entry snapshot"                  # the synthetic exit day has no 15:20 snapshot


def test_a_big_gap_loses_at_most_the_wing(tmp_path):
    write_day(tmp_path / "study_chain_20261026.db", "2026-10-26", ["15:20:30"], 25000.0, 200.0, 15.0)
    write_day(tmp_path / "study_chain_20261027.db", "2026-10-27", ["09:16:10"], 26000.0, 200.0, 15.0)
    forecasts_db(tmp_path / "nfce.db", [])
    r = oo.score(tmp_path)
    r = r[(r["kind"] == "IF") & (r["status"] == "ok")].iloc[0]
    assert r["net"] < 0 and -r["net"] <= r["R"] + r["fees"] + 1e-6


def test_f1_skips_when_iv_rose_since_1100(tmp_path):
    con_path = tmp_path / "study_chain_20261026.db"
    write_day(con_path, "2026-10-26", ["11:00:00"], 25000.0, 200.0, 14.0)
    con = sqlite3.connect(con_path)
    rows = con.execute("select * from chain").fetchall()
    con.executemany(f"insert into chain values ({','.join('?' * 19)})",
                    [(r[0].replace("11:00:00", "15:20:30"),) + r[1:14] + (15.0,) + r[15:] for r in rows])
    con.commit()
    con.close()
    write_day(tmp_path / "study_chain_20261027.db", "2026-10-27", ["09:16:10"], 25000.0, 180.0, 15.0)
    forecasts_db(tmp_path / "nfce.db", [])
    t = oo.score(tmp_path)
    r = t[(t["kind"] == "IF") & (t["status"] == "ok")].iloc[0]
    assert r["skip"] == "F1 IV rising" and r["iv_ratio"] == pytest.approx(15 / 14)


def test_f2_uses_only_earlier_sessions():
    fc = pd.Series([0.004, 0.004, 0.005, 0.004, 0.006, 0.009], index=[f"2026-10-{d}" for d in (19, 20, 21, 22, 23, 26)])
    assert oo.f2_large_move(fc, "2026-10-23")[0] is None        # only 4 earlier sessions
    assert oo.f2_large_move(fc, "2026-10-26")[0] is True
    assert oo.f2_large_move(fc, "2026-10-30")[0] is None


def test_judge_needs_40_sessions_and_the_widened_mean():
    rng = np.random.default_rng(0)
    t = pd.DataFrame({"kind": "IF", "status": "ok", "skip": "", "net": rng.normal(500, 300, 45), "net_r": 0.1})
    t["net_widened"] = t["net"] - 100
    assert oo.judge(t, "IF")["pass"]
    assert not oo.judge(t.head(30), "IF")["pass"]
    t["net_widened"] = t["net"] - 1000
    assert not oo.judge(t, "IF")["pass"]


def test_option_fees_short_leg_pays_stt_on_the_sale():
    f = costs.option_fees(80.0, 100.0, 65, costs.CURRENT)            # bought back at 80, sold at 100
    assert f.stt == pytest.approx(0.0015 * 100 * 65)


def test_entry_day_without_a_recorded_next_session_is_unresolved(tmp_path):
    write_day(tmp_path / "study_chain_20261026.db", "2026-10-26", ["15:20:30"], 25000.0, 200.0, 15.0)
    forecasts_db(tmp_path / "nfce.db", [])
    t = oo.score(tmp_path)
    assert t["status"].tolist() == ["unresolved (no next session yet)"]
