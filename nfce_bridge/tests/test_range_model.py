"""R4 range model: live features must equal the training features exactly; forecasts and targets must be sane."""
import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bridge.providers import IST, MarketProvider, ProviderError
from bridge.range_model import INDEX_KEYS, MODEL, VIX_KEY, Forecast, RangeError, RangeForecaster, features, r4_targets, to_frame

ENGINE = Path(__file__).resolve().parents[2] / "nfce_engine"
TZ = "Asia/Kolkata"


def synth(days=40, seed=3, start="2026-08-03", px=25000.0, vol=True):
    rng = np.random.default_rng(seed)
    rows = []
    for d in pd.bdate_range(start, periods=days):
        for t in pd.date_range(pd.Timestamp(d).tz_localize(TZ) + pd.Timedelta(hours=9, minutes=15), periods=75, freq="5min"):
            o = px
            c = o * (1 + rng.normal(0, 0.0012))
            rows.append([t.isoformat(), o, max(o, c) * (1 + abs(rng.normal(0, 0.0004))),
                         min(o, c) * (1 - abs(rng.normal(0, 0.0004))), c, rng.lognormal(8, 0.3) if vol else 0, 0])
            px = c
    return rows


def test_live_features_equal_training_features_bar_for_bar():
    sys.path.insert(0, str(ENGINE))
    from tools.ml_study import symbol_frame
    bars = to_frame(synth())
    vix = to_frame(synth(seed=9, px=14.0)).close
    eng = symbol_frame(bars)
    cols = ["r1", "r3", "r6", "r12", "r24", "r_open", "gap", "first30", "rng_atr", "atr_px", "rv12", "rv_prev", "tod", "dow"]
    hm = bars.index.hour * 60 + bars.index.minute
    checked = 0
    for i in np.flatnonzero((hm >= 9 * 60 + 40) & (hm <= 14 * 60 + 10))[-80::7]:
        live = features(bars.iloc[: i + 1], vix, expiry_today=False)
        for c in cols:
            a, b = live[c], float(eng[c].iloc[i])
            assert (math.isnan(a) and math.isnan(b)) or a == pytest.approx(b, rel=1e-9, abs=1e-12), (c, i)
        t = bars.index[i]
        assert live["vix"] == pytest.approx(vix[t]) and live["vix5"] == pytest.approx(vix[t] - vix.shift(5)[t])
        checked += 1
    assert checked >= 10


class CandleProvider(MarketProvider):
    def __init__(self, rows_by_key, today_rows_by_key):
        self.rows, self.today = rows_by_key, today_rows_by_key
        self.calls = 0

    def expiries(self, k):
        return []

    def chain(self, k, e):
        raise ProviderError("n/a")

    def quotes(self, keys):
        """Index quotes carry the official previous close (= the history's last close when the history is complete)."""
        from bridge.providers import Quote
        now = datetime.now(IST)
        out = {}
        for k in keys:
            if self.rows.get(k):
                pc = [r for r in self.rows[k] if r[0][:10] == max(x[0][:10] for x in self.rows[k])][-1][4]
                out[k] = Quote(k, pc, now, now, prev_close=pc)
        return out

    def front_future(self, u, t):
        raise ProviderError("n/a")

    def candles_5m(self, key, start, end, intraday=False):
        self.calls += 1
        return self.today[key] if intraday else self.rows[key]


def provider_for(days=40):
    allrows = synth(days)
    vixrows = synth(days, seed=9, px=14.0)
    last_day = allrows[-1][0][:10]
    split = lambda rows: ([r for r in rows if r[0][:10] != last_day], [r for r in rows if r[0][:10] == last_day])  # noqa: E731
    (h, t), (vh, vt) = split(allrows), split(vixrows)
    return CandleProvider({INDEX_KEYS["NIFTY"]: h, VIX_KEY: vh}, {INDEX_KEYS["NIFTY"]: t, VIX_KEY: vt}), last_day


@pytest.mark.skipif(not MODEL.exists(), reason="model file not built")
def test_forecast_is_ordered_positive_and_uses_completed_bars_only():
    prov, last_day = provider_for()
    now = datetime.fromisoformat(f"{last_day}T11:02:00+05:30")
    rf = RangeForecaster(prov, clock=lambda: now)
    fc = rf.forecast("NIFTY", now, expiry_today=False)
    assert 0 < fc.l10 < fc.m50 < fc.u90 < 0.05 * fc.price
    assert fc.bar_close == datetime.fromisoformat(f"{last_day}T11:00:00+05:30")    # the 10:55 bar, not the forming one
    assert "median" in fc.line()
    calls = prov.calls
    rf.forecast("NIFTY", now + timedelta(seconds=20), expiry_today=False)
    assert prov.calls == calls                                                      # cached within a minute


@pytest.mark.skipif(not MODEL.exists(), reason="model file not built")
def test_forecast_refuses_stale_data_outside_hours_and_unknown_index():
    prov, last_day = provider_for()
    with pytest.raises(RangeError, match="hours"):
        RangeForecaster(prov).forecast("NIFTY", datetime.fromisoformat(f"{last_day}T15:00:00+05:30"), False)
    prov2, last_day2 = provider_for()
    prov2.today = {k: [r for r in v if r[0][11:16] <= "10:00"] for k, v in prov2.today.items()}
    with pytest.raises(RangeError, match="stale"):
        RangeForecaster(prov2).forecast("NIFTY", datetime.fromisoformat(f"{last_day2}T11:30:00+05:30"), False)
    with pytest.raises(RangeError, match="no range model"):
        RangeForecaster(prov).forecast("SENSEX", datetime.now(IST), False)


def test_r4_targets_rule_and_degenerate_cases():
    fc = Forecast("NIFTY", datetime.now(IST), 25000.0, 40.0, 60.0, 110.0)
    assert r4_targets(25000.0, 1, fc, 0.1) == (25030.0, 25055.0, 25110.0)
    assert r4_targets(25000.0, -1, fc, 0.1) == (24970.0, 24945.0, 24890.0)
    with pytest.raises(ValueError):
        r4_targets(25000.0, 1, Forecast("NIFTY", datetime.now(IST), 25000.0, 0.0, 0.1, 0.1), 0.1)
    with pytest.raises(ValueError):
        r4_targets(25000.0, 1, Forecast("NIFTY", datetime.now(IST), 25000.0, 40.0, float("nan"), 110.0), 0.1)


# ---------------- service integration (R4 book) ----------------
from conftest import FakeTelegram, StubProvider, make_payload, sig  # noqa: E402


class StubWithCandles(StubProvider):
    """The normal stub plus 5m candles for NIFTY and VIX ending on the clock's day."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        day = self.clock().date()
        start = (pd.Timestamp(day) - pd.offsets.BDay(39)).date().isoformat()
        rows, vrows = synth(40, start=start), synth(40, seed=9, start=start, px=14.0)
        self.c = {INDEX_KEYS["NIFTY"]: rows, VIX_KEY: vrows}

    def candles_5m(self, key, start, end, intraday=False):
        rows = self.c.get(key, [])
        d = self.clock().date().isoformat()
        return [r for r in rows if (r[0][:10] == d) == intraday]

    def quotes(self, keys):
        out = super().quotes(keys)
        d = self.clock().date().isoformat()
        for k in keys:
            if k in self.c and k in out:
                out[k].prev_close = [r for r in self.c[k] if r[0][:10] < d][-1][4]
        return out


def bridge_with(provider_cls, settings, clock):
    from bridge.service import Bridge
    from bridge.store import Store
    prov = provider_cls(make_payload(), clock=clock)
    return Bridge(settings, prov, Store(settings.db_path), FakeTelegram(), clock=clock), prov


@pytest.mark.skipif(not MODEL.exists(), reason="model file not built")
def test_r4_book_opens_with_range_targets_alongside_the_executable_book(settings, clock):
    b, prov = bridge_with(StubWithCandles, settings, clock)
    text = b.handle_payload(sig(clock=clock, sid="r4a"), "tradingview")
    assert "Next-hour range forecast (R4 model)" in text and "r4 book: entered" in text
    rows = dict(((bk, (e, t1, t2, t3, sl)) for bk, e, t1, t2, t3, sl in
                 b.store.db.execute("SELECT book, entry, t1, t2, t3, sl FROM paper_trades WHERE sid='r4a'")))
    ex, r4 = rows["executable"], rows["r4"]
    assert r4[0] == ex[0] and r4[4] == ex[4]                       # same entry, same stop: only the targets differ
    assert r4[1] != ex[1] and ex[0] < r4[1] < r4[2] < r4[3]


def test_r4_without_candle_data_is_rejected_with_a_reason_and_never_blocks_the_signal(make_bridge, clock):
    b, prov, tg = make_bridge()                                   # the plain stub has no candle history
    text = b.handle_payload(sig(clock=clock, sid="r4b"), "tradingview")
    assert "Range forecast unavailable" in text and "executable book: entered" in text
    st, why = b.store.db.execute("SELECT status, exit_reason FROM paper_trades WHERE sid='r4b' AND book='r4'").fetchone()
    assert st == "REJECTED" and "no range forecast" in why


def test_r4_report_pairs_closed_trades_by_signal(make_bridge, clock):
    b, prov, tg = make_bridge()
    assert "R4" in b.r4_report() and "0 paired" in b.r4_report()


@pytest.mark.skipif(not MODEL.exists(), reason="model file not built")
def test_forecast_refuses_when_history_is_missing_the_previous_session():
    """Live finding (20 Oct 2026): Upstox's historical candles can lag a day; the gap/rv_prev features would be wrong."""
    from bridge.providers import Quote
    prov, last_day = provider_for()
    key = INDEX_KEYS["NIFTY"]
    hist = prov.rows[key]
    prev_day = sorted({r[0][:10] for r in hist})[-1]
    true_prev_close = [r for r in hist if r[0][:10] == prev_day][-1][4]
    now = datetime.fromisoformat(f"{last_day}T11:02:00+05:30")
    prov.quotes = lambda keys: {key: Quote(key, 1.0, now, now, prev_close=true_prev_close)}
    assert RangeForecaster(prov).forecast("NIFTY", now, False).m50 > 0           # history complete: forecast
    prov.rows = {**prov.rows, key: [r for r in hist if r[0][:10] != prev_day]}       # Upstox lag: yesterday missing
    with pytest.raises(RangeError, match="previous session missing"):
        RangeForecaster(prov).forecast("NIFTY", now, False)


def test_quote_parser_derives_the_previous_close():
    from bridge.providers import parse_upstox_quotes
    q = parse_upstox_quotes({"status": "success", "data": {"NSE_INDEX:Nifty 50": {
        "instrument_token": "NSE_INDEX|Nifty 50", "last_price": 22888.95, "net_change": -257.2}}})["NSE_INDEX|Nifty 50"]
    assert q.prev_close == pytest.approx(23146.15)


# ---------------- review round 3: calibrated model, HAR baseline, live benchmark (R6) ----------------
def test_har_model_in_the_bridge_equals_the_engine_formula():
    import json
    sys.path.insert(0, str(ENGINE))
    from tools.range_benchmark import har_predict
    from bridge.range_model import HAR_MODEL, har_log_quantiles
    model = json.loads(HAR_MODEL.read_text())
    bars = to_frame(synth())
    vix = to_frame(synth(seed=9, px=14.0)).close
    hm = bars.index.hour * 60 + bars.index.minute
    for i in np.flatnonzero(hm == 10 * 60 + 25)[-5:]:
        fx = features(bars.iloc[: i + 1], vix, expiry_today=False)
        a = har_log_quantiles(model, fx)
        b = har_predict(model, pd.DataFrame([fx]))[0]
        assert a == pytest.approx(tuple(sorted(b)), rel=1e-9)


@pytest.mark.skipif(not MODEL.exists(), reason="model file not built")
def test_shipped_model_is_the_calibrated_m1_and_its_shift_is_applied():
    import pickle
    meta = pickle.loads(MODEL.read_bytes())["meta"]
    assert meta["model"].startswith("M1") and len(meta["conformal_shift"]) == 3
    prov, last_day = provider_for()
    now = datetime.fromisoformat(f"{last_day}T11:02:00+05:30")
    fc = RangeForecaster(prov).forecast("NIFTY", now, False)
    assert len(fc.logq) == 3 and len(fc.har_logq) == 3
    assert fc.m50 == pytest.approx(math.exp(fc.logq[1]) * fc.price)


@pytest.mark.skipif(not MODEL.exists(), reason="model file not built")
def test_live_range_benchmark_records_then_scores(settings, clock):
    b, prov = bridge_with(StubWithCandles, settings, clock)        # clock: 10:00, the 09:55 bar just closed
    assert b.record_range_forecasts(clock()) == 3                  # M1, HAR and their average, for NIFTY
    assert b.record_range_forecasts(clock()) == 0                  # once per decision bar
    clock.advance(minutes=65)
    assert b.score_range_forecasts(clock()) == 1
    rep = b.range_report()
    assert "NIFTY M1: n=1" in rep and "NIFTY HAR: n=1" in rep and "NIFTY ENS: n=1" in rep
