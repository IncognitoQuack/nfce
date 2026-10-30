"""Tests for the study engine (tools/study.py), on small synthetic frames: no real data files are read."""
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce import costs  # noqa: E402
from nfce.research2 import _walk  # noqa: E402
from nfce.stats import holm  # noqa: E402
from tools import study as st  # noqa: E402

TZ = "Asia/Kolkata"


def bars(n_days=30, tf=3, seed=0, start="2023-01-02", vol=True):
    rng = np.random.default_rng(seed)
    out = []
    px = 1000.0
    for d in pd.bdate_range(start, periods=n_days):
        idx = pd.date_range(f"{d.date()} 09:15", periods=375 // tf, freq=f"{tf}min", tz=TZ)
        px *= 1 + rng.normal(0, 0.01)                     # overnight gap
        c = px * np.exp(np.cumsum(rng.normal(0, 0.002, len(idx))))
        o = np.r_[px, c[:-1]]
        h = np.maximum(o, c) * (1 + rng.uniform(0, 0.001, len(idx)))
        l = np.minimum(o, c) * (1 - rng.uniform(0, 0.001, len(idx)))
        v = rng.uniform(1e4, 5e4, len(idx)) if vol else np.zeros(len(idx))
        out.append(pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v, "oi": 0.0}, index=idx))
        px = c[-1]
    return pd.concat(out)


@pytest.fixture(scope="module")
def frm():
    return st.frame(bars(), 3)


# ---------------------------------------------------------------- frame and indicators
def test_frame_daily_values_use_only_earlier_days(frm):
    days = frm["day"].unique()
    d1 = frm[frm["day"] == days[1]]
    d0 = frm[frm["day"] == days[0]]
    assert (d1["prev_high"] == d0["high"].max()).all() and (d1["prev_close"] == d0["close"].iloc[-1]).all()
    assert d0["prev_close"].isna().all()
    assert np.isnan(frm["atr_prev"].iloc[0]) and np.isfinite(frm["atr_prev"].iloc[-1])


def test_frame_drops_short_sessions():
    b = bars(3)
    extra = b.iloc[:10].copy()
    extra.index = pd.date_range("2023-01-07 18:15", periods=10, freq="3min", tz=TZ)  # a Saturday special session
    f = st.frame(pd.concat([b, extra]), 3)
    assert f["day"].nunique() == 3


def test_vwap_resets_each_day(frm):
    first = frm[frm["first"]]
    tp = (first["high"] + first["low"] + first["close"]) / 3
    assert np.allclose(first["vwap"], tp)


@pytest.mark.parametrize("name", list(st.INDICATORS))
def test_no_lookahead(name):
    """Signals up to bar t are identical whether or not the bars after t exist."""
    b = bars(25, seed=3)
    full = st.frame(b, 3)
    cut = len(full) - 140
    part = st.frame(b.iloc[:cut], 3)
    ind = st.INDICATORS[name]
    for p in ind.params:
        lf, sf = ind.fn(full, *p)
        lp, sp = ind.fn(part, *p)
        n = len(part)
        assert np.array_equal(np.asarray(lf)[:n], np.asarray(lp)), (name, p)
        assert np.array_equal(np.asarray(sf)[:n], np.asarray(sp)), (name, p)


def test_rsi_matches_hand_calculation():
    c = pd.Series([10, 11, 12, 11, 13, 12, 14.0])
    r = st.rsi(c, 3)
    d = c.diff().to_numpy()[1:]                             # the first bar has no change
    a = 1 / 3
    u, dw = max(d[0], 0), max(-d[0], 0)
    for x in d[1:]:
        u, dw = (1 - a) * u + a * max(x, 0), (1 - a) * dw + a * max(-x, 0)
    assert r.iloc[-1] == pytest.approx(100 - 100 / (1 + u / dw))


def test_orb_fires_on_the_breakout_bar():
    idx = pd.date_range("2023-01-02 09:15", periods=20, freq="3min", tz=TZ)
    px = np.full(20, 100.0)
    px[8] = 101.0                                           # 09:39 bar closes above the 15-minute range high
    d = pd.DataFrame({"open": 100.0, "high": np.maximum(px, 100.2), "low": 99.8, "close": px, "volume": 1.0,
                      "hm": idx.hour * 60 + idx.minute, "day": idx.normalize().tz_localize(None)}, index=idx)
    lg, sh = st.s_orb(d, 15)
    assert np.flatnonzero(lg).tolist() == [8] and not sh.any()


def test_gap_rules_fire_on_the_first_bar_only(frm):
    lg, sh = st.s_gap_cont(frm, 0.005)
    fl, fs = st.s_gap_fade(frm, 0.005)
    assert frm["first"].to_numpy()[lg | sh].all()
    assert np.array_equal(lg, fs) and np.array_equal(sh, fl)
    gap = (frm["day_open"] / frm["prev_close"] - 1).to_numpy()
    assert (gap[lg] >= 0.005).all() and (gap[sh] <= -0.005).all()


def test_rvol_uses_previous_days_of_the_same_slot():
    b = bars(12, seed=5)
    f = st.frame(b, 3)
    rv = st.rvol(f, 10)
    days = f["day"].unique()
    assert np.isnan(rv[f["day"].to_numpy() < days[10]]).all()
    row = f[(f["day"] == days[10]) & (f["slot"] == 4)]
    prev = f[(f["day"] < days[10]) & (f["slot"] == 4)]["volume"].mean()
    assert rv[f.index.get_loc(row.index[0])] == pytest.approx(row["volume"].iloc[0] / prev)


# ---------------------------------------------------------------- entries, walk, costs
def test_entries_first_signal_per_day_next_bar_same_day_and_cutoff(frm):
    sig = np.zeros(len(frm), bool)
    day = frm["day"].to_numpy()
    days = frm["day"].unique()
    d0 = np.flatnonzero(day == days[0])
    sig[d0[[10, 20]]] = True                                  # two signals day 0: only the first counts
    sig[d0[-1]] = True                                        # last bar of day 1: no next bar that day
    d1 = np.flatnonzero(day == days[1])
    sig[d1[-1]] = True
    sig[d1[100]] = True                                       # 14:15 bar closes 14:18 (inside ALL, not AM)
    e = st.entries(frm, sig, 3, st.WINDOWS["ALL"])
    assert e.tolist() == [d0[10] + 1, d1[100] + 1]
    assert st.entries(frm, sig, 3, st.WINDOWS["AM"]).tolist() == [d0[10] + 1]


@pytest.mark.parametrize("side", [1, -1])
def test_vectorised_walk_matches_research2_walk(frm, side):
    g = st.make_grid(frm, 3)
    rng = np.random.default_rng(1)
    pos = np.sort(rng.choice(np.flatnonzero(frm["hm"].to_numpy() < 14 * 60), 60, replace=False))
    entry = frm["open"].to_numpy()[pos]
    R = entry * rng.uniform(0.001, 0.01, len(pos))
    px, why = st.walk(g, pos, side, entry - side * R, entry + side * R)
    names = {0: "stop", 1: "target", 2: "eod"}
    for i, p in enumerate(pos):
        day = frm["day"].iloc[p]
        d = frm[frm["day"] == day]
        j0 = int(np.flatnonzero(d.index == frm.index[p])[0])
        epx, ewhy, _ = _walk(d, j0, side, entry[i] - side * R[i], entry[i] + side * R[i], 15 * 60 + 12)
        assert px[i] == pytest.approx(epx) and names[int(why[i])] == ewhy


def test_vectorised_costs_equal_the_scalar_cost_model():
    e = np.array([500.0, 1500.0, 3200.0])
    x = np.array([505.0, 1490.0, 3300.0])
    u = np.maximum(1, np.round(st.NOTIONAL / e))
    for side in (1, -1):
        v = st.cost_points(e, x, side, u, st.FRICTION * e)
        for i in range(3):
            assert v[i] == pytest.approx(costs.futures_cost_points(e[i], x[i], side, costs.CURRENT, int(u[i]), 1, 2,
                                                                   st.FRICTION * e[i]))


def test_instrument_accumulates_and_respects_the_stage(frm):
    rules = [r for r in st.grid() if r.univ == "STK" and r.ind == "EMA_X" and r.param == (9, 21)]
    idx = {r: i for i, r in enumerate(rules)}
    days = pd.DatetimeIndex(frm["day"].unique())
    reg = pd.Series(np.where(np.arange(len(days)) % 2, "VIXHI", "VIXLO"), index=days)
    acc = st.instrument(frm, 3, "STK", idx, days, reg)
    half = st.instrument(frm, 3, "STK", idx, days[:10], reg)
    by = {(r.side, r.k, r.window, r.regime): acc[i] for r, i in idx.items()}
    a = by[(1, 1, "ALL", "ALL")]
    assert a[:, 0].sum() > 0 and a[:, 0].max() <= 1             # at most one trade a day
    assert np.allclose(by[(1, 1, "ALL", "VIXHI")] + by[(1, 1, "ALL", "VIXLO")], a)
    assert np.allclose(half[idx[rules[0]]], acc[idx[rules[0]], :10])
    assert (a[:, 6] + a[:, 7] <= a[:, 0]).all()


# ---------------------------------------------------------------- grid and selection
def test_grid_shape():
    g = st.grid()
    ids = [r.id for r in g]
    assert len(ids) == len(set(ids)) and len(g) > 500
    assert not any(r.univ == "IDX" and st.INDICATORS[r.ind].volume for r in g)
    assert all(r.window == "ALL" for r in g if st.INDICATORS[r.ind].open_only)
    fam = {}
    for r in g:
        fam.setdefault(r.family, set()).add(r.param)
    assert all(v == set(st.INDICATORS[f.split("|")[0]].params) for f, v in fam.items())


def _fake_stage(rules, nets, n_per_day=2, ndays=200, seed=0):
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2022-01-03", periods=ndays)
    acc = np.zeros((len(rules), ndays, len(st.FIELDS)))
    for i, mu in enumerate(nets):
        x = rng.normal(mu, 1.0, (ndays, n_per_day))
        acc[i, :, 0] = n_per_day
        acc[i, :, 1] = acc[i, :, 2] = x.sum(1)
        acc[i, :, 3] = (x > 0).sum(1)
        acc[i, :, 4] = np.where(x > 0, x, 0).sum(1)
        acc[i, :, 5] = np.where(x < 0, -x, 0).sum(1)
    return {"rules": rules, "acc": acc, "days": days}


def test_select_picks_the_best_positive_setting_per_family():
    a = st.Rule("EMA_X", (9, 21), 1, 1, "ALL", "ALL", "STK")
    b = st.Rule("EMA_X", (5, 13), 1, 1, "ALL", "ALL", "STK")
    c = st.Rule("EMA_X", (9, 21), -1, 1, "ALL", "ALL", "STK")
    tr = _fake_stage([a, b, c], [0.05, 0.3, -0.3])
    assert st.select(tr) == [b]


# ---------------------------------------------------------------- statistics
def test_holm_adjust_agrees_with_house_holm_and_counts_untested_rules():
    p = np.array([0.001, 0.02, 0.04, 0.3])
    adj = st.holm_adjust(p)
    assert np.allclose(adj, [0.004, 0.06, 0.08, 0.3])
    ref = holm({str(i): v for i, v in enumerate(p)})
    assert [ref[str(i)] for i in range(4)] == list(adj < 0.05)
    assert st.holm_adjust(np.array([0.001]), 100)[0] == pytest.approx(0.1)


def test_spa_noise_is_not_significant_and_a_real_edge_is():
    rng = np.random.default_rng(2)
    noise = rng.normal(0, 1, (250, 40))
    assert st.spa(noise, b=300)["spa_p"] > 0.05
    edge = noise.copy()
    edge[:, 7] += 0.5
    r = st.spa(edge, b=300)
    assert r["spa_p"] < 0.01 and r["rc_p"] < 0.05 and r["best"] == 7


def test_deflated_sharpe_falls_with_more_trials():
    x = np.random.default_rng(4).normal(0.15, 1, 250)
    assert st.deflated_sharpe(x, 0.004, 1000) < st.deflated_sharpe(x, 0.004, 10) < st.deflated_sharpe(x, 0.004, 1)
    assert st.expected_max_sr(0.004, 1) == 0.0


def test_rule_stats_and_block_ci():
    r = st.Rule("ORB", (15,), 1, 1, "ALL", "ALL", "STK")
    s = _fake_stage([r], [0.2])
    t = s["acc"][0]
    x = st.rule_stats(t, s["days"])
    assert x["n"] == 400 and x["net_r"] == pytest.approx(t[:, 1].sum() / 400) and x["p_day"] < 0.05
    lo, hi = st.block_ci(t, b=500)
    assert lo < x["net_r"] < hi
    assert set(x["years"]) == {2022}


def test_validation_needs_holm_over_all_rules_tried():
    r = st.Rule("ORB", (15,), 1, 1, "ALL", "ALL", "STK")
    v = _fake_stage([r], [0.12], n_per_day=4, ndays=245, seed=9)
    loose = st.judge_validation(v, 1, 0.0)[0]
    strict = st.judge_validation(v, 100_000, 0.0)[0]
    assert loose["net_r"] > 0 and loose["holm_all"] < strict["holm_all"]
    assert not strict["pass"]


# ---------------------------------------------------------------- cost check
def test_cost_check_reads_quotes_read_only(tmp_path):
    db = tmp_path / "q.db"
    con = sqlite3.connect(db)
    con.execute("create table q (ts text, key text, symbol text, last real, volume real, oi real, bid real, bid_qty real,"
                " ask real, ask_qty real, depth text, ltt text)")
    rows = [("2026-10-23T09:20:00+05:30", "k", "NSE_FO:ABC26OCTFUT", 0, 0, 0, 999.9, 5000, 1000.1, 5000, "", ""),
            ("2026-10-23T11:00:00+05:30", "k", "NSE_FO:ABC26OCTFUT", 0, 0, 0, 999.8, 100, 1000.2, 100, "", ""),
            ("2026-10-23T11:00:00+05:30", "k", "NSE_FO:NIFTY26OCTFUT", 0, 0, 0, 25000.0, 75, 25000.4, 75, "", ""),
            ("2026-10-23T11:00:00+05:30", "k", "NSE_EQ:ABC", 0, 0, 0, 1.0, 1, 9.0, 1, "", "")]
    con.executemany("insert into q values (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    cc = st.cost_check([db, tmp_path / "missing.db"])
    assert cc["quotes"] == 3 and cc["stocks"] == 1
    assert cc["stock_half_median"] == pytest.approx(0.00015, rel=1e-3)
    assert cc["stock_half_open_median"] == pytest.approx(0.0001, rel=1e-3)
    assert cc["touch_fills_lot"] == 0.5                          # 700 units needed: 5000 shown, then 100
    assert cc["index"]["NIFTY"]["half_median_pts"] == pytest.approx(0.2)
    assert "NSE_EQ" not in str(cc)


# ---------------------------------------------------------------- PBO (CSCV)
def test_pbo_is_about_one_half_for_pure_noise():
    runs = [st.pbo_cscv(np.random.default_rng(s).normal(0, 1, (320, 50)), S=8) for s in range(30)]
    assert runs[0]["splits"] == 70                                 # C(8, 4)
    assert 0.35 < np.mean([r["pbo"] for r in runs]) < 0.6           # one draw varies a lot; the average is ~1/2


def test_pbo_is_near_zero_when_one_trial_is_really_better():
    X = np.random.default_rng(6).normal(0, 1, (320, 50))
    X[:, 3] += 0.6
    r = st.pbo_cscv(X, S=8)
    assert r["pbo"] < 0.05 and r["oos_sr_of_is_best"] > 0.3


def test_pbo_needs_enough_trials_and_days():
    assert np.isnan(st.pbo_cscv(np.ones((100, 1)) + np.arange(100)[:, None], S=8)["pbo"])
    assert np.isnan(st.pbo_cscv(np.random.default_rng(0).normal(size=(10, 5)), S=8)["pbo"])
