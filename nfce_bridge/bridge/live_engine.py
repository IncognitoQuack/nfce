"""Signals without a paid TradingView plan: the NFCE engine (bar-for-bar equal to the Pine strategy, see
evidence/golden_parity_*.txt) runs on live Upstox candles of the front-month future.

Every completed 5m (and 15m) bar: fetch the future's candles (about 40 sessions of history, fetched once a day, plus
today's), India VIX and the five heavyweight stocks; run prepare() + run(); if the engine opened a trade on the bar
that just closed, turn it into the same JSON alert Pine would send and hand it to the bridge (source "engine").
The bridge then treats it exactly like a TradingView alert: chain check, evidence card, range forecast, paper books.

Known difference from TradingView: previous-day levels come from the intraday bars (TradingView uses the daily bar,
whose close is the settlement price), so a signal can occasionally differ near those levels.
"""
from __future__ import annotations

import logging
import sys
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from .providers import IST, ProviderError

ENGINE_DIR = Path(__file__).resolve().parents[2] / "nfce_engine"
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

log = logging.getLogger("nfce.engine")
TZ = "Asia/Kolkata"
VIX_KEY = "NSE_INDEX|India VIX"
HEAVYWEIGHTS = {"NIFTY": ["HDFCBANK", "ICICIBANK", "RELIANCE", "INFY", "BHARTIARTL"],
                "SENSEX": ["HDFCBANK", "ICICIBANK", "RELIANCE", "INFY", "BHARTIARTL"],
                "BANKNIFTY": ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK"]}
HISTORY_DAYS = 60
SETTLE_S = 20                      # wait this long after a bar closes, so the candle is final


def frame(rows: list[list], tf: int = 5) -> pd.DataFrame:
    """Upstox candles [time, o, h, l, c, volume, oi] -> regular-session bars (starts 09:15 .. 15:30 - tf)."""
    cols = ["open", "high", "low", "close", "volume", "oi"]
    if not rows:                                   # empty, but with a time index, so it concatenates and compares
        return pd.DataFrame(columns=cols, index=pd.DatetimeIndex([], tz=TZ), dtype=float)
    d = pd.DataFrame([list(r[:7]) + [0] * (7 - len(r[:7])) for r in rows], columns=["time"] + cols)
    d["time"] = pd.to_datetime(d["time"])
    d = d.drop_duplicates("time").set_index("time").sort_index().astype(float)
    d.index = pd.DatetimeIndex(d.index).tz_convert(TZ)
    hm = d.index.hour * 60 + d.index.minute
    return d[(hm >= 9 * 60 + 15) & (hm <= 15 * 60 + 30 - tf)]


def to_15m(d: pd.DataFrame) -> pd.DataFrame:
    """15-minute bars aligned to 09:15, complete buckets only (3 five-minute bars)."""
    g = d.groupby(pd.Grouper(freq="15min", origin=pd.Timestamp("2022-01-03 09:15", tz=TZ)))
    o = g.agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum", "oi": "last"})
    n = g.size().reindex(o.index).fillna(0)
    return o[(n == 3) & o.close.notna()]


class LiveEngine:
    def __init__(self, bridge, roots: list[str], tfs: tuple[int, ...] = (5, 15), params: dict | None = None):
        self.b = bridge
        self.params = params or {}                       # tests only; live = the strategy's defaults
        self.roots = [r for r in roots if r in bridge.s.underlyings]
        self.tfs = tfs
        self._hist: dict[str, tuple[date, pd.DataFrame]] = {}
        self._today: dict[str, tuple[datetime, pd.DataFrame]] = {}
        self._done: set[tuple[str, datetime]] = set()
        self._lock = threading.Lock()
        self.status: dict[str, str] = {}

    @staticmethod
    def slot(now: datetime, minutes: int = 5) -> datetime:
        """The most recent bar close of a `minutes` grid anchored at 09:15."""
        n = now.astimezone(IST)
        m = n.hour * 60 + n.minute - (9 * 60 + 15)
        m -= m % minutes
        t = 9 * 60 + 15 + m
        return n.replace(hour=t // 60, minute=t % 60, second=0, microsecond=0)

    # ---------- data ----------
    def _candles(self, key: str, today: date, now: datetime, minutes: int = 5) -> pd.DataFrame:
        prov = self.b.provider
        kw = {} if minutes == 5 else {"minutes": minutes}
        ck = (key, minutes)
        with self._lock:
            h = self._hist.get(ck)
            if not h or h[0] != today:
                days = HISTORY_DAYS if minutes >= 5 else 30         # 3m: 30 days is about 2,500 bars, plenty
                h = (today, frame(prov.candles_5m(key, today - timedelta(days=days), today - timedelta(days=1), **kw),
                                  minutes))
                self._hist[ck] = h
            c = self._today.get(ck)
            if not c or c[0] != self.slot(now, minutes):         # today's candles once per completed bar
                c = (self.slot(now, minutes), frame(prov.candles_5m(key, today, today, intraday=True, **kw), minutes))
                self._today[ck] = c
        t = c[1]
        d = pd.concat([h[1], t])
        d = d[~d.index.duplicated(keep="last")].sort_index()
        return d[d.index + pd.Timedelta(minutes=minutes) <= pd.Timestamp(now).tz_convert(TZ)]   # completed bars only

    def warm(self, now: datetime) -> None:
        """Pre-market: history for every future, VIX and heavyweight, so the first bar of the day is quick."""
        for root in self.roots:
            self.inputs(root, now)

    def history_lag(self, root: str, bars: pd.DataFrame, today: date) -> str | None:
        """FIX (live, 19 Oct): Upstox history can miss yesterday. Compare the history's last close with the futures
        quote's previous close (settlement, so allow 0.5%)."""
        fkey, _ = self.b.keys(root)
        prev = bars[bars.index.date < today]
        if prev.empty:
            return "no history before today"
        prev = prev[prev.index.date == prev.index.date[-1]]
        try:
            q = (self.b.provider.quotes([fkey]) or {}).get(fkey)
        except ProviderError:
            return None                                   # cannot check: carry on, the quote path reports outages
        if q is None or not q.prev_close:
            return None
        last = float(prev.close.iloc[-1])
        if abs(last / q.prev_close - 1) > 0.005:
            with self._lock:
                self._hist.pop(fkey, None)                # refetch on the next bar
            return f"history ends {prev.index[-1]:%d %b} at {last:,.1f}, previous close {q.prev_close:,.1f}: lagging"
        return None

    def inputs(self, root: str, now: datetime, minutes: int = 5):
        today = now.astimezone(IST).date()
        fkey, _ = self.b.keys(root)
        bars = self._candles(fkey, today, now, minutes)
        vix = self._candles(VIX_KEY, today, now, minutes)[["close"]]
        hw = []
        for sym in HEAVYWEIGHTS.get(root, HEAVYWEIGHTS["NIFTY"]):
            k = self.b.provider.equity_key(sym)
            if k:
                hw.append(self._candles(k, today, now, minutes)[["open", "close"]])
        return bars, vix, hw

    # ---------- signals ----------
    def signals(self, root: str, now: datetime, grid: int = 5) -> list[dict]:
        """Engine trades whose entry bar is the bar that has just closed, as Pine-format alerts.
        grid 5 = the 5m and 15m timeframes (15m built from 5m); grid 3 = the 3m timeframe (Upstox 3m candles)."""
        from nfce import Params, prepare, run
        bars5, vix5, hw5 = self.inputs(root, now, grid)
        if bars5.empty or bars5.index[-1].date() != now.astimezone(IST).date():
            self.status[root] = "no completed bar today yet"
            return []
        lag = self.history_lag(root, bars5, now.astimezone(IST).date())
        if lag:
            self.status[root] = f"waiting: {lag}"
            return []
        out = []
        for tf in [t for t in self.tfs if (t == 3) == (grid == 3)]:
            if tf in (3, 5):
                bars, vix, hw = bars5, vix5, hw5
            else:
                bars = to_15m(bars5)
                vix = to_15m(vix5.assign(open=vix5.close, high=vix5.close, low=vix5.close, volume=0, oi=0))[["close"]]
                hw = [to_15m(h.assign(high=h[["open", "close"]].max(axis=1), low=h[["open", "close"]].min(axis=1),
                                      volume=0, oi=0))[["open", "close"]] for h in hw5]
            if len(bars) < 200:
                self.status[root] = f"only {len(bars)} {tf}m bars of history"
                continue
            last_close = bars.index[-1] + pd.Timedelta(minutes=tf)
            if last_close != pd.Timestamp(self.slot(now, grid)):
                continue                                        # this timeframe's bar did not just close
            vix = vix.reindex(bars.index).ffill().dropna()
            hw = [h.reindex(bars.index).ffill().dropna() for h in hw]
            p = Params(instr=root, **self.params)
            open_now: list = []
            run(prepare(bars, tf, p, vix=vix if len(vix) else None, hw=hw), p, open_out=open_now)
            for t in open_now:                                  # a trade entered on the bar that just closed
                if t.entry_time != last_close:
                    continue
                s = 1 if t.side == "L" else -1
                ms = int(last_close.timestamp() * 1000)
                fut = "BSE" if root == "SENSEX" else "NSE"
                out.append({"v": 2, "kind": "signal", "id": f"ENG-{root}-{tf}-{ms}-{t.side}", "t": ms,
                            "untested_tf": tf == 3,
                            "symbol": f"{fut}:{root}1!", "tf": str(tf), "side": "BUY" if s > 0 else "SELL",
                            "entry": round(t.entry, 2), "sl": round(t.entry - s * t.R, 2),
                            "t1": round(t.entry + s * p.r1m * t.R, 2), "t2": round(t.entry + s * p.r2m * t.R, 2),
                            "t3": round(t.entry + s * p.r3m * t.R, 2), "score": round(t.score, 1), "grade": t.grade,
                            "px": "futures"})
            self.status[root] = f"ok, last {tf}m bar {bars.index[-1]:%H:%M}"
        return out

    def step(self, now: datetime) -> int:
        """Call often (every poll tick); works once per root per bar close, SETTLE_S..110 s after it."""
        n = 0
        grids = sorted({3 if t == 3 else 5 for t in self.tfs})
        for grid in grids:
            slot = self.slot(now, grid)
            age = (now.astimezone(IST) - slot).total_seconds()
            hm = slot.hour * 60 + slot.minute
            if not (SETTLE_S <= age <= 110) or not (9 * 60 + 15 + grid <= hm <= 15 * 60 + 30):
                continue
            for root in self.roots:
                if (root, grid, slot) in self._done:
                    continue
                try:
                    sigs = self.signals(root, now, grid)
                    self._done.add((root, grid, slot))
                    for payload in sigs:
                        if self.b.handle_payload(payload, "engine") != "duplicate alert ignored":
                            n += 1
                except ProviderError as exc:
                    self.status[root] = f"data error: {exc}"[:160]
                except Exception as exc:                        # never let the engine break the poll loop
                    log.exception("live engine failed for %s", root)
                    self.status[root] = f"error {type(exc).__name__}"
        return n
