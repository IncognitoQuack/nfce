"""Bridge core: market data, signal intake, veto/boost, paper books, risk gate, health. Alerts only, no orders.

Design rules (from the independent reviews):
* every TradingView payload is written to a durable inbox before anything else, and deduplicated by signal id;
* no executable paper entry without a fresh front-month futures quote, an acceptable spread, a recent alert and
  the risk gate's permission; "do nothing" is the normal outcome and each block is logged with its reason;
* strikes are compared with the LIVE futures-minus-spot basis; without it the signal is UNCHECKED, never PASS;
* one failing request never kills a worker: every iteration is isolated, and /health reports worker heartbeats.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import threading
from datetime import date, datetime, timedelta, timezone

from .analytics import Summary, summarize
from .config import Settings
from .evidence import Card, assess, drift, load_table
from .range_model import DECISION_BAR_STARTS, INDEX_KEYS, Forecast, RangeError, RangeForecaster, r4_targets
from .paper import LOT as LOT_UNITS, TICK, PaperBook, PaperTrade
from .providers import IST, MarketProvider, ProviderError, Quote, TokenExpired
from .risk import RiskGate, market_open
from .options import OptionBook, pick_leg
from .rules import Decision, Signal, SignalError, evaluate
from .store import Store

log = logging.getLogger("nfce.bridge")

HELP = (
    "NFCE bridge (alerts only, never places orders)\n"
    "/status [NIFTY|BANKNIFTY]: option-chain and futures summary\n"
    "/check BUY|SELL entry sl [t1] [NIFTY|BANKNIFTY]: check levels by hand (analysis only, no paper trade)\n"
    "/paper: paper-trading results (executable vs theoretical, taken vs vetoed)\n"
    "/health: data and worker health\n"
    "/trust: what the evidence says about these signals, and live vs tested results\n"
    "/range: live scorecard of the next-hour range forecasts (R6)\n"
    "/scan: F&O gainers, losers and volume surges right now (analysis only)\n"
    "/options: option-leg paper results\n"
    "/account: the paper accounts (equity, cash, today, open positions)\n"
    "/ledger: every account fill as a CSV file\n"
    "/halt, /resume: stop / allow new executable paper entries"
)


def _event_list(x) -> list[str]:
    """Event text(s) from an alert: a list, a single value, or nothing. FIX (fuzz): a number used to crash iteration."""
    if x is None or x == "" or x == []:
        return []
    items = x if isinstance(x, list) else [x]
    return [str(e)[:300] for e in items[:20] if e is not None and str(e).strip()]


def symbol_root(symbol: str) -> str:
    """'NSE:NIFTY1!' -> 'NIFTY', 'BANKNIFTY' -> 'BANKNIFTY'."""
    s = symbol.split(":")[-1].upper()
    return re.sub(r"\d*!$", "", s)


def signal_id(payload: dict) -> str:
    """The indicator's own id when present, otherwise a content fingerprint (same alert twice = same id)."""
    if isinstance(payload, dict) and payload.get("id"):
        return str(payload["id"])[:80]
    core = {k: (payload.get(k) if isinstance(payload, dict) else None)
            for k in ("symbol", "tf", "side", "entry", "sl", "t1", "t", "event", "events")}
    return "h:" + hashlib.sha256(json.dumps(core, sort_keys=True, default=str).encode()).hexdigest()[:24]


def _fmt(x, d=2):
    if x is None:
        return "n/a"
    if isinstance(x, float) and math.isinf(x):
        return "inf"
    return f"{x:,.{d}f}"


def _age(iso: str | None, now: datetime) -> float:
    return math.inf if not iso else (now - datetime.fromisoformat(iso)).total_seconds()


class Bridge:
    def __init__(self, settings: Settings, provider: MarketProvider, store: Store, telegram, clock=None):
        self.s = settings
        self.provider = provider
        self.store = store
        self.tg = telegram
        raw_send = telegram.send

        def logged_send(text: str, html: bool = False, **kw) -> bool:    # every message is kept, so it can be shown later
            ok = raw_send(text, html=html, **kw) if (html or kw) else raw_send(text)
            try:
                store.add_sent(text, bool(ok))
            except Exception:
                log.exception("could not log a sent message")
            return ok
        telegram.send = logged_send
        self.clock = clock or (lambda: datetime.now(IST))
        from .bot import Bot
        self.bot = Bot(self)                  # roles, plain-English questions, admin control, unattended jobs
        v = store.kv_get("set_stock_signal_risk")
        if v is not None:                     # an admin /set survives restarts
            settings.stock_signal_risk = float(v)
        self.paper = PaperBook(store)
        self.risk = RiskGate(settings, store, self.paper)
        self._lock = threading.RLock()
        self._entry_lock = threading.RLock()    # FIX (H03): risk check + position check + insert are one step
        self._band: dict[str, tuple[date, float, float]] = {}    # the session's spot range, for the option recorder
        self._contracts_seen: set[tuple[str, str]] = set()
        self._chain: dict[str, tuple[datetime, Summary, int]] = {}
        self._quotes: dict[str, tuple[datetime, Quote | None, Quote | None]] = {}
        self.health: dict = {"poll_beat": None, "tg_beat": None, "quote_ok": None, "chain_ok": None, "last_error": None,
                             "quote_ok_by": {}, "chain_ok_by": {}}
        self._token_warned = False
        self.evidence = load_table()      # shipped with the code; a missing or broken table is a startup error
        self.ranger = RangeForecaster(provider, clock=self.clock)   # R4; any failure only disables R4 for that signal
        self.options = OptionBook(store, provider)
        self._legs: dict = {}                                      # signal id -> (option leg, paper opened?)
        self.stock_futures: dict[str, str] = {}                    # scanner symbol -> its future's instrument key
        self.engine = None
        if settings.engine_underlyings:
            from .live_engine import LiveEngine
            self.engine = LiveEngine(self, settings.engine_underlyings, tuple(settings.engine_timeframes))
        self.accounts = []
        if settings.accounts or settings.account_capital > 0:
            from .account import Account
            for i, (name, cap) in enumerate((settings.accounts or {"2L": settings.account_capital}).items()):
                self.accounts.append(Account(self, cap, settings.account_risk_pct, settings.account_daily_loss_pct,
                                             settings.account_max_open, name=name,
                                             strategy=settings.account_strategies.get(name, "base"), quiet=i > 0))
        self.account = self.accounts[0] if self.accounts else None
        self._acct_notes: dict = {}
        self.stocks = None
        if settings.stock_engine:
            from .stock_engine import StockEngine
            self.stocks = StockEngine(self)
        self.scanner = None
        if settings.scanner:
            from .scanner import Scanner
            self.scanner = Scanner(self)
        self.gs = None                        # GS research engine (bridge/gs_live.py): paper, own book, off by default
        if settings.gs and self.stocks is not None:
            try:
                from .gs_live import GSLive
                self.gs = GSLive(self, settings.gs_db)
            except Exception:                 # GS can never stop the bridge from starting
                log.exception("GS engine could not start; the bridge runs without it")

    def now(self) -> datetime:
        return self.clock().astimezone(IST)

    # ---------- error isolation ----------
    def _safe(self, fn, what: str):
        try:
            return fn()
        except TokenExpired as exc:
            self._error(f"{what}: {exc}", token=True)
        except (ProviderError, ValueError, KeyError, OSError) as exc:
            self._error(f"{what}: {type(exc).__name__}: {exc}")
        except Exception as exc:   # never let one bad response kill a worker
            log.exception("unexpected error in %s", what)
            self._error(f"{what}: unexpected {type(exc).__name__}")
        return None

    def _error(self, msg: str, token: bool = False) -> None:
        self.health["last_error"] = f"{self.now():%H:%M:%S} {msg}"
        log.warning(msg)
        bot = getattr(self, "bot", None)
        if bot:
            bot.note_error(msg)
        if token and not self._token_warned:
            self._token_warned = True
            (bot.admin if bot else self.tg.send)("⚠️ " + msg + "\nSign in from your phone with /login.")

    # ---------- market data ----------
    def keys(self, root: str) -> tuple[str, str]:
        spot = self.s.underlyings.get(root)
        fsym = self.s.futures_symbol.get(root)
        if not spot or not fsym:
            raise ProviderError(f"unknown underlying {root!r}")
        fut = self.provider.front_future(fsym, self.now().date())
        tag = (fut.instrument_key, self.now().date().isoformat())
        if tag not in self._contracts_seen:                       # FIX (H08): which contract was "front" each day
            self.store.add_contract(fut.instrument_key, root, fut.expiry.isoformat(), fut.lot_size, tag[1])
            self._contracts_seen.add(tag)
        return fut.instrument_key, spot

    def _fresh(self, q: Quote | None, now: datetime, exchange_time: bool = True) -> bool:
        """FIX (H05): a futures quote is fresh only with an exchange last-trade time; receipt time proves nothing about
        the market. exchange_time=False (spot index, used for the basis only) falls back to the receipt time."""
        if q is None:
            return False
        if exchange_time and q.last_trade_time is None:
            return False
        return -self.s.max_clock_skew_s <= q.age_s(now) <= self.s.max_quote_age_s

    def refresh_quotes(self, root: str) -> tuple[Quote | None, Quote | None]:
        fkey, skey = self.keys(root)
        qs = self.provider.quotes([fkey, skey])
        fq, sq = qs.get(fkey), qs.get(skey)
        now = self.now()
        with self._lock:
            self._quotes[root] = (now, fq, sq)
        for q in (fq, sq):
            if q is not None:
                self.store.add_quote(q)
        if self._fresh(fq, now):
            self.health["quote_ok"] = now.isoformat()
            self.health["quote_ok_by"][root] = now.isoformat()
            self._token_warned = False
            self._update_paper(root, fq, now)
        else:
            self._error(f"quotes {root}: futures quote stale or missing (frozen feed, holiday or after hours)")
        return fq, sq

    def fresh_quotes(self, root: str) -> tuple[Quote | None, Quote | None]:
        now = self.now()
        with self._lock:
            cached = self._quotes.get(root)
        if not cached or (now - cached[0]).total_seconds() >= self.s.quote_seconds:
            got = self._safe(lambda: self.refresh_quotes(root), f"quotes {root}")
            if got is None:
                return None, None
            fq, sq = got
        else:
            _, fq, sq = cached
        return (fq if self._fresh(fq, now) else None), (sq if self._fresh(sq, now, exchange_time=False) else None)

    def _spot_band(self, root: str, spot: float) -> tuple[float, float]:
        today = self.now().date()
        with self._lock:
            b = self._band.get(root)
            lo, hi = (min(b[1], spot), max(b[2], spot)) if b and b[0] == today else (spot, spot)
            self._band[root] = (today, lo, hi)
        return lo, hi

    def _record_rows(self, chain, lo: float, hi: float) -> list:
        """FIX (H07): every strike within `window` strikes of ANY spot seen today, so a contract chosen earlier in the
        session (e.g. the ITM strike of an R1 trade) is still recorded after a large move."""
        ks = sorted(r.strike for r in chain.rows)
        step = min((b - a for a, b in zip(ks, ks[1:]) if b > a), default=0.0)
        pad = self.s.window * step
        return [r for r in chain.rows if lo - pad <= r.strike <= hi + pad]

    def refresh_chain(self, root: str) -> tuple[Summary, int]:
        key = self.s.underlyings.get(root)
        if not key:
            raise ProviderError(f"unknown underlying {root!r}")
        today = self.now().date()
        exps = sorted(e for e in self.provider.expiries(key) if e >= today.isoformat())
        if not exps:
            raise ProviderError(f"no future expiries for {key}")
        chain = self.provider.chain(key, exps[0])
        summ = summarize(chain, self.s.window, self.s.pcr_doi_veto)
        snap_id = self.store.add_snapshot(summ)
        lo, hi = self._spot_band(root, chain.spot)
        self.store.add_option_rows(chain, snap_id, self._record_rows(chain, lo, hi))
        # FIX (H07): R1 trades the nearest expiry with >= 2 sessions left; near expiry, also record the next one
        if len(exps) > 1 and (date.fromisoformat(exps[0]) - today).days <= 2:
            nxt = self._safe(lambda: self.provider.chain(key, exps[1]), f"chain {root} next expiry")
            if nxt is not None:
                self.store.add_option_rows(nxt, None, self._record_rows(nxt, lo, hi))
        now = self.now()
        with self._lock:
            self._chain[root] = (now, summ, snap_id)
        self.health["chain_ok"] = now.isoformat()
        self.health["chain_ok_by"][root] = now.isoformat()
        return summ, snap_id

    def chain_for(self, root: str) -> tuple[Summary | None, int | None]:
        now = self.now()
        with self._lock:
            cached = self._chain.get(root)
        if cached and (now - cached[0]).total_seconds() < self.s.poll_seconds:
            return cached[1], cached[2]
        got = self._safe(lambda: self.refresh_chain(root), f"chain {root}")
        if got:
            return got
        if cached and (now - cached[0]).total_seconds() <= self.s.max_chain_age_s:
            return cached[1], cached[2]
        return None, None

    def _update_paper(self, root: str, fq: Quote, now: datetime) -> None:
        hh, mm = divmod(self.s.square_off_hhmm, 100)
        for t in self.paper.on_quote(root, fq, now, self.s.max_gap_s, self.s.extra_slippage_ticks, hh * 60 + mm):
            if t.book in ("executable", "scanner"):
                self.options.request_close(t.sid, t.book, t.exit_reason)
            r = t.net_pts() / t.R if t.R else 0.0
            if t.book == "theoretical":                            # the model book is in the daily report only
                continue
            from . import human
            reason = ("data gap, result not counted" if t.status == "UNRESOLVED" else t.exit_reason)
            self.tg.send(human.closed(root, t.side, t.book, reason, r, t.net_pts() * t.units), html=True)

    # ---------- intake ----------
    def accept(self, payload: dict, source: str) -> tuple[int | None, bool]:
        """Write the raw payload to the durable inbox. Returns (inbox id, duplicate?)."""
        return self.store.inbox_add(source, payload, signal_id(payload))

    def process(self, inbox_id: int | None, payload: dict, source: str, received: datetime | None = None) -> str:
        received = (received or self.now()).astimezone(IST)
        try:
            if isinstance(payload, dict) and ("events" in payload or "event" in payload):
                text = self._event(payload, source)
            else:
                text = self._signal(payload, source, received)
            status = "DONE"
        except SignalError as exc:
            text, status = f"⚠️ Alert rejected: {exc}", "REJECTED"
            self.tg.send(text)
        except Exception as exc:      # recorded, never silently lost
            log.exception("processing failed")
            text, status = f"⚠️ Alert could not be processed ({type(exc).__name__}); it is kept in the inbox", "ERROR"
            self.tg.send(text)
        if inbox_id is not None:
            self.store.inbox_done(inbox_id, status, text[:300])
        return text

    def handle_payload(self, payload: dict, source: str) -> str:
        inbox_id, dup = self.accept(payload, source)
        if dup:
            return "duplicate alert ignored"
        return self.process(inbox_id, payload, source)

    def recover_inbox(self) -> int:
        """Process alerts that were accepted but not processed (e.g. the bridge stopped mid-way)."""
        n = 0
        for inbox_id, source, raw, received in self.store.inbox_pending():
            self.process(inbox_id, json.loads(raw), source, datetime.fromisoformat(received))
            n += 1
        return n

    def _event(self, payload: dict, source: str) -> str:
        self.store.add_event(source, payload)
        evs = _event_list(payload.get("events")) or _event_list(payload.get("event")) or ["(event without text)"]
        flat = payload.get("pos") == 0 or any(re.search(r"exit|square-off", str(e), re.I) for e in evs)
        tail = f" | SL now {payload['sl']}" if payload.get("sl") is not None and not flat else ""
        text = f"ℹ️ {symbol_root(str(payload.get('symbol', '')))} {payload.get('tf', '')}: " + "; ".join(map(str, evs)) + tail
        self.tg.send(text)
        return text

    def _signal(self, payload: dict, source: str, received: datetime) -> str:
        sig = Signal.from_payload(payload)
        if not sig.sid:
            sig.sid = signal_id(payload)
        root = symbol_root(sig.symbol or "NIFTY")
        if root not in self.s.underlyings:
            raise SignalError(f"unknown underlying {root!r}")
        prev = ""
        closed = payload.get("closed")
        cevs = _event_list(closed.get("events")) if isinstance(closed, dict) else []
        if cevs:                                                   # the previous trade's exit on this same bar
            self.store.add_event(source, {"v": payload.get("v"), "kind": "event", "id": closed.get("id"), "pos": 0,
                                          "symbol": payload.get("symbol"), "tf": payload.get("tf"), "events": cevs})
            prev = f"ℹ️ previous trade {closed.get('id')}: " + "; ".join(cevs) + "\n"
        delay = None
        if sig.bar_time_ms:
            delay = (received - datetime.fromtimestamp(sig.bar_time_ms / 1000, timezone.utc)).total_seconds()
        summ, snap_id = self.chain_for(root)
        fq, sq = self.fresh_quotes(root)
        basis = (fq.last_price - sq.last_price) if (fq and sq) else None
        blocked, dom_note = None, ""
        if sig.domain == "spot":                                   # FIX (H12): one price domain for everything
            if basis is None:
                blocked = "levels are SPOT prices and the live futures-spot basis is unavailable"
                dom_note = "⚠️ Levels are spot-chart prices; no live basis, so no paper trade"
            else:
                sig = sig.to_futures(basis)
                dom_note = f"Levels are spot-chart prices, moved to futures with the live basis {basis:+.1f}"
        dec = evaluate(sig, summ, basis, self.s.pcr_doi_veto)
        self.store.add_signal(source, payload, sig, dec, snap_id, basis, delay)
        bar_close = datetime.fromtimestamp(sig.bar_time_ms / 1000, timezone.utc) if sig.bar_time_ms else None
        card = assess(self.evidence, sig, root, bar_close or received, received)
        self.store.add_evidence(sig.sid, card)
        fc, fc_note = self.range_forecast(root, received)
        if source in ("tradingview", "engine"):
            notes = self._open_books(sig, dec, root, received, delay, fc, fc_note, blocked, bar_close)
        else:
            notes = ["analysis only (manual check): no paper trade"]
        if self.s.option_legs and blocked is None:
            entered = self.paper.find_open(sig.sid, "executable") is not None
            spot = sq.last_price if sq else sig.entry
            notes.append(self.option_leg(sig.sid, "executable", root, self.s.underlyings[root], spot,
                                         1 if sig.side == "BUY" else -1, sig.entry, (sig.sl, sig.t1, sig.t2, sig.t3),
                                         LOT_UNITS.get(root, 1), sig.R, self.now(), open_paper=entered))
        if self.accounts and blocked is None and source in ("tradingview", "engine") and sq is not None:
            leg, _ = self._legs.get(sig.sid, (None, False))
            s_ = 1 if sig.side == "BUY" else -1
            got = []
            for acct in self.accounts:
                note = self._safe(lambda a=acct: a.consider(
                    self.now(), sig.sid, leg, self.s.underlyings[root], s_, [sig.sl, sig.t1, sig.t2, sig.t3],
                    sq.last_price - sig.entry, f"{root} {sig.tf}m signal"), f"account {acct.name}")
                if note:
                    got.append(note)
            if got:
                notes += got
                self._acct_notes[sig.sid] = "\n".join(got)
        if source == "engine":
            notes.insert(0, "Source: NFCE engine on live Upstox futures candles (same rules as the TradingView strategy)"
                         + (". ⚠️ 3-minute timeframe: NEVER tested historically" if sig.tf == "3" else ""))
        if dom_note:
            notes.insert(0, dom_note)
        text = (prev + self.format_signal(sig, dec, summ, basis, delay, card) + "\n"
                + (fc.line() if fc else f"Range forecast unavailable: {fc_note}") + "\n" + "\n".join(notes))
        try:
            self.tg.send(self.human_signal(sig, dec, root, card, fc, source, bar_close or received), html=True)
        except Exception:                                          # the plain text is the fallback, never silence
            log.exception("human message failed")
            self.tg.send(text)
        return text

    def human_signal(self, sig: Signal, dec: Decision, root: str, card, fc, source: str, when: datetime) -> str:
        from . import human
        s = 1 if sig.side == "BUY" else -1
        leg, opened = self._legs.get(sig.sid, (None, False))
        ex = self.paper.find_open(sig.sid, "executable")
        if ex is not None:
            paper = f"Paper: {ex.lots} lots {'bought' if s > 0 else 'sold'} at {human.px(ex.entry)}" + \
                    (", option bought at the ask" if opened else "")
        elif source in ("tradingview", "engine"):
            with self.store._lock:
                row = self.store.db.execute("SELECT exit_reason FROM paper_trades WHERE sid=? AND book='executable'",
                                            (sig.sid,)).fetchone()
            paper = f"Paper: not entered ({row[0]})" if row and row[0] else ""
        else:
            paper = "Manual check: no paper trade"
        c = card.cell if card else {}
        evidence = (f"{c.get('n', 0)} similar past trades: {c.get('win', 0) * 100:.0f}% winners, "
                    f"{c.get('net_r', 0):+.2f}R per trade after costs") if c else "no evidence table"
        chain = {"PASS": "Option chain: OK", "VETO": "Option chain: AGAINST (veto)", "NO_DATA": "Option chain: not checked"}
        rng = f"Next-hour range ~{fc.m50:.0f} pts (80%: {fc.l10:.0f}–{fc.u90:.0f})" if fc else ""
        acct = self._acct_notes.get(sig.sid)
        if acct:
            paper = (paper + "\n" if paper else "") + acct
        return human.signal(root, s, sig.tf, when.astimezone(IST).strftime("%H:%M"), sig.entry, sig.sl, sig.t1, sig.t2,
                            sig.t3, trust=card.trust if card else "NO EDGE", evidence=evidence,
                            chain=chain.get(dec.action, ""), leg=leg, leg_note=(leg.note if leg is not None else ""),
                            paper=paper, range_pts=rng,
                            source={"engine": "engine signal", "tradingview": "TradingView alert"}.get(source, "manual check"),
                            untested_tf=sig.tf == "3")

    def option_leg(self, sid: str, book: str, underlying: str, spot_key: str, spot: float, side: int, entry: float,
                   levels: tuple, units: int, r_pts: float, now: datetime, short: bool = False,
                   open_paper: bool = True) -> str:
        """The 1-ITM option to buy for this signal (see options.py); opened in the options paper book when the
        underlying's paper trade opened. Never raises."""
        try:
            leg = pick_leg(self.provider, spot_key, underlying, spot, side, entry, levels[0], levels[1:], units,
                           self.now().date())
        except ProviderError as exc:
            return f"Option leg unavailable: {exc}"[:200]
        except Exception as exc:
            log.exception("option leg failed")
            return f"Option leg unavailable: {type(exc).__name__}"
        opened = open_paper and self.options.open(sid, book, leg, r_pts, now)
        self._legs[sid] = (leg, opened)
        if short:
            if leg.note:
                return f"{leg.strike:g}{leg.typ}: {leg.note}"
            return (f"{leg.strike:g}{leg.typ} {leg.expiry[5:]} ask {leg.ask:.2f} SL {leg.sl:.2f} T1 {leg.t1:.2f} "
                    f"T2 {leg.t2:.2f} T3 {leg.t3:.2f}" + (" (paper)" if opened else ""))
        return leg.line() + (" | paper: bought at the ask" if opened else "")

    def range_forecast(self, root: str, now: datetime) -> tuple[Forecast | None, str]:
        """R4 forecast for the signal's index; never raises (a failure only means no R4 trade for this signal)."""
        try:
            nifty = self.s.underlyings.get("NIFTY", "")
            expiry_today = self.provider.nearest_expiry(nifty, now.date()) == now.date().isoformat() if nifty else False
        except Exception:                                          # expiry unknown: treat as a normal day
            expiry_today = False
        try:
            return self.ranger.forecast(root, now, expiry_today), ""
        except (RangeError, ProviderError) as exc:
            return None, str(exc)[:160]
        except Exception as exc:                                   # never let R4 break a signal
            log.exception("range forecast failed")
            return None, f"{type(exc).__name__}"

    def _open_r4(self, base: dict, px: float, s: int, root: str, fc: Forecast | None, fc_note: str) -> str:
        """R4 book: same entry, stop and exits as the executable book; only the targets come from the range forecast.
        R4 trades are independent PAIRED shadow trials (REGISTRY R4 amendment): one can still be open when the next
        executable trade opens. They measure target choice, not the returns of a one-position strategy."""
        if fc is None:
            self.paper.reject(PaperTrade(book="r4", entry=px, **base), f"no range forecast: {fc_note}"[:200])
            return f"r4 book: NOT entered (no range forecast: {fc_note})"
        try:
            t1, t2, t3 = r4_targets(px, s, fc, TICK.get(root, 0.1))
        except ValueError:
            self.paper.reject(PaperTrade(book="r4", entry=px, **base), "r4: degenerate targets")
            return "r4 book: NOT entered (degenerate targets)"
        ok = self.paper.open_trade(PaperTrade(book="r4", entry=px, **{**base, "t1": t1, "t2": t2, "t3": t3}))
        return (f"r4 book: entered at {px:.1f} with range targets T1 {t1:.1f} T2 {t2:.1f} T3 {t3:.1f}" if ok
                else "r4 book: duplicate id, ignored")

    # ---------- R6: live forward benchmark of the range forecasts ----------
    def record_range_forecasts(self, now: datetime) -> int:
        """Every decision bar (closes 09:45, 10:00 .. 14:15): store M1, HAR+VIX and their average for each index."""
        n = 0
        for root in INDEX_KEYS:
            if root not in self.s.underlyings:
                continue
            fc, _ = self.range_forecast(root, now)
            if fc is None or not fc.logq:
                continue
            start = fc.bar_close.astimezone(IST) - timedelta(minutes=5)
            if start.hour * 60 + start.minute not in DECISION_BAR_STARTS:
                continue
            fcs = {"M1": fc.logq}
            if fc.har_logq:
                fcs["HAR"] = fc.har_logq
                fcs["ENS"] = tuple((a + b) / 2 for a, b in zip(fc.logq, fc.har_logq))
            for model, q in fcs.items():
                n += self.store.add_range_forecast(root, fc.bar_close.isoformat(), model, now.isoformat(), fc.price, q)
        return n

    def score_range_forecasts(self, now: datetime) -> int:
        n = 0
        for root, bar_close in self.store.unscored_forecasts():
            t = datetime.fromisoformat(bar_close)
            if (now - t).total_seconds() < 3600 or t.astimezone(IST).date() != now.astimezone(IST).date():
                continue
            try:
                v = self.ranger.realized(root, t, now)
            except Exception:
                v = None
            if v is not None:
                self.store.set_realized(root, bar_close, v)
                n += 1
        return n

    def range_report(self) -> str:
        rows = self.store.scored_forecasts()
        if not rows:
            return "R6 range scorecard: no scored forecasts yet (each is scored 60 minutes after it is made)."
        out = ["R6 live range scorecard (next-hour range, log scale; lower pinball = better; band = 10-90%, aim 80%):"]
        for root in sorted({r[0] for r in rows}):
            for model in ("M1", "HAR", "ENS"):
                g = [r for r in rows if r[0] == root and r[2] == model]
                if not g:
                    continue
                pin = sum(sum(max(q * (y - p), (q - 1) * (y - p)) for q, p in zip((0.1, 0.5, 0.9), (a, b, c)))
                          for _, _, _, a, b, c, y in g) / (3 * len(g))
                cov = sum(a <= y <= c for _, _, _, a, b, c, y in g) / len(g)
                days = len({r[1][:10] for r in g})
                out.append(f"• {root} {model}: n={len(g)} ({days} sessions) pinball {pin:.4f}, inside band {cov:.0%}")
        out.append("Registered judgement (REGISTRY R6) only after >= 40 sessions; until then this is a progress report.")
        return "\n".join(out)

    def r4_report(self) -> str:
        with self.store._lock:
            rows = self.store.db.execute(
                "SELECT e.sid, e.net_pts / e.r_pts, r.net_pts / r.r_pts FROM paper_trades e JOIN paper_trades r "
                "ON e.sid = r.sid AND e.book = 'executable' AND r.book = 'r4' "
                "WHERE e.status = 'CLOSED' AND r.status = 'CLOSED' AND e.r_pts > 0 AND r.r_pts > 0").fetchall()
        d = [r4 - ex for _, ex, r4 in rows]
        if not d:
            return "R4 (range-calibrated targets vs fixed targets): 0 paired closed trades yet."
        m = sum(d) / len(d)
        sd = math.sqrt(sum((x - m) ** 2 for x in d) / (len(d) - 1)) if len(d) > 1 else 0.0
        t = m / (sd / math.sqrt(len(d))) if sd > 0 else 0.0
        return (f"R4 (range-calibrated targets vs fixed targets): {len(d)} paired trades, mean difference {m:+.3f}R "
                f"(t {t:+.2f}). Registered pass bar: >= +0.05R, one-sided p < 0.0125, >= 100 pairs.")

    def _open_books(self, sig: Signal, dec: Decision, root: str, received: datetime, delay: float | None,
                    fc: Forecast | None = None, fc_note: str = "", blocked: str | None = None,
                    bar_close: datetime | None = None) -> list[str]:
        s = 1 if sig.side == "BUY" else -1
        base = dict(underlying=root, tf=sig.tf, decision=dec.action, grade=dec.grade_out, side=s, sl=sig.sl,
                    t1=sig.t1, t2=sig.t2, t3=sig.t3, sid=sig.sid, signal_R=sig.R, lots=self.s.paper_lots,
                    received=received.isoformat())
        notes = []
        with self._entry_lock:          # FIX (H03): no second entry can slip between the checks and the insert
            now = self.now()
            th = PaperTrade(book="theoretical", entry=sig.entry, opened=now.isoformat(), **base)
            if blocked:
                self.paper.reject(th, blocked)
                notes.append(f"theoretical book: NOT entered ({blocked})")
            elif self.paper.has_open(root, sig.tf, "theoretical"):
                notes.append("theoretical book: skipped (a position is already open)")
            else:
                ok = self.paper.open_trade(th)
                notes.append("theoretical book: opened at the signal price" if ok else "theoretical book: duplicate id, ignored")
            reason, px, fq = blocked, None, None
            if reason is None:
                ok, why = self.risk.check(now)
                if not ok:
                    reason = why
                elif self.paper.has_open(root, sig.tf, "executable"):
                    reason = "a position is already open"
                elif delay is None or bar_close is None:
                    reason = "alert has no bar time, so its age is unknown"
                elif delay < -self.s.max_clock_skew_s:                         # FIX (M01)
                    reason = f"bar time is {-delay:.0f}s in the future (clock problem)"
            if reason is None:
                # FIX (H04): fetch the quote NOW and judge every age at the moment of the entry decision
                got = self._safe(lambda: self.refresh_quotes(root), f"quotes {root}")
                now = self.now()
                fq = got[0] if got and self._fresh(got[0], now) else None
                age = (now - bar_close).total_seconds()
                if age > self.s.max_signal_delay_s:
                    reason = f"entry decision {age:.0f}s after the bar closed (max {self.s.max_signal_delay_s}s)"
                elif fq is None:
                    reason = "no fresh futures quote with an exchange timestamp"
                elif fq.spread is None:
                    reason = "no bid/ask in the quote"
                elif fq.spread > self.s.max_spread_pts.get(root, 3.0):
                    reason = f"spread {fq.spread:.1f} pts above the {self.s.max_spread_pts.get(root, 3.0)} limit"
            if reason is None:
                px = (fq.ask if s > 0 else fq.bid) + s * self.s.extra_slippage_ticks * TICK.get(root, 0.1)
                if (px - sig.sl) * s <= 0 or (sig.t1 - px) * s <= 0:
                    reason = f"price already beyond SL or T1 (would enter at {px:.1f})"
            if reason is None:
                t = PaperTrade(book="executable", entry=px, opened=now.isoformat(), **base)
                touch_qty = fq.ask_qty if s > 0 else fq.bid_qty
                if touch_qty is not None and touch_qty < t.units:
                    t.flags.append(f"touch_qty_{touch_qty:.0f}<{t.units}")
                ok = self.paper.open_trade(t)
                notes.append(f"executable book: entered {t.lots} lots at {px:.1f} ({'ask' if s > 0 else 'bid'} + "
                             f"{self.s.extra_slippage_ticks} ticks, decided {(now - bar_close).total_seconds():.0f}s "
                             f"after the bar)" if ok else "executable book: duplicate id, ignored")
                if ok:
                    notes.append(self._open_r4({**base, "opened": now.isoformat()}, px, s, root, fc, fc_note))
            else:
                self.paper.reject(PaperTrade(book="executable", entry=sig.entry, opened=now.isoformat(), **base), reason)
                notes.append(f"executable book: NOT entered ({reason})")
        return notes

    # ---------- formatting ----------
    def format_signal(self, sig: Signal, dec: Decision, s: Summary | None, basis: float | None,
                      delay: float | None, card: Card | None = None) -> str:
        chain = {"PASS": "✅ PASS", "VETO": "⛔ VETO", "NO_DATA": "⚠️ UNCHECKED"}[dec.action]
        grade = dec.grade_in if dec.grade_out == dec.grade_in else f"{dec.grade_in}→{dec.grade_out}"
        what = f"{symbol_root(sig.symbol or 'NIFTY')} {sig.side} {grade}" + (" (boosted)" if dec.boosted else "")
        lines = [
            # FIX (trust upgrade): the headline is the measured evidence for this class of signal; a green "PASS"
            # headline read like "trade this", although it only means the option chain did not object.
            f"{card.headline()}: {what}" if card else f"{chain}: {what}",
            f"Chain check: {chain}",
            f"Entry {_fmt(sig.entry, 1)}  SL {_fmt(sig.sl, 1)}  T1 {_fmt(sig.t1, 1)}"
            + (f"  T2 {_fmt(sig.t2, 1)}" if sig.t2 else "") + (f"  T3 {_fmt(sig.t3, 1)}" if sig.t3 else "")
            + (f" | {sig.tf}m" if sig.tf else "") + (f" score {sig.score:.0f}" if sig.score is not None else "")
            + (f" | fut OI: {sig.oi}" if sig.oi else "") + (f" | alert age {delay:.0f}s" if delay is not None else ""),
        ]
        if s is not None:
            lines.append(self.format_summary(s, basis))
        lines += [f"• {r}" for r in dec.reasons]
        if card:
            lines += card.lines(self.evidence.get("tradingview_futures"))
        lines.append("Alerts only. No order placed. Not a recommendation.")
        return "\n".join(lines)

    def live_record(self) -> list[float]:
        """Net R of closed executable paper trades (the closest thing to real results)."""
        with self.store._lock:
            rows = self.store.db.execute(
                "SELECT net_pts, r_pts FROM paper_trades WHERE book='executable' AND status='CLOSED' AND r_pts > 0"
            ).fetchall()
        return [n / r for n, r in rows]

    def trust_report(self) -> str:
        e = self.evidence
        a, tv = e["cells"]["all|all|all"], e.get("tradingview_futures") or {}
        m = e["cells"].get("morning|all|all", {})
        live = self.live_record()
        lines = ["What the evidence says (out-of-sample, after costs):",
                 f"• All signals: n={a['n']}, {a['win'] * 100:.0f}% winners, {a['net_r']:+.2f}R per trade "
                 f"[95% {a['ci'][0]:+.2f}..{a['ci'][1]:+.2f}] (before costs {a['gross_r']:+.2f}R)"]
        if m:
            lines.append(f"• Morning entries (to 11:15), mostly STOCK trades: n={m['n']}, before costs "
                         f"{m['gross_r']:+.2f}R, after costs {m['net_r']:+.2f}R")
        ic = e.get("index_cells") or {}
        for k, label in (("tv|all", "Index futures (TradingView), all"), ("tv|morning", "  morning"),
                         ("tv|later", "  after 11:15")):
            c = ic.get(k)
            if c:
                lines.append(f"• {label}: n={c['n']}, before costs {c['gross_r']:+.2f}R, after current costs "
                             f"{c['net_r']:+.2f}R [95% {c['ci'][0]:+.2f}..{c['ci'][1]:+.2f}]")
        if tv and not ic:
            lines.append(f"• TradingView futures runs: n={tv['n']}, {tv['net_r']:+.2f}R per trade")
        lines.append("• VALIDATED classes: " + (", ".join(e["validated_classes"]) or "none (no registered experiment has passed)"))
        lines.append(f"Source: {e['source']}")
        if not live:
            lines.append("Live record: no closed executable paper trades yet.")
        else:
            lines.append(f"Live record: {len(live)} closed executable paper trades, {sum(live) / len(live):+.2f}R per trade.")
            lines.append(drift(tv or a, live) or "Live results are inside the tested range (or too few to judge).")
        return "\n".join(lines)

    def format_summary(self, s: Summary, basis: float | None = None) -> str:
        div, note = self.store.iv_change(s.underlying_key, s.fetched_at)
        age = (self.now() - datetime.fromisoformat(s.fetched_at)).total_seconds()
        b = f" | futures−spot {basis:+.1f}" if basis is not None else " | futures quote n/a"
        return (f"Chain exp {s.expiry} | spot {_fmt(s.spot, 1)}{b} | ATM {s.atm_strike:g}\n"
                f"PCR OI {_fmt(s.pcr_oi)} | ΔOI flow {s.flow} | call wall {s.max_call_oi_strike:g} | "
                f"put wall {s.max_put_oi_strike:g} | max pain {s.max_pain:g}\n"
                f"ATM IV {_fmt(s.atm_iv)} (15m Δ {_fmt(div)}{' ' + note if note else ''}) | chain age {age:.0f}s")

    # ---------- commands ----------
    def handle_command(self, text: str) -> str:
        t = text.strip()
        if t.startswith("{"):
            try:
                payload = json.loads(t)
            except ValueError as exc:
                return self._reply(f"Could not read that JSON: {exc}")
            return self.process(None, payload, "manual")
        if t[:7].lower() == "@admin:":                  # the admin's instructions (saved; run if they read as a command)
            return self.bot.free_text(t[7:].strip(), tagged_admin=True)
        if t and not t.startswith(("/", "{")):          # free text: saved, and answered if it is a known question
            return self.bot.free_text(t, tagged_admin=False)
        parts = t.split()
        cmd = parts[0].lower().split("@")[0] if parts else ""
        out = self.bot.handle(cmd, parts[1:], t)        # roles first: admin-only commands are refused to users
        if out is not None:
            return out
        if cmd == "/paper":
            return self._reply(self.paper.report() + "\n" + self.r4_report())
        if cmd == "/health":
            h = self.health_status()
            extra = ""
            if h.get("engine") is not None:
                extra += "\nengine: " + (", ".join(f"{k} {v}" for k, v in h["engine"].items()) or "waiting for a bar")
            if h.get("scanner") is not None:
                extra += f"\nscanner: {h['scanner']}"
            if h.get("stocks3m") is not None:
                extra += f"\nstock 3m engine: {h['stocks3m']}"
            if h.get("gs") is not None:
                extra += f"\nGS engine: {h['gs']}"
            return self._reply(("✅ healthy" if h["ok"] else "⚠️ " + "; ".join(h["problems"]))
                               + f"\nlast error: {h['last_error'] or 'none'}" + extra)
        if cmd == "/trust":
            return self._reply(self.trust_report())
        if cmd == "/range":
            return self._reply(self.range_report())
        if cmd == "/options":
            return self._reply(self.options.report())
        if cmd == "/account":
            if not self.accounts:
                return self._reply("The paper accounts are off: set ACCOUNTS in .env.")
            text = self.accounts_text()
            self.tg.send(text, html=True)
            return text
        if cmd == "/ledger":
            if not self.accounts:
                return self._reply("The paper accounts are off: set ACCOUNTS in .env.")
            path = self.export_ledger()
            self.tg.send_document(path, "Paper account ledger: every fill, cash flow, fees, realized P&L")
            return f"ledger sent: {path}"
        if cmd == "/scan":
            if not self.scanner:
                return self._reply("The F&O scanner is off: set SCANNER=on in .env and restart.")
            now = self.now()
            if not self.scanner.ensure_loaded(now.date()):
                return self._reply(f"Scanner not ready yet ({self.scanner.status}); try again in a minute or two.")
            lists = self.scanner.rank(now, f"{now:%H:%M}")
            out = [f"F&O watchlist {now:%H:%M} (analysis only; trades come only from 3-min signals):"]
            for name, df in lists.items():
                out.append(f"{name}: " + (", ".join(f"{r.symbol} {r.chg * 100:+.1f}%"
                                                    + (f" {r.rvol:.1f}×" if r.rvol == r.rvol else "")
                                                    for r in df.itertuples()) or "none"))
            out.append("Tested: NO EDGE after costs (evidence/scanner_result.md).")
            return self._reply("\n".join(out))
        if cmd == "/status":
            root = symbol_root(parts[1]) if len(parts) > 1 else self.s.poll_underlyings[0]
            summ, _ = self.chain_for(root)
            fq, sq = self.fresh_quotes(root)
            basis = (fq.last_price - sq.last_price) if (fq and sq) else None
            return self._reply(self.format_summary(summ, basis) if summ else f"No chain data: {self.health['last_error']}")
        if cmd == "/check":
            try:
                args = parts[1:]
                name = args.pop() if args and not _isnum(args[-1]) else "NIFTY"
                side, entry, sl = args[0], float(args[1]), float(args[2])
                payload = {"symbol": name, "side": side, "entry": entry, "sl": sl, "grade": "A"}
                if len(args) > 3:
                    payload["t1"] = float(args[3])
            except (IndexError, ValueError) as exc:
                return self._reply(f"Usage: /check BUY 24500 24470 [t1] [NIFTY] ({exc})")
            return self.process(None, payload, "manual")
        return self.bot.cmd_help([], t)

    def _reply(self, text: str) -> str:
        self.tg.send(text)
        return text

    # ---------- workers ----------
    def premarket(self, now: datetime) -> None:
        """08:45-09:15 on weekdays: download the day's history once (engine, range model, scanner)."""
        n = now.astimezone(IST)
        # pre-market, or on the first tick after a start during market hours (21 Oct: a mid-day restart made the
        # first range forecast download a year of history in the poll loop: a 38 s cycle)
        if n.weekday() >= 5 or not (8 * 60 + 45 <= n.hour * 60 + n.minute < 15 * 60):
            return
        if self.store.kv_get("warm_day") == n.date().isoformat():
            return
        self.store.kv_set("warm_day", n.date().isoformat())
        if self.engine:
            self._safe(lambda: self.engine.warm(now), "engine warm-up")
        self._safe(lambda: self.ranger.warm(now), "range-model warm-up")
        if self.scanner:
            self.scanner.ensure_loaded(n.date())                      # background thread
        self._refresh_results(n.date())
        self.tg.send("Pre-market: history loaded for the engine and range model"
                     + ("; the F&O scanner is loading stock history" if self.scanner else "") + ".")

    def _refresh_results(self, day) -> None:
        """The 📰 results calendar (bridge/events.py): one NSE request a day, in the background."""
        import threading
        if getattr(self, "results", None) is None:
            from .events import ResultsCalendar
            self.results = ResultsCalendar(self.s.db_path.parent)
        if self.results.day != day.isoformat() and not getattr(self, "_results_busy", False):
            self._results_busy = True

            def run():
                try:
                    self.results.refresh(day)
                finally:
                    self._results_busy = False
            threading.Thread(target=run, daemon=True, name="results-calendar").start()

    def results_flag(self, symbol: str) -> str:
        """'' or a 📰 line for a stock with results today, yesterday or on the next trading day. Never raises."""
        try:
            day = self.now().astimezone(IST).date()
            self._refresh_results(day)
            return self.results.flag(symbol, day)
        except Exception:
            return ""

    def tick(self) -> None:
        now = self.now()
        self.health["poll_beat"] = now.isoformat()
        self.premarket(now)
        roots = set(self.s.poll_underlyings) | self.paper.underlyings_open()
        if market_open(now) or self.paper.underlyings_open():
            for root in sorted(roots):
                self._safe(lambda r=root: self.refresh_quotes(r), f"quotes {root}")
                with self._lock:
                    c = self._chain.get(root)
                if market_open(now) and (not c or (now - c[0]).total_seconds() >= self.s.poll_seconds):
                    self._safe(lambda r=root: self.refresh_chain(r), f"chain {root}")
        if market_open(now) and self.engine and not self.bot.off("index"):
            self._safe(lambda: self.engine.step(now), "live engine")
        if market_open(now) and self.paper.open_stock_trades():
            self._safe(lambda: self.refresh_stock_futures(now), "stock futures")
        if self.scanner and not self.bot.off("scanner"):
            self._safe(lambda: self.scanner.step(now), "scanner")
        if self.stocks and not self.bot.off("stocks"):
            self._safe(lambda: self.stocks.step(now), "stock 3m engine")
        if self.gs is not None and not self.bot.off("gs"):
            self._safe(lambda: self.gs.ensure_thread(), "GS engine")     # GS steps on its own 2 s thread
        for acct in self.accounts:
            if market_open(now) or acct.positions:
                for msg in self._safe(lambda a=acct: a.on_tick(now), f"account {acct.name}") or []:
                    self.tg.send(msg)
        for book, msg in self._safe(lambda: self.options.settle(now), "option exits") or []:
            if book not in ("scanner", "stock3m"):    # stock legs are summarised in the daily report
                self.tg.send(msg, html=True)
        if market_open(now) and now.minute % 15 < 5 and \
                (9 * 60 + 45 <= now.hour * 60 + now.minute <= 14 * 60 + 19):
            self._safe(lambda: self.record_range_forecasts(now), "range forecasts")
        if market_open(now) and now.minute % 5 == 1:
            self._safe(lambda: self.score_range_forecasts(now), "range scoring")
        self.daily_report(now)
        self._safe(lambda: self.bot.tick(now), "bot jobs")

    def poll_loop(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("poll iteration failed")
            stop.wait(self.s.quote_seconds)

    def telegram_loop(self, stop: threading.Event) -> None:
        while not stop.is_set() and self.tg.enabled:
            self.health["tg_beat"] = self.now().isoformat()
            try:
                texts = self.tg.poll_commands(timeout=25)
                for i, text in enumerate(texts):
                    srcs = getattr(self.tg, "sources", [])
                    if hasattr(self.tg, "reply_to"):
                        self.tg.reply_to = srcs[i] if i < len(srcs) else None    # answer the chat that asked
                    try:
                        self.handle_command(text)
                    except Exception:     # one bad command must not block the queue
                        log.exception("command failed")
                    finally:
                        if hasattr(self.tg, "reply_to"):
                            self.tg.reply_to = None
                self.tg.commit()          # FIX (M09): acknowledge updates only after the commands were handled
                if self.bot.restart_requested:      # after the commit, so /restart is not replayed on start
                    log.warning("restart requested by the admin")
                    import os
                    os._exit(3)                     # start.sh restarts the bridge on exit code 3
            except Exception as exc:
                log.warning("telegram poll error: %s", type(exc).__name__)
                stop.wait(5)

    def daily_report(self, now: datetime | None = None) -> str | None:
        now = (now or self.now()).astimezone(IST)
        day = now.date().isoformat()
        if self.store.kv_get("report_day") == day or now.hour * 60 + now.minute < 15 * 60 + 20 or now.weekday() >= 5:
            return None
        self._safe(lambda: self.score_range_forecasts(now), "range scoring")
        text = self.report_text()
        sent = self.tg.send(text)
        if self.accounts:
            self.tg.send(self.accounts_text(), html=True)
        if sent or not self.tg.enabled:       # FIX (M09): a failed delivery is retried on the next tick
            self.store.kv_set("report_day", day)
        else:
            self._error("daily report: Telegram delivery failed, will retry")
        return text

    def report_text(self) -> str:
        text = "\n".join([self.paper.report(), self.r4_report(), self.options.report(), self.scanner_report(),
                          self.scanner_report("stock3m"), self.range_report()])
        warn = drift(self.evidence.get("tradingview_futures") or self.evidence["cells"]["all|all|all"], self.live_record())
        return text + ("\n" + warn if warn else "")

    def export_ledger(self):
        import csv
        path = self.s.db_path.parent / f"account_ledger_{self.now():%Y-%m-%d}.csv"
        with self.store._lock:
            cur = self.store.db.execute("SELECT acct, ts, sid, symbol, action, lots, units, price, cash_flow, fees, "
                                        "realized, reason, cash_after FROM account_fills ORDER BY id")
            cols = [c[0] for c in cur.description]
            rows = cur.fetchall()
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(rows)
        return path

    def refresh_stock_futures(self, now: datetime) -> None:
        """Live quotes for the stock futures of open scanner trades; they manage those paper trades."""
        open_ = self.paper.open_stock_trades()
        keys = {t.underlying: self.stock_futures.get(t.underlying) for t in open_}
        missing = [u for u, k in keys.items() if not k]
        if missing:
            uni = {u["symbol"]: u["fut_key"] for u in self.provider.fno_stocks(now.date())}
            for u in missing:
                keys[u] = self.stock_futures[u] = uni.get(u)
        qs = self.provider.quotes(sorted({k for k in keys.values() if k}))
        hh, mm = divmod(self.s.square_off_hhmm, 100)
        for u, k in keys.items():
            q = qs.get(k) if k else None
            if q is None or not self._fresh(q, now):
                continue
            for t in self.paper.on_quote(u, q, now, self.s.max_gap_s, self.s.extra_slippage_ticks, hh * 60 + mm):
                self.options.request_close(t.sid, t.book, t.exit_reason)   # one summary in the daily report

    def accounts_text(self) -> str:
        """The main account in full; the strategy accounts (evidence/strategy_accounts_protocol.md) side by side."""
        text = self.accounts[0].report()
        if len(self.accounts) > 1:
            text += ("\n\n📊 <b>Strategy accounts</b> (same signals, different handling; paper)\n"
                     + "\n".join(a.summary_line() for a in self.accounts))
        return text

    def scanner_report(self, book: str = "scanner") -> str:
        label = {"scanner": "Scanner", "stock3m": "Stock 3m engine"}[book]
        with self.store._lock:
            rows = self.store.db.execute("SELECT status, net_pts, r_pts, state FROM paper_trades WHERE book=?",
                                         (book,)).fetchall()
        if not rows:
            return f"{label} paper book: no trades yet."
        closed = [(n, r, json.loads(st)) for stt, n, r, st in rows if stt == "CLOSED" and r]
        inr = sum(n * (st.get("lot_units") or 1) * st.get("lots", 1) for n, r, st in closed)
        rs = [n / r for n, r, _ in closed]
        tested = " (tested: −0.05 to −0.09R per trade)" if book == "scanner" else " (untested on 3m)"
        return (f"{label} paper book: closed {len(closed)}, open {sum(r[0] == 'OPEN' for r in rows)}"
                + (f", {sum(x > 0 for x in rs)}/{len(rs)} winners, avg {sum(rs) / len(rs):+.2f}R, net ₹{inr:+,.0f}"
                   if rs else "") + tested)

    def health_status(self) -> dict:
        now = self.now()
        h = dict(self.health)
        problems = []
        if _age(h["poll_beat"], now) > 3 * self.s.quote_seconds:
            problems.append("poll worker not running")
        if market_open(now):                    # FIX (M09): per instrument, so one dead feed cannot hide
            for root in sorted(set(self.s.poll_underlyings) | self.paper.underlyings_open()):
                if _age(h["quote_ok_by"].get(root), now) > 3 * self.s.quote_seconds + self.s.max_quote_age_s:
                    problems.append(f"no fresh futures quotes for {root}")
                if _age(h["chain_ok_by"].get(root), now) > self.s.max_chain_age_s:
                    problems.append(f"no fresh option chain for {root}")
        if self.tg.enabled and h["tg_beat"] and _age(h["tg_beat"], now) > 120:
            problems.append("Telegram command loop not running")
        if self.risk.halted():
            problems.append("halted by /halt")
        if self.engine:
            h["engine"] = dict(self.engine.status)
        if self.scanner:
            h["scanner"] = self.scanner.status
        if self.stocks:
            h["stocks3m"] = self.stocks.status
        if self.gs is not None:
            h["gs"] = self.gs.status          # informational: GS problems never make the bridge unhealthy
        h["ok"] = not problems
        h["problems"] = problems
        return h


def _isnum(x: str) -> bool:
    try:
        float(x)
        return True
    except ValueError:
        return False
