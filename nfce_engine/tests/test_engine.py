"""Rule invariants of the engine on simulated NSE-session bars."""
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce.engine import LEGACY_V1, Params, prepare, run  # noqa: E402


def sim_bars(days=40, tf=5, seed=3, trend=0.0):
    rng = np.random.default_rng(seed)
    rows = []
    price = 25000.0
    for d in pd.bdate_range("2026-06-01", periods=days, tz="Asia/Kolkata"):
        t = d + pd.Timedelta(hours=9, minutes=15)
        price += rng.normal(0, 40)
        for _ in range(375 // tf):
            o = price
            ch = rng.normal(trend, 12) * (2 if rng.random() < 0.05 else 1)
            c = o + ch
            h = max(o, c) + abs(rng.normal(0, 5))
            lo = min(o, c) - abs(rng.normal(0, 5))
            v = rng.lognormal(10, 0.5) * (3 if rng.random() < 0.05 else 1)
            rows.append((t, o, h, lo, c, v, 1e7 + rng.normal(0, 1e4)))
            price = c
            t += pd.Timedelta(minutes=tf)
    df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume", "oi"]).set_index("t")
    return df


LOOSE = Params(min_score_in=1, chop_max=100.0, body_atr=0.0, room_r=0.0)   # forces many trades to test the rules


@pytest.fixture(scope="module")
def loose_trades():
    bars = sim_bars()
    pr = prepare(bars, 5, LOOSE)
    return bars, run(pr, LOOSE)


def test_produces_trades(loose_trades):
    _, trades = loose_trades
    assert len(trades) > 50


def test_session_filters(loose_trades):
    _, trades = loose_trades
    for t in trades:
        open_t = t.entry_time - pd.Timedelta(minutes=5)
        m = open_t.hour * 60 + open_t.minute
        mc = t.entry_time.hour * 60 + t.entry_time.minute    # actual entry time = bar close
        assert m >= 9 * 60 + 30, t                       # no entries from bars opening in the first 15 minutes
        assert not (m < 810 and mc > 750), t             # no bar overlapping 12:30-13:30
        assert mc <= 14 * 60 + 45, t                     # last entry (close time, v2)
        if t.expiry:
            assert mc <= 13 * 60 + 30, t                 # expiry-day cut-off (close time, v2)


def test_15m_cutoffs_use_entry_time():
    bars = sim_bars(tf=15, days=30)
    for t in run(prepare(bars, 15, LOOSE), LOOSE):
        mc = t.entry_time.hour * 60 + t.entry_time.minute
        assert mc <= 14 * 60 + 45 and not (t.expiry and mc > 13 * 60 + 30), t


def test_max_trades_per_day_and_same_day_exit(loose_trades):
    _, trades = loose_trades
    per_day = pd.Series([t.entry_time.date() for t in trades]).value_counts()
    assert per_day.max() <= 4
    for t in trades:
        assert t.exit_time.date() == t.entry_time.date()
        assert t.exit_time.hour * 60 + t.exit_time.minute <= 15 * 60 + 15


def test_pnl_matches_exit_type(loose_trades):
    """40/30/30 booking; stops fill at the stop, or at the open if the bar gaps through it."""
    bars, trades = loose_trades
    seen = set()
    for t in trades:
        r = t.pnl / t.R
        seen.add(t.exit)
        s = 1 if t.side == "L" else -1
        bar = bars.loc[t.exit_time - pd.Timedelta(minutes=5)]
        fill = (lambda stop: min(bar.open, stop)) if s == 1 else (lambda stop: max(bar.open, stop))
        if t.exit == "3":
            assert r == pytest.approx(0.4 * 1 + 0.3 * 2 + 0.3 * 3)                      # 1.9R
        elif t.exit == "B":
            be = 0.4 + 0.6 * s * (fill(t.entry) - t.entry) / t.R                        # after T1: stop at entry
            tr = 0.4 + 0.3 * 2 + 0.3 * s * (fill(t.entry + s * t.R) - t.entry) / t.R    # after T2: stop at T1
            # same-bar stop after a target (v2) fills exactly at the moved stop: +0.4R or +1.3R
            assert any(r == pytest.approx(x) for x in (be, tr, 0.4, 1.3)), (r, t)
        elif t.exit == "S":
            assert r == pytest.approx(s * (fill(t.entry - s * t.R) - t.entry) / t.R)
            assert r <= -1 + 1e-9
    assert {"S", "B", "Q"} <= seen


def test_stop_checked_before_target(loose_trades):
    bars, trades = loose_trades
    for t in trades:
        if t.exit != "S":
            continue
        bar = bars.loc[t.exit_time - pd.Timedelta(minutes=5)]
        sl = t.entry - t.R if t.side == "L" else t.entry + t.R
        assert (bar.low <= sl + 1e-6) if t.side == "L" else (bar.high >= sl - 1e-6)


def test_no_overlapping_positions(loose_trades):
    _, trades = loose_trades
    for a, b in zip(trades, trades[1:]):
        assert b.entry_time >= a.exit_time


def test_default_params_are_stricter_than_loose():
    bars = sim_bars()
    pr = prepare(bars, 5, Params())
    assert len(run(pr, Params())) < len(run(pr, LOOSE))


def test_ablation_changes_weights_only():
    p = Params().ablate("volume")
    assert p.weights[0] == 0 and p.weights[1:] == Params().weights[1:]


def test_trace_explains_every_bar_without_changing_results():
    bars = sim_bars(days=20)
    pr = prepare(bars, 5, LOOSE)
    plain = run(pr, LOOSE)
    tr = {i: {} for i in range(len(bars))}
    traced = run(pr, LOOSE, trace=tr)
    assert [(t.entry_time, t.pnl) for t in plain] == [(t.entry_time, t.pnl) for t in traced]
    entries = {t.entry_time - pd.Timedelta(minutes=5) for t in traced}
    for i, info in tr.items():
        assert "blocked" in info
        assert (info["blocked"] == "") == (bars.index[i] in entries)


def test_15m_square_off_uses_bar_close():
    bars = sim_bars(tf=15, days=30)
    trades = run(prepare(bars, 15, LOOSE), LOOSE)
    q = [t for t in trades if t.exit == "Q"]
    assert q and all(t.exit_time.hour * 60 + t.exit_time.minute == 15 * 60 + 15 for t in q)


# ------------------------------------------------------------------ v2 semantics and review findings
def test_no_same_bar_reentry_v2_but_legacy_allows_it(loose_trades):
    _, trades = loose_trades
    assert all(b.entry_time != a.exit_time for a, b in zip(trades, trades[1:]))
    bars = sim_bars()
    legacy = replace(LOOSE, **LEGACY_V1)
    lt = run(prepare(bars, 5, legacy), legacy)
    assert any(b.entry_time == a.exit_time for a, b in zip(lt, lt[1:]))     # v1 behaviour reproducible


def test_cost_gate_skips_trades_whose_risk_is_too_small_for_costs(loose_trades):
    """Research setting min_risk_pct: the stop must be at least this % of price (costs <= ~15% of R at 0.45%)."""
    bars, base = loose_trades
    thr = float(np.median([t.R / t.entry * 100 for t in base]))         # half the fixture's trades are below
    p = replace(LOOSE, min_risk_pct=thr)
    gated = run(prepare(bars, 5, p), p)
    assert gated and all(t.R / t.entry * 100 >= thr - 1e-9 for t in gated)
    assert run(prepare(bars, 5, LOOSE), replace(LOOSE, min_risk_pct=0.0)) == base   # default 0 = off, unchanged


def test_daily_stop_two_losses_or_minus_2R(loose_trades):
    _, trades = loose_trades
    by_day: dict = {}
    for t in trades:
        by_day.setdefault(t.entry_time.date(), []).append(t)
    for day, ts in by_day.items():
        losses, rsum = 0, 0.0
        for t in ts:
            assert losses < 2 and rsum > -2, (day, [x.r for x in ts])     # a new trade only before the daily stop
            losses += t.r < 0
            rsum += t.r


def _fixture_bars(next_bar):
    """Quiet history, one forced long breakout at 10:00 (close 10:05), then `next_bar` (O,H,L,C) and a 15:10 bar."""
    rows, price = [], 100.0
    for d in pd.bdate_range("2026-06-01", periods=3, tz="Asia/Kolkata"):
        t = d + pd.Timedelta(hours=9, minutes=15)
        for _ in range(75):                                  # doji bars: never green, so never a breakout signal
            rows.append((t, price, price + 0.1, price - 0.1, price, 1000.0))
            t += pd.Timedelta(minutes=5)
    day = pd.Timestamp("2026-06-04", tz="Asia/Kolkata")
    t = day + pd.Timedelta(hours=9, minutes=15)
    while t < day + pd.Timedelta(hours=10):
        rows.append((t, price, price + 0.1, price - 0.1, price, 1000.0))
        t += pd.Timedelta(minutes=5)
    rows.append((t, price, price + 3.1, price - 0.1, price + 3.0, 5000.0))           # breakout bar 10:00
    e = price + 3.0
    rows.append((t + pd.Timedelta(minutes=5), *next_bar(e), 1000.0))
    rows.append((day + pd.Timedelta(hours=15, minutes=10), e, e + 0.1, e - 0.1, e, 1000.0))
    return pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume"]).set_index("t"), e


FORCE = replace(LOOSE, max_risk_atr=100.0, min_risk_atr=0.0, daily_max_losses=0, daily_max_loss_r=0.0)


def test_intrabar_stop_after_target_review_fixture():
    """Independent review fixture: entry E, bar O=E+0.5R H=E+1.2R L=E-0.5R C=E-0.1R. The close below the new
    breakeven stop proves it was crossed after T1 -> exit the rest at breakeven: +0.4R (v1 kept it open)."""
    probe, e = _fixture_bars(lambda e: (e, e + 0.05, e - 0.05, e))
    (t0,) = run(prepare(probe, 5, FORCE), FORCE)
    R = t0.R
    bars, e = _fixture_bars(lambda e: (e + 0.5 * R, e + 1.2 * R, e - 0.5 * R, e - 0.1 * R))
    (t,) = run(prepare(bars, 5, FORCE), FORCE)
    assert t.exit == "B" and t.r == pytest.approx(0.4) and t.bars == 1
    legacy = replace(FORCE, intrabar_stop_after_target=False)
    (tl,) = run(prepare(bars, 5, legacy), legacy)
    assert tl.bars > 1                                       # v1: the trade survived the bar that crossed its stop


def test_prefix_causality_of_trades():
    """Trades closed before bar k must be identical whether or not bars after k exist (no look-ahead)."""
    bars = sim_bars(days=12)
    full = run(prepare(bars, 5, LOOSE), LOOSE)
    for k in (300, 451, 600, 777):
        cut = bars.index[k]
        part = run(prepare(bars.iloc[:k], 5, LOOSE), LOOSE)
        a = [(t.entry_time, t.exit_time, round(t.pnl, 9)) for t in full if t.exit_time <= cut]
        b = [(t.entry_time, t.exit_time, round(t.pnl, 9)) for t in part if t.exit_time <= cut]
        assert a == b, k


def test_context_must_match_chart_timeframe():
    bars = sim_bars(days=5)
    hourly = bars.resample("60min", origin="start_day", offset="15min").agg(
        {"open": "first", "close": "last"}).dropna()
    with pytest.raises(ValueError, match="same timeframe"):
        prepare(bars, 5, LOOSE, hw=[hourly])
    prepare(bars, 5, LOOSE, hw=[bars[["open", "close"]]])                           # same timeframe: fine


def test_prepared_fingerprint_guard():
    bars = sim_bars(days=5)
    pr = prepare(bars, 5, LOOSE)
    with pytest.raises(ValueError, match="different preparation"):
        run(pr, replace(LOOSE, use_oi=False))


def test_grade_uses_a_plus_param():
    bars = sim_bars(days=10)
    trades = run(prepare(bars, 5, LOOSE), replace(LOOSE, a_plus=101))
    assert trades and all(t.grade == "A" for t in trades)


def test_previous_day_levels_come_from_daily_bars_when_given():
    """Golden parity: TradingView takes PDH/PDL/PDC from the symbol's daily bars (for futures the close is the
    official settlement), not from the last intraday bar. prepare(daily=...) uses them, as Pine does."""
    b = sim_bars(days=3)
    dates = sorted(set(b.index.normalize()))
    daily = pd.DataFrame({"high": [99999.0, 88888.0, 77777.0], "low": [1.0, 2.0, 3.0], "close": [123.0, 456.0, 789.0]},
                         index=dates)
    pr = prepare(b, 5, Params(), daily=daily)
    day2 = np.asarray(b.index.normalize() == dates[1])
    assert (pr.cols["pdc"][day2] == 123.0).all() and (pr.cols["pdh"][day2] == 99999.0).all()
    assert np.isnan(pr.cols["pdc"][np.asarray(b.index.normalize() == dates[0])]).all()
    pr0 = prepare(b, 5, Params())                                  # without daily bars: built from the intraday bars
    assert pr0.cols["pdc"][day2][0] == b["close"][np.asarray(b.index.normalize() == dates[0])].iloc[-1]


def test_spec_defaults_restored():
    from nfce.engine import strict_phase3
    assert Params().min_score_in == 0 and Params().rvol_thr_in == 0      # presets 65/60 and 1.5/1.3 (spec)
    assert strict_phase3(5) == {"min_score_in": 75, "rvol_thr_in": 1.8}  # Phase-3 option: explicit, labelled


def test_mtm_curve_has_one_point_per_bar(loose_trades):
    bars, trades = loose_trades
    eq: list = []
    run(prepare(bars, 5, LOOSE), LOOSE, mtm=eq)
    assert len(eq) == len(bars)
    assert eq[-1] == pytest.approx(sum(t.pnl for t in trades))


def test_open_position_at_the_end_is_reported_for_live_use(loose_trades):
    bars, trades = loose_trades
    t0 = trades[len(trades) // 2]
    cut = bars[bars.index < t0.entry_time]                 # data ends on the entry bar (its close = entry time)
    out = []
    closed = run(prepare(cut, 5, LOOSE), LOOSE, open_out=out)
    assert t0.entry_time not in {t.entry_time for t in closed}
    assert len(out) == 1 and out[0].entry_time == t0.entry_time and out[0].entry == t0.entry and out[0].exit == ""
