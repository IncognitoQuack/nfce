"""The bridge's own NFCE engine: fed bar by bar, it must emit exactly the batch engine's trades, on time, no lookahead."""
import sys
from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd

from bridge.live_engine import ENGINE_DIR, LiveEngine, frame, to_15m
from bridge.providers import MarketProvider

sys.path.insert(0, str(ENGINE_DIR))
from nfce import Params, prepare, run  # noqa: E402

TZ = "Asia/Kolkata"
LOOSE = dict(min_score_in=1, chop_max=100.0, body_atr=0.0, room_r=0.0)
HW = ["HDFCBANK", "ICICIBANK", "RELIANCE", "INFY", "BHARTIARTL"]


def series(seed, px, days=45, vol=True):
    rng = np.random.default_rng(seed)
    rows = []
    for d in pd.bdate_range("2026-08-03", periods=days):
        for t in pd.date_range(pd.Timestamp(d).tz_localize(TZ) + pd.Timedelta(hours=9, minutes=15), periods=75, freq="5min"):
            o = px
            c = o * (1 + rng.normal(0.0001, 0.0015))
            rows.append([t.isoformat(), o, max(o, c) * (1 + abs(rng.normal(0, 0.0005))),
                         min(o, c) * (1 - abs(rng.normal(0, 0.0005))), c, float(rng.lognormal(10, 0.4)) if vol else 0.0, 1e7])
            px = c
    return rows


class ReplayProvider(MarketProvider):
    """Serves candles as Upstox would at `now`: history up to yesterday, today's bars including the forming one."""

    def __init__(self, clock):
        self.clock = clock
        self.rows = {"FUT": series(1, 25000.0), "NSE_INDEX|India VIX": series(2, 14.0, vol=False)}
        for k, s in enumerate(HW):
            self.rows[f"EQ|{s}"] = series(10 + k, 1000.0 + 100 * k)

    def expiries(self, k):
        return []

    def chain(self, k, e):
        raise NotImplementedError

    def quotes(self, keys):
        return {}

    def front_future(self, u, t):
        raise NotImplementedError

    def equity_key(self, sym):
        return f"EQ|{sym}"

    def candles_5m(self, key, start, end, intraday=False):
        now = self.clock()
        out = []
        for r in self.rows[key]:
            t = datetime.fromisoformat(r[0])
            if intraday and t.date() == now.date() and t <= now:
                out.append(r)
            elif not intraday and start <= t.date() <= end:
                out.append(r)
        return out


def test_live_engine_emits_exactly_the_batch_engines_trades_on_time():
    clock = SimpleNamespace(t=None)
    prov = ReplayProvider(lambda: clock.t)
    got = []
    bridge = SimpleNamespace(s=SimpleNamespace(underlyings={"NIFTY": "NSE_INDEX|Nifty 50"}), provider=prov,
                             keys=lambda root: ("FUT", "NSE_INDEX|Nifty 50"),
                             handle_payload=lambda p, src: (got.append((clock.t, p)), "ok")[1])
    eng = LiveEngine(bridge, ["NIFTY"], params=LOOSE)
    last_day = pd.Timestamp(prov.rows["FUT"][-1][0]).tz_convert(TZ).normalize()
    for k in range(1, 76):                                         # every 5-minute close of the last session, +25 s
        clock.t = (last_day + pd.Timedelta(hours=9, minutes=15 + 5 * k, seconds=25)).to_pydatetime()
        eng.step(clock.t)
    bars = frame(prov.rows["FUT"])                                 # batch: the whole history at once
    vix = frame(prov.rows["NSE_INDEX|India VIX"])[["close"]]
    hw = [frame(prov.rows[f"EQ|{s}"])[["open", "close"]] for s in HW]
    p = Params(instr="NIFTY", **LOOSE)
    want = {}
    for tf in (5, 15):
        if tf == 5:
            b, v, h = bars, vix, hw
        else:
            b = to_15m(bars)
            v = to_15m(vix.assign(open=vix.close, high=vix.close, low=vix.close, volume=0, oi=0))[["close"]]
            h = [to_15m(x.assign(high=x.max(axis=1), low=x.min(axis=1), volume=0, oi=0))[["open", "close"]] for x in hw]
        for t in run(prepare(b, tf, p, vix=v.reindex(b.index).ffill().dropna(),
                             hw=[x.reindex(b.index).ffill().dropna() for x in h]), p):
            if t.entry_time.tz_convert(TZ).normalize() == last_day:
                want[(tf, t.entry_time)] = round(t.entry, 2)
    have = {(int(q["tf"]), pd.Timestamp(q["t"], unit="ms", tz="UTC").tz_convert(TZ)): q["entry"] for _, q in got}
    assert want, "fixture must produce trades on the last day"
    assert have == want
    for when, q in got:                                            # each emitted 20-110 s after its bar closed
        age = (pd.Timestamp(when).tz_convert(TZ) - pd.Timestamp(q["t"], unit="ms", tz="UTC")).total_seconds()
        assert 20 <= age <= 110
        s = 1 if q["side"] == "BUY" else -1
        assert (q["entry"] - q["sl"]) * s > 0 and (q["t1"] - q["entry"]) * s > 0 and q["px"] == "futures"



def series3(seed, px, days=30, vol=True):
    rng = np.random.default_rng(seed)
    rows = []
    for d in pd.bdate_range("2026-08-03", periods=days):
        for t in pd.date_range(pd.Timestamp(d).tz_localize(TZ) + pd.Timedelta(hours=9, minutes=15), periods=125, freq="3min"):
            o = px
            c = o * (1 + rng.normal(0.0001, 0.0012))
            rows.append([t.isoformat(), o, max(o, c) * (1 + abs(rng.normal(0, 0.0004))),
                         min(o, c) * (1 - abs(rng.normal(0, 0.0004))), c, float(rng.lognormal(10, 0.4)) if vol else 0.0, 1e7])
            px = c
    return rows


class Replay3(ReplayProvider):
    def __init__(self, clock):
        self.clock = clock
        self.rows = {"FUT": series3(1, 25000.0), "NSE_INDEX|India VIX": series3(2, 14.0, vol=False)}
        for k, s in enumerate(HW):
            self.rows[f"EQ|{s}"] = series3(10 + k, 1000.0 + 100 * k)

    def candles_5m(self, key, start, end, intraday=False, minutes=5):
        assert minutes == 3
        return super().candles_5m(key, start, end, intraday)


def test_live_engine_3_minute_timeframe_matches_the_batch_engine():
    clock = SimpleNamespace(t=None)
    prov = Replay3(lambda: clock.t)
    got = []
    bridge = SimpleNamespace(s=SimpleNamespace(underlyings={"NIFTY": "NSE_INDEX|Nifty 50"}), provider=prov,
                             keys=lambda root: ("FUT", "NSE_INDEX|Nifty 50"),
                             handle_payload=lambda p, src: (got.append((clock.t, p)), "ok")[1])
    eng = LiveEngine(bridge, ["NIFTY"], tfs=(3,), params=LOOSE)
    last_day = pd.Timestamp(prov.rows["FUT"][-1][0]).tz_convert(TZ).normalize()
    for k in range(1, 126):
        clock.t = (last_day + pd.Timedelta(hours=9, minutes=15 + 3 * k, seconds=25)).to_pydatetime()
        eng.step(clock.t)
    bars = frame(prov.rows["FUT"], 3)
    vix = frame(prov.rows["NSE_INDEX|India VIX"], 3)[["close"]]
    hw = [frame(prov.rows[f"EQ|{s}"], 3)[["open", "close"]] for s in HW]
    p = Params(instr="NIFTY", **LOOSE)
    out = run(prepare(bars, 3, p, vix=vix.reindex(bars.index).ffill().dropna(),
                      hw=[x.reindex(bars.index).ffill().dropna() for x in hw]), p)
    want = {t.entry_time: round(t.entry, 2) for t in out if t.entry_time.tz_convert(TZ).normalize() == last_day}
    have = {pd.Timestamp(q["t"], unit="ms", tz="UTC").tz_convert(TZ): q["entry"] for _, q in got}
    assert want and have == want and all(q["tf"] == "3" for _, q in got)
    assert frame(prov.rows["FUT"], 3).index[-1].strftime("%H:%M") == "15:27"      # the last 3m bar is kept
