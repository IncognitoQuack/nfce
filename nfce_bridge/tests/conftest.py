import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bridge.config import Settings  # noqa: E402
from bridge.providers import IST, Future, MarketProvider, Quote, parse_upstox_chain  # noqa: E402

T0 = datetime(2026, 10, 21, 10, 0, tzinfo=IST)     # a Wednesday, inside market hours


def make_payload(spot=25000.0, step=50, n=10, expiry="2026-10-27", call=None, put=None, iv=12.0, prev_missing=False,
                 bid_ask=True):
    """Upstox-format chain. call/put: dict strike -> (oi, prev_oi, ltp). prev_missing drops every prev_oi field.
    bid_ask adds bid_price/ask_price = ltp -/+ 0.5 to every option."""
    call, put = call or {}, put or {}
    data = []
    for k in range(-n, n + 1):
        strike = round(spot / step) * step + k * step
        c = call.get(strike, (100_000, 100_000, max(1.0, spot - strike) + 20))
        p = put.get(strike, (100_000, 100_000, max(1.0, strike - spot) + 20))
        cm = {"ltp": c[2], "volume": 1000, "oi": c[0]}
        pm = {"ltp": p[2], "volume": 1000, "oi": p[0]}
        if bid_ask:
            cm.update(bid_price=c[2] - 0.5, ask_price=c[2] + 0.5)
            pm.update(bid_price=p[2] - 0.5, ask_price=p[2] + 0.5)
        if prev_missing not in (True, "call"):
            cm["prev_oi"] = c[1]
        if prev_missing not in (True, "put"):
            pm["prev_oi"] = p[1]
        data.append({
            "expiry": expiry, "pcr": 1.0, "strike_price": strike, "underlying_key": "NSE_INDEX|Nifty 50",
            "underlying_spot_price": spot,
            "call_options": {"instrument_key": f"NSE_FO|C{strike}", "market_data": cm,
                             "option_greeks": {"iv": iv, "delta": 0.5}},
            "put_options": {"instrument_key": f"NSE_FO|P{strike}", "market_data": pm,
                            "option_greeks": {"iv": iv, "delta": -0.5}},
        })
    return {"status": "success", "data": data}


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t = self.t + timedelta(**kw)
        return self.t

    def set(self, t):
        self.t = t
        return t


class StubProvider(MarketProvider):
    """Chain from a payload; futures quote = spot + basis (or fut_price), fresh unless frozen_ltt is set."""

    def __init__(self, payload, clock=None, basis=0.0, fut_price=None, spread=0.2):
        self.payload = payload
        self.clock = clock or Clock()
        self.basis = basis
        self.fut_price = fut_price
        self.spread = spread
        self.fail = None          # exception instance to raise from every call
        self.frozen_ltt = None    # last-trade time to report (simulates a frozen feed / holiday)
        self.calls = 0
        self.quote_calls = 0

    def expiries(self, underlying_key):
        return ["2020-01-01", self.payload["data"][0]["expiry"], "2099-01-01"]

    def chain(self, underlying_key, expiry):
        if self.fail:
            raise self.fail
        self.calls += 1
        return parse_upstox_chain(self.payload, underlying_key, fetched_at=self.clock().astimezone(timezone.utc))

    def front_future(self, underlying, today):
        return Future(underlying, f"NSE_FO|FUT-{underlying}", today, 65, 0.1, f"{underlying} FUT")

    def quotes(self, keys):
        if self.fail:
            raise self.fail
        self.quote_calls += 1
        now = self.clock()
        ltt = self.frozen_ltt or now - timedelta(seconds=1)
        spot = float(self.payload["data"][0]["underlying_spot_price"])
        out = {}
        for k in keys:
            if k.startswith("NSE_FO"):
                px = self.fut_price if self.fut_price is not None else spot + self.basis
                out[k] = Quote(k, px, ltt, now, bid=round(px - self.spread / 2, 2), ask=round(px + self.spread / 2, 2))
            else:
                out[k] = Quote(k, spot, ltt, now)
        return out


class FakeTelegram:
    def __init__(self):
        self.sent = []
        self.enabled = True

    def send(self, text, html=False, to=None):
        self.sent.append(text)
        return True

    def send_admin(self, text, html=False):
        self.sent.append(text)
        return True

    def poll_commands(self, timeout=30):
        return []

    def commit(self):
        pass

    def send_document(self, path, caption="", to=None):
        self.sent.append(f"[document {path}] {caption}")
        return True


def bar_ms(t: datetime) -> int:
    return int(t.timestamp() * 1000)


def sig(entry=25000.0, sl=24960.0, t1=None, t2=None, t3=None, side="BUY", clock=None, delay_s=5, sid="T1",
        symbol="NSE:NIFTY1!", tf="5", grade="A"):
    s = 1 if side == "BUY" else -1
    r = abs(entry - sl)
    d = {"v": 2, "id": sid, "symbol": symbol, "tf": tf, "side": side, "entry": entry, "sl": sl,
         "t1": t1 or entry + s * r, "t2": t2 or entry + 2 * s * r, "t3": t3 or entry + 3 * s * r,
         "score": 72, "grade": grade, "oi": "Long build-up"}
    if clock is not None:
        d["t"] = bar_ms(clock() - timedelta(seconds=delay_s))
    return d


@pytest.fixture
def settings(tmp_path):
    s = Settings()
    s.db_path = tmp_path / "t.db"
    s.webhook_secret = "s3cret-" + "x" * 20
    return s


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def make_bridge(settings, clock):
    from bridge.service import Bridge
    from bridge.store import Store

    def _make(payload=None, **kw):
        prov = StubProvider(payload or make_payload(), clock=clock, **kw)
        tg = FakeTelegram()
        b = Bridge(settings, prov, Store(settings.db_path), tg, clock=clock)
        return b, prov, tg
    return _make



@pytest.fixture(autouse=True)
def _no_nse(monkeypatch):
    """Tests never call NSE: the results calendar (bridge/events.py) sees no meetings unless a test supplies them."""
    import bridge.events as ev
    monkeypatch.setattr(ev, "nse_fetch", lambda d0, d1: [])
