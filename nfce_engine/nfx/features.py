"""NFCE-X phase 1: point-in-time features for one stock's 3-minute bars, plus cross-sectional and context features.

Every value at bar t uses only bars that had CLOSED by t (the bar's own close included), so a decision taken at bar t's
close can use it. `tests/test_nfx_features.py` proves this by recomputing on data truncated at t and comparing.

Families (FAMILIES maps each column to one): momentum, volatility, trend, oscillator, volume, session, pattern,
structure, daily, cross (cross-sectional), context (VIX, breadth), event (results calendar). Labels (future returns)
live in `labels()` and are never features.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from nfce import ta

BARS_HOUR = 20                   # 3-minute bars in an hour
OPEN_RANGE_END = "09:30"         # opening range = bars starting 09:15..09:27
RVOL_DAYS = 10


def _s(x, idx) -> pd.Series:
    return pd.Series(np.asarray(x, dtype=float), index=idx)


def _safe_div(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = a / b
    out[~np.isfinite(out)] = np.nan
    return out


def _rsi(c: pd.Series, n: int) -> pd.Series:
    d = c.diff()
    up, dn = ta.rma(d.clip(lower=0).to_numpy(), n), ta.rma((-d).clip(lower=0).to_numpy(), n)
    return _s(100 - 100 / (1 + _safe_div(up, dn)), c.index)


def _stoch(h, l, c, n: int, k: int):
    lo, hi = l.rolling(n).min(), h.rolling(n).max()
    kk = 100 * (c - lo) / (hi - lo).replace(0, np.nan)
    return kk, kk.rolling(k).mean()


def stock_features(d: pd.DataFrame) -> pd.DataFrame:
    """d: one stock's 3-minute bars (open, high, low, close, volume), tz-aware index, sorted. Returns one row per bar."""
    d = d[~d.index.duplicated(keep="first")].sort_index()
    idx = d.index
    o, h, l, c, v = (d[k].astype(float) for k in ("open", "high", "low", "close", "volume"))
    day = pd.Series(idx.date, index=idx)
    hhmm = pd.Series(idx.strftime("%H:%M"), index=idx)
    f: dict[str, pd.Series] = {}
    lc = np.log(c)

    # ---- momentum: log returns over bar horizons, and since the open ----
    for n, name in ((1, "3m"), (5, "15m"), (10, "30m"), (20, "1h"), (40, "2h"), (125, "1d"), (250, "2d"), (625, "5d")):
        f[f"mom_{name}"] = lc - lc.shift(n)
    day_open = o.groupby(day).transform("first")
    f["mom_since_open"] = lc - np.log(day_open)
    f["roc_10"] = 100 * (c / c.shift(10) - 1)

    # ---- volatility ----
    atr14 = _s(ta.atr(h.to_numpy(), l.to_numpy(), c.to_numpy(), 14), idx)
    f["natr_14"] = atr14 / c
    f["natr_50"] = _s(ta.atr(h.to_numpy(), l.to_numpy(), c.to_numpy(), 50), idx) / c
    f["atr_ratio_5_50"] = _s(ta.atr(h.to_numpy(), l.to_numpy(), c.to_numpy(), 5), idx) / (f["natr_50"] * c)
    r1 = lc.diff()
    f["rv_20"] = r1.rolling(20).std()
    f["rv_100"] = r1.rolling(100).std()
    f["rv_ratio"] = f["rv_20"] / f["rv_100"]
    f["parkinson_20"] = np.sqrt((np.log(h / l) ** 2).rolling(20).mean() / (4 * np.log(2)))
    ma20, sd20 = c.rolling(20).mean(), c.rolling(20).std()
    f["bb_width"] = 4 * sd20 / ma20
    f["bb_pos"] = (c - (ma20 - 2 * sd20)) / (4 * sd20).replace(0, np.nan)
    ema20 = _s(ta.ema(c.to_numpy(), 20), idx)
    f["kc_pos"] = (c - ema20) / (2 * atr14).replace(0, np.nan)
    f["kc_width"] = 4 * atr14 / ema20
    f["squeeze"] = (f["bb_width"] < f["kc_width"]).astype(float)

    # ---- trend ----
    emas = {n: _s(ta.ema(c.to_numpy(), n), idx) for n in (9, 21, 50, 200)}
    for n, e in emas.items():
        f[f"ema{n}_dist"] = (c - e) / atr14
        f[f"ema{n}_slope"] = (e - e.shift(5)) / atr14
    f["ema_stack"] = ((emas[9] > emas[21]).astype(float) + (emas[21] > emas[50]).astype(float)
                      + (emas[50] > emas[200]).astype(float)) - 1.5
    e12, e26 = _s(ta.ema(c.to_numpy(), 12), idx), _s(ta.ema(c.to_numpy(), 26), idx)
    macd = e12 - e26
    sig = _s(ta.ema(macd.fillna(0).to_numpy(), 9), idx)
    f["macd"], f["macd_sig"], f["macd_hist"] = macd / atr14, sig / atr14, (macd - sig) / atr14
    dip, dim, adx = ta.dmi(h.to_numpy(), l.to_numpy(), c.to_numpy(), 14, 14)
    f["adx"], f["di_diff"] = _s(adx, idx), _s(dip, idx) - _s(dim, idx)
    for n in (25,):
        hi_i = h.rolling(n + 1).apply(np.argmax, raw=True)
        lo_i = l.rolling(n + 1).apply(np.argmin, raw=True)
        f["aroon_up"], f["aroon_dn"] = 100 * hi_i / n, 100 * lo_i / n
        f["aroon_osc"] = f["aroon_up"] - f["aroon_dn"]
    st, st_dir = ta.supertrend(h.to_numpy(), l.to_numpy(), c.to_numpy(), 3.0, 10)
    f["supertrend_dir"] = -_s(st_dir, idx)               # +1 up, -1 down (ta returns Pine's sign)
    f["supertrend_dist"] = (c - _s(st, idx)) / atr14
    tenkan = (h.rolling(9).max() + l.rolling(9).min()) / 2
    kijun = (h.rolling(26).max() + l.rolling(26).min()) / 2
    span_a, span_b = ((tenkan + kijun) / 2).shift(26), ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)
    f["ichi_tk"] = (tenkan - kijun) / atr14
    f["ichi_cloud"] = (c - pd.concat([span_a, span_b], axis=1).max(axis=1)) / atr14
    f["linreg_slope_20"] = (_s(ta.linreg(c.to_numpy(), 20, 0), idx) - _s(ta.linreg(c.to_numpy(), 20, 1), idx)) / atr14
    tr = _s(ta.true_range(h.to_numpy(), l.to_numpy(), c.to_numpy(), True), idx)
    rng14 = h.rolling(14).max() - l.rolling(14).min()
    f["chop_14"] = 100 * np.log10(tr.rolling(14).sum() / rng14.replace(0, np.nan)) / np.log10(14)
    f["eff_ratio_20"] = (c - c.shift(20)).abs() / c.diff().abs().rolling(20).sum().replace(0, np.nan)

    # ---- oscillators ----
    for n in (7, 14, 21):
        f[f"rsi_{n}"] = _rsi(c, n)
    k, dd = _stoch(h, l, c, 14, 3)
    f["stoch_k"], f["stoch_d"] = k, dd
    f["williams_r"] = -100 * (h.rolling(14).max() - c) / (h.rolling(14).max() - l.rolling(14).min()).replace(0, np.nan)
    tp = (h + l + c) / 3
    mad = tp.rolling(20).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    f["cci_20"] = (tp - tp.rolling(20).mean()) / (0.015 * mad.replace(0, np.nan))
    mf = tp * v
    pos = mf.where(tp > tp.shift(1), 0).rolling(14).sum()
    neg = mf.where(tp < tp.shift(1), 0).rolling(14).sum()
    f["mfi_14"] = 100 - 100 / (1 + pos / neg.replace(0, np.nan))
    up, dn = c.diff().clip(lower=0), (-c.diff()).clip(lower=0)
    f["cmo_14"] = 100 * (up.rolling(14).sum() - dn.rolling(14).sum()) / (up.rolling(14).sum() + dn.rolling(14).sum()).replace(0, np.nan)
    bp = c - pd.concat([l, c.shift(1)], axis=1).min(axis=1)
    trr = pd.concat([h, c.shift(1)], axis=1).max(axis=1) - pd.concat([l, c.shift(1)], axis=1).min(axis=1)
    f["ult_osc"] = 100 * (4 * bp.rolling(7).sum() / trr.rolling(7).sum() + 2 * bp.rolling(14).sum() / trr.rolling(14).sum()
                          + bp.rolling(28).sum() / trr.rolling(28).sum()) / 7
    for n in (20, 50):
        f[f"zscore_{n}"] = (c - c.rolling(n).mean()) / c.rolling(n).std()

    # ---- volume ----
    slot_vol = v.groupby([day, hhmm]).sum()
    piv = slot_vol.unstack()                                           # rows = days, cols = time slots
    usual = piv.shift(1).rolling(RVOL_DAYS, min_periods=5).mean()      # previous days only
    usual_long = usual.stack().reindex(pd.MultiIndex.from_arrays([day, hhmm])).to_numpy()
    f["rvol_slot"] = _s(_safe_div(v.to_numpy(), usual_long), idx)
    cumv = v.groupby(day).cumsum()
    cum_usual = piv.shift(1).rolling(RVOL_DAYS, min_periods=5).mean().cumsum(axis=1)
    cu = cum_usual.stack().reindex(pd.MultiIndex.from_arrays([day, hhmm])).to_numpy()
    f["rvol_cum"] = _s(_safe_div(cumv.to_numpy(), cu), idx)
    f["vol_z_20"] = (v - v.rolling(20).mean()) / v.rolling(20).std()
    obv = (np.sign(c.diff()).fillna(0) * v).cumsum()
    f["obv_slope_20"] = (obv - obv.shift(20)) / v.rolling(20).sum().replace(0, np.nan)
    mfm = ((c - l) - (h - c)) / (h - l).replace(0, np.nan)
    f["cmf_20"] = (mfm * v).rolling(20).sum() / v.rolling(20).sum().replace(0, np.nan)
    f["force_13"] = _s(ta.ema((c.diff() * v).fillna(0).to_numpy(), 13), idx) / (atr14 * v.rolling(20).mean())
    pv = (tp * v).groupby(day).cumsum()
    vwap = pv / cumv.replace(0, np.nan)
    vw_var = ((tp - vwap) ** 2 * v).groupby(day).cumsum() / cumv.replace(0, np.nan)
    f["vwap_dist"] = (c - vwap) / atr14
    f["vwap_z"] = (c - vwap) / np.sqrt(vw_var).replace(0, np.nan)

    # ---- session structure ----
    mins = pd.Series((idx.hour * 60 + idx.minute - 555).to_numpy(), index=idx)
    f["mins_since_open"] = mins.astype(float)
    in_or = hhmm < OPEN_RANGE_END
    or_hi = h.where(in_or).groupby(day).transform("max")
    or_lo = l.where(in_or).groupby(day).transform("min")
    or_done = hhmm >= "09:27"                                          # the 09:27 bar closes at 09:30
    f["or_pos"] = ((c - or_lo) / (or_hi - or_lo).replace(0, np.nan)).where(or_done)
    f["or_width"] = ((or_hi - or_lo) / atr14).where(or_done)
    dhi, dlo = h.groupby(day).cummax(), l.groupby(day).cummin()
    f["day_range_pos"] = (c - dlo) / (dhi - dlo).replace(0, np.nan)
    f["dist_day_high"], f["dist_day_low"] = (dhi - c) / atr14, (c - dlo) / atr14
    dclose = c.groupby(day).last()
    dhigh, dlow = h.groupby(day).max(), l.groupby(day).min()
    prev = pd.DataFrame({"pc": dclose.shift(1), "ph": dhigh.shift(1), "pl": dlow.shift(1)})
    pr = prev.reindex(day.to_numpy()).set_index(idx)
    f["gap"] = np.log(day_open / pr["pc"])
    f["prev_close_dist"] = (c - pr["pc"]) / atr14
    f["prev_high_dist"], f["prev_low_dist"] = (c - pr["ph"]) / atr14, (c - pr["pl"]) / atr14
    for n in (10, 20, 50):
        f[f"donchian_pos_{n}"] = (c - l.rolling(n).min()) / (h.rolling(n).max() - l.rolling(n).min()).replace(0, np.nan)
        f[f"breakout_up_{n}"] = (c > h.shift(1).rolling(n).max()).astype(float)
        f[f"breakout_dn_{n}"] = (c < l.shift(1).rolling(n).min()).astype(float)
    f["dow"] = pd.Series(idx.dayofweek.astype(float), index=idx)

    # ---- candlestick patterns ----
    body, rng = (c - o), (h - l).replace(0, np.nan)
    upw, low_w = h - pd.concat([o, c], axis=1).max(axis=1), pd.concat([o, c], axis=1).min(axis=1) - l
    pb, po, pc_, ph, pl = body.shift(1), o.shift(1), c.shift(1), h.shift(1), l.shift(1)
    f["body_frac"], f["upper_wick"], f["lower_wick"] = body / rng, upw / rng, low_w / rng
    f["body_atr"] = body / atr14
    small = body.abs() <= 0.1 * rng
    f["pat_doji"] = small.astype(float)
    f["pat_hammer"] = ((low_w >= 2 * body.abs()) & (upw <= 0.3 * body.abs().clip(lower=1e-9)) & (c < c.shift(5))).astype(float)
    f["pat_inv_hammer"] = ((upw >= 2 * body.abs()) & (low_w <= 0.3 * body.abs().clip(lower=1e-9)) & (c < c.shift(5))).astype(float)
    f["pat_shooting_star"] = ((upw >= 2 * body.abs()) & (low_w <= 0.3 * body.abs().clip(lower=1e-9)) & (c > c.shift(5))).astype(float)
    f["pat_hanging_man"] = ((low_w >= 2 * body.abs()) & (upw <= 0.3 * body.abs().clip(lower=1e-9)) & (c > c.shift(5))).astype(float)
    f["pat_bull_engulf"] = ((pb < 0) & (body > 0) & (o <= pc_) & (c >= po)).astype(float)
    f["pat_bear_engulf"] = ((pb > 0) & (body < 0) & (o >= pc_) & (c <= po)).astype(float)
    f["pat_bull_harami"] = ((pb < 0) & (body > 0) & (o > pc_) & (c < po)).astype(float)
    f["pat_bear_harami"] = ((pb > 0) & (body < 0) & (o < pc_) & (c > po)).astype(float)
    f["pat_piercing"] = ((pb < 0) & (body > 0) & (o < pl) & (c > (po + pc_) / 2) & (c < po)).astype(float)
    f["pat_dark_cloud"] = ((pb > 0) & (body < 0) & (o > ph) & (c < (po + pc_) / 2) & (c > po)).astype(float)
    b2, c2, o2 = body.shift(2), c.shift(2), o.shift(2)
    f["pat_morning_star"] = ((b2 < 0) & (pb.abs() < 0.3 * b2.abs()) & (body > 0) & (c > (o2 + c2) / 2)).astype(float)
    f["pat_evening_star"] = ((b2 > 0) & (pb.abs() < 0.3 * b2.abs()) & (body < 0) & (c < (o2 + c2) / 2)).astype(float)
    ups = (body > 0) & (c > c.shift(1))
    dns = (body < 0) & (c < c.shift(1))
    f["pat_three_soldiers"] = (ups & ups.shift(1, fill_value=False) & ups.shift(2, fill_value=False)).astype(float)
    f["pat_three_crows"] = (dns & dns.shift(1, fill_value=False) & dns.shift(2, fill_value=False)).astype(float)
    f["pat_marubozu"] = (np.sign(body) * ((upw + low_w) <= 0.05 * rng)).astype(float)
    f["pat_spinning_top"] = ((body.abs() <= 0.3 * rng) & (upw >= 0.3 * rng) & (low_w >= 0.3 * rng)).astype(float)
    f["pat_inside_bar"] = ((h <= ph) & (l >= pl)).astype(float)
    f["pat_outside_bar"] = ((h > ph) & (l < pl)).astype(float)
    f["pat_tweezer_top"] = (((h - ph).abs() <= 0.05 * atr14) & (pb > 0) & (body < 0)).astype(float)
    f["pat_tweezer_bottom"] = (((l - pl).abs() <= 0.05 * atr14) & (pb < 0) & (body > 0)).astype(float)
    nr = (h - l)
    f["pat_nr7"] = (nr <= nr.rolling(7).min()).astype(float)

    # ---- structure ----
    f["higher_highs_10"] = (h > h.shift(1)).astype(float).rolling(10).sum()
    f["higher_lows_10"] = (l > l.shift(1)).astype(float).rolling(10).sum()
    sgn = np.sign(c.diff()).fillna(0)
    grp = (sgn != sgn.shift(1)).cumsum()
    f["streak"] = sgn * sgn.groupby(grp).cumcount().add(1)
    f["inside_count_5"] = f["pat_inside_bar"].rolling(5).sum()

    # ---- daily (previous completed days only) ----
    dlc = np.log(dclose)
    dret = pd.DataFrame({"d_ret_1": dlc.diff(1), "d_ret_5": dlc.diff(5), "d_ret_20": dlc.diff(20),
                         "d_vol_20": dlc.diff().rolling(20).std()}).shift(1)   # as of the previous close
    dr = dret.reindex(day.to_numpy()).set_index(idx)
    for k2 in dret.columns:
        f[k2] = dr[k2]

    out = pd.DataFrame(f, index=idx)
    out = out.replace([np.inf, -np.inf], np.nan).astype("float32")
    return out


def cross_section(panel: dict[str, pd.DataFrame], cols=("mom_since_open", "mom_1h", "mom_1d", "rvol_cum", "natr_14",
                                                      "d_ret_5")) -> dict[str, pd.DataFrame]:
    """Per-timestamp percentile ranks across stocks, plus breadth and equal-weight market moves (same for all)."""
    out = {s: pd.DataFrame(index=df.index) for s, df in panel.items()}
    ctx = {}
    for col in cols:
        wide = pd.DataFrame({s: df[col] for s, df in panel.items()})
        rk = wide.rank(axis=1, pct=True)
        for s in panel:
            out[s][f"xs_rank_{col}"] = rk[s].astype("float32")
        if col in ("mom_since_open", "mom_1h", "mom_1d"):
            ctx[f"mkt_{col}"] = wide.mean(axis=1)
            for s in panel:
                out[s][f"rel_{col}"] = (wide[s] - wide.mean(axis=1)).astype("float32")
        if col == "mom_since_open":
            ctx["breadth"] = (wide > 0).sum(axis=1) / wide.notna().sum(axis=1)
    ctx = pd.DataFrame(ctx).astype("float32")
    for s in panel:
        out[s] = out[s].join(ctx.reindex(out[s].index))
    return out


def vix_features(vix: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """India VIX level and changes, as of each bar (3-minute VIX bars; previous closes for the daily changes)."""
    vix = vix[~vix.index.duplicated(keep="first")].sort_index()
    vc = vix["close"].astype(float)
    vday = pd.Series(vix.index.date, index=vix.index)
    dclose = vc.groupby(vday).last()
    prev1, prev5 = dclose.shift(1), dclose.shift(5)
    f = pd.DataFrame({"vix": vc,
                      "vix_chg_day": np.log(vc / prev1.reindex(vday.to_numpy()).to_numpy()),
                      "vix_chg_5d": np.log(prev1 / prev5).reindex(vday.to_numpy()).to_numpy(),
                      "vix_chg_1h": np.log(vc / vc.shift(BARS_HOUR))}, index=vix.index)
    return f.reindex(index, method="ffill").astype("float32")


def event_features(symbol: str, index: pd.DatetimeIndex, calendar: pd.DataFrame) -> pd.DataFrame:
    """Results-calendar flags: board meetings are announced in advance, so knowing the date ahead is not leakage."""
    cal = calendar[(calendar["symbol"] == symbol) & (calendar["results"] == 1)]
    dates = np.array(sorted(pd.to_datetime(cal["date"]).dt.date.unique()))
    days = np.array(index.date)
    out = pd.DataFrame(index=index)
    if len(dates) == 0:
        out["ev_results_today"] = np.float32(0)
        out["ev_days_to_results"] = np.float32(np.nan)
        out["ev_days_since_results"] = np.float32(np.nan)
        return out
    pos = np.searchsorted(dates, days)
    nxt = np.where(pos < len(dates), pos, len(dates) - 1)
    prv = np.clip(np.searchsorted(dates, days, side="right") - 1, 0, None)
    to_n = np.array([(dates[j] - d).days if dates[j] >= d else np.nan for j, d in zip(nxt, days)], dtype=float)
    since = np.array([(d - dates[j]).days if dates[j] <= d else np.nan for j, d in zip(prv, days)], dtype=float)
    out["ev_results_today"] = (to_n == 0).astype("float32")
    out["ev_days_to_results"] = to_n.astype("float32")
    out["ev_days_since_results"] = since.astype("float32")
    return out


def labels(d: pd.DataFrame, horizons=(20, "eod")) -> pd.DataFrame:
    """FUTURE returns, for training targets only. Never join these into features."""
    c = d["close"].astype(float)
    day = pd.Series(d.index.date, index=d.index)
    out = {}
    for hz in horizons:
        if hz == "eod":
            out["y_eod"] = np.log(c.groupby(day).transform("last") / c)
        else:
            out[f"y_{hz}"] = np.log(c.shift(-hz) / c).where(day.shift(-hz) == day)
    return pd.DataFrame(out).astype("float32")


def exec_labels(d: pd.DataFrame, delays=(1, 2, 5), hold: int = 20) -> pd.DataFrame:
    """FUTURE returns with an executable entry (nfx_model_amendment_1.md): buy at the OPEN of bar t+k, sell at the
    close of bar t+k+hold, same day only. Avoids the bid-ask bounce in the decision bar's own last-traded close."""
    d = d[~d.index.duplicated(keep="first")].sort_index()
    o, c = d["open"].astype(float), d["close"].astype(float)
    day = pd.Series(d.index.date, index=d.index)
    out = {}
    for k in delays:
        end = k + hold
        out[f"y_x{k}"] = np.log(c.shift(-end) / o.shift(-k)).where(day.shift(-end) == day)
    return pd.DataFrame(out).astype("float32")


def family(col: str) -> str:
    for pre, fam in (("mom_", "momentum"), ("roc_", "momentum"), ("natr", "volatility"), ("atr_", "volatility"),
                     ("rv_", "volatility"), ("parkinson", "volatility"), ("bb_", "volatility"), ("kc_", "volatility"),
                     ("squeeze", "volatility"), ("ema", "trend"), ("macd", "trend"), ("adx", "trend"), ("di_", "trend"),
                     ("aroon", "trend"), ("supertrend", "trend"), ("ichi", "trend"), ("linreg", "trend"),
                     ("chop", "trend"), ("eff_", "trend"), ("rsi", "oscillator"), ("stoch", "oscillator"),
                     ("williams", "oscillator"), ("cci", "oscillator"), ("mfi", "oscillator"), ("cmo", "oscillator"),
                     ("ult_", "oscillator"), ("zscore", "oscillator"), ("rvol", "volume"), ("vol_z", "volume"),
                     ("obv", "volume"), ("cmf", "volume"), ("force", "volume"), ("vwap", "volume"),
                     ("mins_", "session"), ("or_", "session"), ("day_", "session"), ("dist_day", "session"),
                     ("gap", "session"), ("prev_", "session"), ("donchian", "session"), ("breakout", "session"),
                     ("dow", "session"), ("pat_", "pattern"), ("body_", "pattern"), ("upper_", "pattern"),
                     ("lower_", "pattern"), ("higher_", "structure"), ("streak", "structure"), ("inside_", "structure"),
                     ("d_", "daily"), ("xs_", "cross"), ("rel_", "cross"), ("mkt_", "context"), ("breadth", "context"),
                     ("vix", "context"), ("ev_", "event")):
        if col.startswith(pre):
            return fam
    return "other"
