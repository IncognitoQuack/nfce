"""R4: live next-60-minute range forecast and range-calibrated targets (evidence/r4_protocol.md, registered in REGISTRY.md).

models/range_r4.pkl = M1 (adopted 20 Oct 2026 by the pre-declared rule of evidence/range_benchmark_protocol.md): gradient-
boosted quantile regression fitted on 2022-2025 (953k samples), conformalised on Jan-Jul 2026 (meta["conformal_shift"]).
On FRESH Aug-Oct 2026 data: pinball 0.0978, 10-90% band held 77% of moves (NIFTY 75%, BANKNIFTY 80%), R² 0.31 - level
with a simple linear HAR+VIX quantile model (models/range_har.json, also forecast live and scored daily, REGISTRY R6).
The features here reproduce nfce_engine/tools/ml_study.py:symbol_frame exactly (tests/test_range_model.py checks parity).

Live data: about a year of the index's 5m bars, fetched once a day (daily ATR14 needs long history to match training),
plus today's bars on demand; India VIX 5m for today. Only COMPLETED bars are used.
"""
from __future__ import annotations

import json
import math
import pickle
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .providers import IST, ProviderError

MODEL = Path(__file__).with_name("models") / "range_r4.pkl"
HAR_MODEL = Path(__file__).with_name("models") / "range_har.json"
LOG_COLS = ("rv12", "rv_prev", "atr_px", "vix")
DECISION_BAR_STARTS = tuple(range(9 * 60 + 40, 14 * 60 + 11, 15))      # the bars the models were trained on
INDEX_KEYS = {"NIFTY": "NSE_INDEX|Nifty 50", "BANKNIFTY": "NSE_INDEX|Nifty Bank"}
VIX_KEY = "NSE_INDEX|India VIX"
HISTORY_DAYS = 330
MAX_BAR_AGE_S = 600
MIN_PREV_BARS = 72           # of 75 regular-session bars (09:15-15:25 starts); it must also end with the 15:25 bar
PREV_CLOSE_TOL = 0.0025      # last 5m close vs official close: within 0.20% on 76/76 days measured (Jul-Oct 2026)
TZ = "Asia/Kolkata"


class RangeError(Exception):
    pass


def to_frame(rows: list[list]) -> pd.DataFrame:
    """Upstox candles -> regular-session 5m bars (09:15-15:25; special sessions not starting 09:15 dropped)."""
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    d = pd.DataFrame([r[:6] for r in rows], columns=["time", "open", "high", "low", "close", "volume"])
    d["time"] = pd.to_datetime(d["time"])
    d = d.drop_duplicates("time").set_index("time").sort_index().astype(float)
    d.index = pd.DatetimeIndex(d.index).tz_convert(TZ)
    hm = d.index.hour * 60 + d.index.minute
    d = d[(hm >= 9 * 60 + 15) & (hm <= 15 * 60 + 25)]
    if d.empty:
        return d
    first = d.groupby(d.index.normalize()).apply(lambda g: g.index[0].hour * 60 + g.index[0].minute)
    return d[d.index.normalize().isin(set(first[first == 9 * 60 + 15].index))]


def features(bars: pd.DataFrame, vix: pd.Series, expiry_today: bool) -> dict:
    """The 19 live features for the LAST bar of `bars` (same formulas as training)."""
    x = bars.copy()
    day = x.index.normalize()
    hm = x.index.hour * 60 + x.index.minute
    lc = np.log(x.close)
    f = {}
    for k in (1, 3, 6, 12, 24):
        f[f"r{k}"] = float((lc - lc.shift(k)).iloc[-1])
    day_open = x.open.groupby(day).transform("first")
    f["r_open"] = float((lc - np.log(day_open)).iloc[-1])
    dclose = x.close.groupby(day).last()
    prev_close = dclose.shift(1).reindex(day).to_numpy()
    f["gap"] = float(np.log(day_open.to_numpy() / prev_close)[-1])
    c0940 = x.close[hm == 9 * 60 + 40]
    c0940.index = c0940.index.normalize()
    f["first30"] = float(np.log(c0940.reindex(day).to_numpy() / day_open.to_numpy())[-1]) if hm[-1] >= 9 * 60 + 40 else math.nan
    dd = x.groupby(day).agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    pc = dd.close.shift(1)
    tr = pd.concat([dd.high - dd.low, (dd.high - pc).abs(), (dd.low - pc).abs()], axis=1).max(axis=1)
    atr_d = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().shift(1).reindex(day).to_numpy()
    g = x.groupby(day)
    f["rng_atr"] = float(((g.high.cummax() - g.low.cummin()).to_numpy() / atr_d)[-1])
    f["atr_px"] = float((atr_d / x.close.to_numpy())[-1])
    r1 = (lc - lc.shift(1)).where(hm != 9 * 60 + 15)
    f["rv12"] = float(r1.rolling(12, min_periods=8).std().iloc[-1])
    rv_day = r1.groupby(day).std()
    f["rv_prev"] = float(rv_day.shift(1).reindex(day).to_numpy()[-1])
    f["tod"] = float(hm[-1])
    f["dow"] = float(x.index[-1].dayofweek)
    f["expiry"] = float(bool(expiry_today))
    v = vix.sort_index()
    t = x.index[-1]
    f["vix"] = float(v.get(t, math.nan))
    f["vix5"] = float((v - v.shift(5)).get(t, math.nan))
    vday = v.groupby(v.index.normalize()).transform("first")
    f["vix_open"] = float((v - vday).get(t, math.nan))
    f["is_index"] = 1.0
    return f


def har_log_quantiles(model: dict, fx: dict) -> tuple[float, float, float]:
    """Linear HAR+VIX quantile model (nfce_engine/tools/range_benchmark.py: har_fit), evaluated from plain numbers."""
    row = {}
    for c in model["cols"]:
        v = fx[c]
        v = math.log(max(v, 1e-9)) if c in LOG_COLS and math.isfinite(v) else v
        row[c] = v if math.isfinite(v) else model["median"][c]
    for t in model["tods"][1:]:
        row[f"tod{t}"] = 1.0 if int(fx["tod"]) == t else 0.0
    x = [row[c] for c in model["columns"]]
    return tuple(sorted(model["coef"][q][0] + sum(a * b for a, b in zip(model["coef"][q][1:], x))
                        for q in ("0.1", "0.5", "0.9")))


@dataclass
class Forecast:
    root: str
    bar_close: datetime
    price: float
    l10: float          # next-60-minute range, points: 10% / 50% / 90% quantiles
    m50: float
    u90: float
    logq: tuple = ()    # the model's log-space quantiles (log range / price)
    har_logq: tuple = ()    # the linear HAR+VIX model's, for the live benchmark (R6)

    def line(self) -> str:
        return (f"Next-hour range forecast (R4 model): median {self.m50:.0f} pts, 80% band {self.l10:.0f}-{self.u90:.0f} pts "
                f"(from the {self.bar_close:%H:%M} bar)")


def r4_targets(entry: float, side: int, fc: Forecast, tick: float) -> tuple[float, float, float]:
    """Registered R4 rule: T1 = entry ± 0.5 x median range, T2 = ± 0.5 x U90, T3 = ± U90."""
    t1, t2, t3 = (entry + side * 0.5 * fc.m50, entry + side * 0.5 * fc.u90, entry + side * fc.u90)
    if not all(math.isfinite(t) for t in (t1, t2, t3)) or (t1 - entry) * side <= tick or \
            (t2 - t1) * side <= 0 or (t3 - t2) * side <= 0:
        raise ValueError("degenerate targets")
    return t1, t2, t3


class RangeForecaster:
    def __init__(self, provider, model_path: Path = MODEL, clock=None):
        self.provider = provider
        self.clock = clock or (lambda: datetime.now(IST))
        self.model_path = model_path
        self._model = None
        self._har = None
        self._lock = threading.RLock()
        self._hist: dict[str, tuple[date, pd.DataFrame]] = {}
        self._today: dict[str, tuple[datetime, pd.DataFrame]] = {}

    def load(self):
        if self._model is None:
            import sklearn
            blob = pickle.loads(self.model_path.read_bytes())
            want = blob["meta"]["versions"]["sklearn"]
            if sklearn.__version__ != want:
                raise RangeError(f"model needs scikit-learn {want}, installed {sklearn.__version__} (run setup.sh)")
            self._model = blob
        return self._model

    @property
    def meta(self) -> dict:
        return self.load()["meta"]

    def har(self) -> dict | None:
        if self._har is None and HAR_MODEL.exists():
            self._har = json.loads(HAR_MODEL.read_text())
        return self._har

    def _bars(self, key: str, today: date, now: datetime) -> pd.DataFrame:
        with self._lock:
            h = self._hist.get(key)
            if not h or h[0] != today:
                rows = self.provider.candles_5m(key, today - timedelta(days=HISTORY_DAYS), today - timedelta(days=1))
                self._hist[key] = h = (today, to_frame(rows))
            c = self._today.get(key)
            if not c or (now - c[0]).total_seconds() >= 60:
                self._today[key] = c = (now, to_frame(self.provider.candles_5m(key, today, today, intraday=True)))
        b = pd.concat([h[1], c[1]])
        b = b[~b.index.duplicated(keep="last")].sort_index()
        return b[b.index + pd.Timedelta(minutes=5) <= pd.Timestamp(now).tz_convert(TZ)]   # completed bars only

    def forecast(self, root: str, now: datetime, expiry_today: bool) -> Forecast:
        key = INDEX_KEYS.get(root)
        if not key:
            raise RangeError(f"no range model for {root}")
        model = self.load()
        today = now.astimezone(IST).date()
        n = now.astimezone(IST)
        last_start = n.hour * 60 + n.minute - n.minute % 5 - 5          # start of the latest completed 5m bar
        if not (9 * 60 + 40 <= last_start <= 14 * 60 + 10):              # cheap check first: no download outside hours
            raise RangeError("outside the model's hours (09:45-14:15 bar closes)")
        try:
            bars = self._bars(key, today, now)
            vix = self._bars(VIX_KEY, today, now).close
        except ProviderError as exc:
            raise RangeError(f"candle data unavailable: {exc}") from exc
        if bars.empty or bars.index[-1].date() != today:
            raise RangeError("no completed 5m bar today yet")
        last_close = bars.index[-1] + pd.Timedelta(minutes=5)
        if (pd.Timestamp(now).tz_convert(TZ) - last_close).total_seconds() > MAX_BAR_AGE_S:
            raise RangeError("latest 5m bar is stale")
        if bars.index.normalize().nunique() < 20:
            raise RangeError("not enough history for the daily ATR")
        hm = bars.index[-1].hour * 60 + bars.index[-1].minute
        if not (9 * 60 + 40 <= hm <= 14 * 60 + 10):                  # the model was trained on 09:45-14:15 decisions only
            raise RangeError("outside the model's hours (09:45-14:15 bar closes)")
        prev_days = sorted({d for d in bars.index.date if d < today})
        if not prev_days or (today - prev_days[-1]).days > 4:
            raise RangeError("history does not reach the previous session (Upstox candle lag)")
        prev = bars[bars.index.date == prev_days[-1]]
        last_hm = prev.index[-1].hour * 60 + prev.index[-1].minute
        if len(prev) < MIN_PREV_BARS or last_hm != 15 * 60 + 25:   # FIX (H06): the previous session must be complete
            raise RangeError(f"previous session {prev_days[-1]} incomplete ({len(prev)} bars)")
        tod = bars[bars.index.date == today]
        mins = tod.index.hour * 60 + tod.index.minute
        if mins[0] != 9 * 60 + 15 or len(tod) != (mins[-1] - mins[0]) // 5 + 1:
            raise RangeError("today's 5m bars have gaps")
        prev_close_hist = float(prev.close.iloc[-1])
        try:
            q = (self.provider.quotes([key]) or {}).get(key)
        except ProviderError:
            q = None
        # FIX (H06): without the official previous close the history cannot be verified, so no forecast
        if q is None or not q.prev_close:
            raise RangeError("previous close unavailable from the live quote: history cannot be verified")
        if abs(prev_close_hist / q.prev_close - 1) > PREV_CLOSE_TOL:
            with self._lock:
                self._hist.pop(key, None)                            # refetch next time: the history is behind
            raise RangeError(f"history's last close {prev_close_hist:,.1f} != previous close {q.prev_close:,.1f}: "
                             f"previous session missing (Upstox candle lag)")
        fx = features(bars, vix, expiry_today)
        bad = [k for k in ("vix", "vix5", "vix_open") if not math.isfinite(fx[k])]
        if bad:                                                        # FIX (H06): today's VIX must be there
            raise RangeError(f"India VIX for this bar unavailable ({', '.join(bad)})")
        cols = model["meta"]["features"]
        row = pd.DataFrame([[fx[c] for c in cols]], columns=cols)
        shift = model["meta"].get("conformal_shift") or [0.0, 0.0, 0.0]
        q = sorted(float(model["models"][k].predict(row)[0]) + s for k, s in zip(("q10", "q50", "q90"), shift))
        px = float(bars.close.iloc[-1])
        lo, mid, hi = (math.exp(v) * px for v in q)
        h = self.har()
        return Forecast(root, last_close.to_pydatetime(), px, lo, mid, hi, tuple(q),
                        har_log_quantiles(h, fx) if h else ())

    def warm(self, now: datetime) -> None:
        """Pre-market: download the year of history once, so the first forecast of the day is fast."""
        today = now.astimezone(IST).date()
        for key in (*INDEX_KEYS.values(), VIX_KEY):
            self._bars(key, today, now)

    def realized(self, root: str, bar_close: datetime, now: datetime) -> float | None:
        """log(range of the 12 bars after bar_close / close of the decision bar), once all 12 are complete."""
        key = INDEX_KEYS[root]
        today = now.astimezone(IST).date()
        b = self._bars(key, today, now)
        t0 = pd.Timestamp(bar_close).tz_convert(TZ)
        nxt = b[(b.index >= t0) & (b.index < t0 + pd.Timedelta(minutes=60))]
        dec = b[b.index == t0 - pd.Timedelta(minutes=5)]
        if len(nxt) != 12 or dec.empty:
            return None
        return math.log((nxt.high.max() - nxt.low.min()) / float(dec.close.iloc[0]))
