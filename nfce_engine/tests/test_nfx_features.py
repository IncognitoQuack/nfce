"""NFCE-X feature factory: no feature may use data after its own bar (the #1 way such systems fool their builders)."""
import numpy as np
import pandas as pd
import pytest

from nfx import features as fx


def _bars(days=14, seed=7):
    rng = np.random.default_rng(seed)
    idx = []
    for d in pd.bdate_range("2025-03-03", periods=days):
        idx += list(pd.date_range(d + pd.Timedelta(hours=9, minutes=15), d + pd.Timedelta(hours=15, minutes=27),
                                  freq="3min", tz="Asia/Kolkata"))
    idx = pd.DatetimeIndex(idx)
    r = rng.normal(0, 0.002, len(idx))
    c = 1000 * np.exp(np.cumsum(r))
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.0005, len(idx)))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.001, len(idx))))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.001, len(idx))))
    v = rng.lognormal(8, 0.6, len(idx))
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v, "oi": 0.0}, index=idx)


def test_every_feature_is_point_in_time():
    d = _bars()
    full = fx.stock_features(d)
    n = len(d)
    for cut in (n // 3 + 7, n // 2 + 3, n - 40, n - 1):          # mid-session and late cut points
        part = fx.stock_features(d.iloc[: cut + 1])
        a, b = full.iloc[cut], part.iloc[cut]
        bad = [k for k in full.columns if not (np.isclose(a[k], b[k], rtol=1e-4, atol=1e-6, equal_nan=True))]
        assert not bad, f"features change when the future is removed (cut {cut}): {bad}"


def test_feature_count_and_families():
    f = fx.stock_features(_bars())
    assert f.shape[1] >= 120
    fams = {fx.family(c) for c in f.columns}
    assert "other" not in fams, [c for c in f.columns if fx.family(c) == "other"]
    assert {"momentum", "volatility", "trend", "oscillator", "volume", "session", "pattern", "structure", "daily"} <= fams
    assert f.dtypes.eq("float32").all()


def test_labels_look_forward_and_stay_inside_the_day():
    d = _bars(days=3)
    y = fx.labels(d)
    day = pd.Series(d.index.date, index=d.index)
    last_bar = day != day.shift(-1)
    assert y["y_20"][d.index[-25:]].isna().all() or y["y_20"].iloc[-1:].isna().all()
    assert (y["y_eod"][last_bar] == 0).all()                       # at the last bar the rest of the day is empty
    assert not set(y.columns) & set(fx.stock_features(d).columns)


def test_executable_labels_enter_after_the_decision_bar():
    d = _bars(days=2)
    y = fx.exec_labels(d)
    i = 10
    assert np.isclose(y["y_x1"].iloc[i], np.log(d["close"].iloc[i + 21] / d["open"].iloc[i + 1]))
    assert np.isclose(y["y_x5"].iloc[i], np.log(d["close"].iloc[i + 25] / d["open"].iloc[i + 5]))
    day = pd.Series(d.index.date, index=d.index)
    assert y["y_x1"][day != day.shift(-21)].isna().all()          # never crosses into the next day


def test_opening_range_features_wait_for_the_range_to_finish():
    f = fx.stock_features(_bars(days=2))
    early = f.between_time("09:15", "09:24")
    assert early["or_pos"].isna().all() and early["or_width"].isna().all()
    assert f.between_time("09:27", "09:27")["or_pos"].notna().all()


def test_cross_section_ranks_and_breadth():
    panel = {s: fx.stock_features(_bars(seed=i)) for i, s in enumerate("ABCD")}
    xs = fx.cross_section(panel)
    t = panel["A"].index[200]
    ranks = sorted(xs[s].loc[t, "xs_rank_mom_since_open"] for s in "ABCD")
    assert ranks == pytest.approx([0.25, 0.5, 0.75, 1.0])
    assert 0 <= xs["A"].loc[t, "breadth"] <= 1


def test_vix_and_events_use_only_known_information():
    d = _bars(days=8)
    vix = d[["open", "high", "low", "close"]] / 60
    v = fx.vix_features(vix, d.index)
    first_day = v.index.date == v.index[0].date()
    assert v.loc[first_day, "vix_chg_day"].isna().all()           # no previous close yet
    cal = pd.DataFrame({"symbol": ["X"], "date": [str(d.index[-1].date())], "results": [1], "purpose": [""]})
    e = fx.event_features("X", d.index, cal)
    assert e["ev_results_today"].iloc[-1] == 1 and e["ev_results_today"].iloc[0] == 0
    assert e["ev_days_to_results"].iloc[0] > 0
