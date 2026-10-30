"""Market-data providers. Upstox is implemented; others plug in by subclassing MarketProvider.

Every network or decoding failure is raised as ProviderError (TokenExpired for auth problems), so callers
never see raw httpx exceptions. Missing fields stay missing (None), they are never turned into zeros.
"""
from __future__ import annotations

import gzip
import json
import math
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

IST = ZoneInfo("Asia/Kolkata")
UPSTOX_BASE = "https://api.upstox.com/v2"
INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
BSE_INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/BSE.json.gz"   # SENSEX futures


@dataclass
class StrikeRow:
    strike: float
    call_oi: float = 0.0
    call_prev_oi: float | None = None
    call_iv: float | None = None
    call_ltp: float | None = None
    call_volume: float = 0.0
    put_oi: float = 0.0
    put_prev_oi: float | None = None
    put_iv: float | None = None
    put_ltp: float | None = None
    put_volume: float = 0.0
    call_bid: float | None = None      # best bid/ask, recorded for the registered option-execution test (R1)
    call_ask: float | None = None
    put_bid: float | None = None
    put_ask: float | None = None
    call_key: str = ""
    put_key: str = ""
    call_delta: float | None = None
    put_delta: float | None = None

    @property
    def call_doi(self) -> float | None:
        return None if self.call_prev_oi is None else self.call_oi - self.call_prev_oi

    @property
    def put_doi(self) -> float | None:
        return None if self.put_prev_oi is None else self.put_oi - self.put_prev_oi


@dataclass
class Chain:
    underlying_key: str
    expiry: str
    spot: float
    fetched_at: datetime
    rows: list[StrikeRow] = field(default_factory=list)


@dataclass
class Quote:
    key: str
    last_price: float
    last_trade_time: datetime | None     # exchange time of the last trade (freshness)
    fetched_at: datetime                 # when we received it
    bid: float | None = None
    ask: float | None = None
    bid_qty: float | None = None
    ask_qty: float | None = None
    volume: float | None = None
    oi: float | None = None
    prev_close: float | None = None      # official previous-session close (last_price - net_change)
    day_open: float | None = None        # today's open / high / low (quote "ohlc")
    day_high: float | None = None
    day_low: float | None = None

    def age_s(self, now: datetime) -> float:
        ref = self.last_trade_time or self.fetched_at
        return (now - ref).total_seconds()

    @property
    def spread(self) -> float | None:
        if self.bid and self.ask and self.ask >= self.bid:
            return self.ask - self.bid
        return None


@dataclass
class Future:
    underlying: str
    instrument_key: str
    expiry: date
    lot_size: int
    tick_size: float
    trading_symbol: str


class ProviderError(RuntimeError):
    pass


class TokenExpired(ProviderError):
    pass


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def _opt(x) -> float | None:
    """Optional non-negative number: None when absent/invalid, 0 kept as 0."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v >= 0 else None


def _ms_time(x) -> datetime | None:
    if x in (None, "", 0, "0"):
        return None
    try:
        return datetime.fromtimestamp(float(x) / 1000.0, timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        try:
            return datetime.fromisoformat(str(x))
        except ValueError:
            return None


def parse_upstox_chain(payload: dict, underlying_key: str, fetched_at: datetime | None = None) -> Chain:
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise ProviderError(f"Upstox error: {payload.get('errors') if isinstance(payload, dict) else payload}")
    data = payload.get("data") or []
    if not data:
        raise ProviderError("empty option chain")
    rows: list[StrikeRow] = []
    for item in data:
        c = (item.get("call_options") or {})
        p = (item.get("put_options") or {})
        cm, pm = c.get("market_data") or {}, p.get("market_data") or {}
        cg, pg = c.get("option_greeks") or {}, p.get("option_greeks") or {}
        strike = _num(item.get("strike_price"))
        if strike is None:
            continue
        rows.append(StrikeRow(
            strike=strike,
            call_oi=_opt(cm.get("oi")) or 0.0, call_prev_oi=_opt(cm.get("prev_oi")),
            call_iv=_num(cg.get("iv")), call_ltp=_num(cm.get("ltp")), call_volume=_opt(cm.get("volume")) or 0.0,
            put_oi=_opt(pm.get("oi")) or 0.0, put_prev_oi=_opt(pm.get("prev_oi")),
            put_iv=_num(pg.get("iv")), put_ltp=_num(pm.get("ltp")), put_volume=_opt(pm.get("volume")) or 0.0,
            call_bid=_num(cm.get("bid_price")), call_ask=_num(cm.get("ask_price")),    # 0 = no bid/ask -> None
            put_bid=_num(pm.get("bid_price")), put_ask=_num(pm.get("ask_price")),
            call_key=str(c.get("instrument_key") or ""), put_key=str(p.get("instrument_key") or ""),
            call_delta=_finite(cg.get("delta")), put_delta=_finite(pg.get("delta")),
        ))
    spot = _num(data[0].get("underlying_spot_price"))
    if not rows or spot is None:
        raise ProviderError("option chain has no valid strikes or spot price")
    rows.sort(key=lambda r: r.strike)
    return Chain(underlying_key=underlying_key, expiry=str(data[0].get("expiry")), spot=spot,
                 fetched_at=fetched_at or datetime.now(timezone.utc), rows=rows)


def parse_upstox_quotes(payload: dict, fetched_at: datetime | None = None) -> dict[str, Quote]:
    """Full market quote response -> {instrument_key (pipe form): Quote}."""
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise ProviderError(f"Upstox quote error: {payload.get('errors') if isinstance(payload, dict) else payload}")
    now = fetched_at or datetime.now(timezone.utc)
    out: dict[str, Quote] = {}
    for colon_key, q in (payload.get("data") or {}).items():
        key = q.get("instrument_token") or colon_key.replace(":", "|", 1)
        lp = _num(q.get("last_price"))
        if lp is None:
            continue
        depth = q.get("depth") or {}
        buy = (depth.get("buy") or [{}])[0] or {}
        sell = (depth.get("sell") or [{}])[0] or {}
        out[key] = Quote(key=key, last_price=lp, last_trade_time=_ms_time(q.get("last_trade_time")), fetched_at=now,
                         bid=_num(buy.get("price")), ask=_num(sell.get("price")),
                         bid_qty=_opt(buy.get("quantity")), ask_qty=_opt(sell.get("quantity")),
                         volume=_opt(q.get("volume")), oi=_opt(q.get("oi")),
                         day_open=_num((q.get("ohlc") or {}).get("open")), day_high=_num((q.get("ohlc") or {}).get("high")),
                         day_low=_num((q.get("ohlc") or {}).get("low")),
                         prev_close=_num(lp - nc) if (nc := _finite(q.get("net_change"))) is not None else None)
    return out


def _finite(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def front_future(instruments: list[dict], underlying_symbol: str, today: date) -> Future:
    """Nearest-expiry FUT contract (expiry >= today) for the underlying: what TradingView's NIFTY1! tracks."""
    best = None
    for r in instruments:
        if r.get("segment") not in ("NSE_FO", "BSE_FO") or r.get("instrument_type") != "FUT":
            continue
        if str(r.get("underlying_symbol", "")).upper() != underlying_symbol.upper():
            continue
        try:
            exp = datetime.fromtimestamp(float(r["expiry"]) / 1000.0, IST).date()
        except (KeyError, TypeError, ValueError):
            continue
        if exp < today:
            continue
        if best is None or exp < best[0]:
            best = (exp, r)
    if best is None:
        raise ProviderError(f"no live futures contract found for {underlying_symbol}")
    exp, r = best
    # tick_size is stored exactly as the file gives it; its unit (rupees or paise) is not documented clearly,
    # so nothing in the bridge relies on it (costs use the configured per-index tick).
    return Future(underlying=underlying_symbol, instrument_key=r["instrument_key"], expiry=exp,
                  lot_size=int(r.get("lot_size") or 0), tick_size=float(r.get("tick_size") or 0),
                  trading_symbol=str(r.get("trading_symbol", "")))


class MarketProvider(ABC):
    @abstractmethod
    def expiries(self, underlying_key: str) -> list[str]:
        """All listed option expiries (YYYY-MM-DD) for the underlying."""

    @abstractmethod
    def chain(self, underlying_key: str, expiry: str) -> Chain:
        """Full option chain for one expiry."""

    @abstractmethod
    def quotes(self, keys: list[str]) -> dict[str, Quote]:
        """Full market quotes (last price, last trade time, best bid/ask) for instrument keys."""

    @abstractmethod
    def front_future(self, underlying: str, today: date) -> Future:
        """The live front-month futures contract."""

    def candles_5m(self, key: str, start: date, end: date, intraday: bool = False) -> list[list]:
        """5-minute candles [time, open, high, low, close, volume, oi]; intraday=True returns today's bars."""
        raise ProviderError("this data provider has no candle history")

    def equity_key(self, symbol: str) -> str | None:
        """NSE_EQ instrument key of an F&O stock (None when unknown)."""
        return None

    def fno_stocks(self, today: date) -> list[dict]:
        """F&O stocks: symbol, equity key, front-future key, lot size, tick (rupees)."""
        return []

    def nearest_expiry(self, underlying_key: str, today: date | None = None) -> str:
        today = today or datetime.now(IST).date()
        future = sorted(e for e in self.expiries(underlying_key) if e >= today.isoformat())
        if not future:
            raise ProviderError(f"no future expiries for {underlying_key}")
        return future[0]  # listed expiry dates already reflect holiday shifts


# Kept for older imports.
ChainProvider = MarketProvider


class UpstoxProvider(MarketProvider):
    """Upstox v2 REST: option contracts/chain, full market quotes, public instruments file."""

    def __init__(self, token_file: Path, min_interval_s: float = 0.5, client: httpx.Client | None = None,
                 instruments_cache: Path | None = None, instruments_url: str = INSTRUMENTS_URL):
        self.token_file = token_file
        self.min_interval_s = min_interval_s
        self.client = client or httpx.Client(base_url=UPSTOX_BASE, timeout=10.0)
        self.instruments_cache = instruments_cache
        self.instruments_url = instruments_url
        self._lock = threading.Lock()
        self._last_call = 0.0
        self._expiry_cache: dict[str, tuple[str, list[str]]] = {}
        self._fut_cache: dict[str, tuple[str, Future]] = {}

    def _token(self) -> str:
        if not self.token_file.is_file():
            raise TokenExpired("no Upstox token yet: run `bash start.sh` (it logs in)")
        try:
            info = json.loads(self.token_file.read_text())
            exp, tok = float(info["expires_at"]), str(info["access_token"])
        except (ValueError, KeyError, TypeError):
            raise TokenExpired("Upstox token file unreadable: log in again")
        if exp <= time.time():
            raise TokenExpired("Upstox token expired (they expire at 03:30 IST): log in again with `bash start.sh`")
        return tok

    def _get(self, path: str, params: dict) -> dict:
        with self._lock:  # gentle client-side rate limit
            wait = self.min_interval_s - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
        try:
            r = self.client.get(path, params=params, headers={
                "Accept": "application/json", "Authorization": f"Bearer {self._token()}"})
        except httpx.HTTPError as exc:   # timeouts, connection resets, DNS: never escape as raw httpx errors
            raise ProviderError(f"Upstox request failed: {type(exc).__name__}") from exc
        if r.status_code == 401:
            raise TokenExpired("Upstox rejected the token (401): log in again")
        if r.status_code >= 400:
            raise ProviderError(f"Upstox HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json()
        except ValueError as exc:
            raise ProviderError("Upstox returned invalid JSON") from exc

    def expiries(self, underlying_key: str) -> list[str]:
        today = datetime.now(IST).date().isoformat()
        cached = self._expiry_cache.get(underlying_key)
        if cached and cached[0] == today:
            return cached[1]
        payload = self._get("/option/contract", {"instrument_key": underlying_key})
        exp = sorted({str(c["expiry"]) for c in payload.get("data") or [] if c.get("expiry")})
        self._expiry_cache[underlying_key] = (today, exp)
        return exp

    def chain(self, underlying_key: str, expiry: str) -> Chain:
        payload = self._get("/option/chain", {"instrument_key": underlying_key, "expiry_date": expiry})
        return parse_upstox_chain(payload, underlying_key)

    def quotes(self, keys: list[str]) -> dict[str, Quote]:
        if not keys:
            return {}
        return parse_upstox_quotes(self._get("/market-quote/quotes", {"instrument_key": ",".join(keys)}))

    def _instruments(self) -> list[dict]:
        today = datetime.now(IST).date().isoformat()
        if self.instruments_cache and self.instruments_cache.is_file():
            cached = json.loads(self.instruments_cache.read_text())
            if cached.get("date") == today:
                return cached["rows"]
        rows = []
        for url in (self.instruments_url, BSE_INSTRUMENTS_URL):
            try:
                r = httpx.get(url, timeout=30.0)
                r.raise_for_status()
                rows += json.loads(gzip.decompress(r.content))
            except (httpx.HTTPError, OSError, ValueError) as exc:
                if url == self.instruments_url:
                    raise ProviderError(f"could not download the Upstox instruments file: {type(exc).__name__}") from exc
                # BSE file missing: everything except SENSEX still works
        futs = [x for x in rows if x.get("instrument_type") == "FUT"]   # keep the cache small
        if self.instruments_cache:
            self.instruments_cache.parent.mkdir(parents=True, exist_ok=True)
            self.instruments_cache.write_text(json.dumps({"date": today, "rows": futs}))
        return futs

    def front_future(self, underlying: str, today: date) -> Future:
        cached = self._fut_cache.get(underlying)
        if cached and cached[0] == today.isoformat():
            return cached[1]
        fut = front_future(self._instruments(), underlying, today)
        self._fut_cache[underlying] = (today.isoformat(), fut)
        return fut

    def equity_key(self, symbol: str) -> str | None:
        for r in self._instruments():
            if r.get("underlying_type") == "EQUITY" and str(r.get("underlying_symbol", "")).upper() == symbol.upper():
                return r.get("underlying_key")
        return None

    def fno_stocks(self, today: date) -> list[dict]:
        best: dict[str, dict] = {}
        for r in self._instruments():
            if r.get("underlying_type") != "EQUITY" or r.get("segment") != "NSE_FO":
                continue
            try:
                exp = datetime.fromtimestamp(float(r["expiry"]) / 1000.0, IST).date()
            except (KeyError, TypeError, ValueError):
                continue
            sym = str(r.get("underlying_symbol", "")).upper()
            if exp >= today and (sym not in best or exp < best[sym]["expiry"]):
                best[sym] = {"symbol": sym, "equity_key": r.get("underlying_key"), "fut_key": r["instrument_key"],
                             "lot": int(r.get("lot_size") or 0), "tick": float(r.get("tick_size") or 5) / 100,
                             "expiry": exp}
        return sorted(best.values(), key=lambda x: x["symbol"])

    def candles_5m(self, key: str, start: date, end: date, intraday: bool = False, minutes: int = 5) -> list[list]:
        """Upstox v3 candles (5-minute unless `minutes` says otherwise, e.g. 3). Historical requests are split into
        calendar months (the API limit for minute data)."""
        base = "https://api.upstox.com/v3/historical-candle"
        if intraday:
            data = self._get(f"{base}/intraday/{key}/minutes/{int(minutes)}", {})
            return list(((data or {}).get("data") or {}).get("candles") or [])
        rows, a = [], start
        while a <= end:
            month_end = (date(a.year + (a.month == 12), a.month % 12 + 1, 1) - timedelta(days=1))
            b = min(month_end, end)
            data = self._get(f"{base}/{key}/minutes/{int(minutes)}/{b.isoformat()}/{a.isoformat()}", {})
            rows += list(((data or {}).get("data") or {}).get("candles") or [])
            a = b + timedelta(days=1)
        return rows


class FileProvider(MarketProvider):
    """Offline demo provider: an Upstox-format chain JSON, and quotes synthesised from its spot price."""

    def __init__(self, path: Path, basis: float = 0.0):
        self.path = path
        self.basis = basis

    def _payload(self) -> dict:
        return json.loads(self.path.read_text())

    def expiries(self, underlying_key: str) -> list[str]:
        return [str(self._payload()["data"][0]["expiry"])]

    def chain(self, underlying_key: str, expiry: str) -> Chain:
        return parse_upstox_chain(self._payload(), underlying_key)

    def quotes(self, keys: list[str]) -> dict[str, Quote]:
        spot = float(self._payload()["data"][0]["underlying_spot_price"])
        now = datetime.now(timezone.utc)
        out = {}
        for k in keys:
            px = spot + (self.basis if k.startswith("NSE_FO") else 0.0)
            out[k] = Quote(k, px, now, now, bid=px - 0.1, ask=px + 0.1)
        return out

    def front_future(self, underlying: str, today: date) -> Future:
        return Future(underlying, f"NSE_FO|DEMO-{underlying}", today, 65, 0.1, f"{underlying} FUT DEMO")
