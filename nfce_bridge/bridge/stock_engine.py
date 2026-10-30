"""3-minute NFCE signals for every F&O stock (owner request, 21 Oct 2026 09:46).

Data within Upstox's limits (about 2,000 requests per 30 minutes):
* history: about a month of 3m candles per stock, loaded once a day in the background (2-3 requests per stock);
* today: ONE batch request a minute (v3 market-quote/ohlc, interval I1) returns the last completed 1-minute candle of
  every stock; three of them make a 3-minute bar. A stock with a missing minute skips that bar (never guessed).
Every 3 minutes (in its own thread, so index polling stays fast) the NFCE engine (instr STOCK, tf 3) runs per stock;
a trade entered on the bar that just closed becomes a signal. All signals of one bar go out in ONE Telegram message,
each with futures levels, a paper trade on the stock future (book `stock3m`) and the 1-ITM option leg.
Evidence: NFCE on stocks lost money after costs in the hold-out (-0.29R pooled, 504 trades); 3m was never tested.
"""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta

import pandas as pd

from .live_engine import ENGINE_DIR, HEAVYWEIGHTS, frame  # noqa: F401  (ENGINE_DIR puts nfce on sys.path)
from .paper import PaperTrade
from .providers import IST, ProviderError

log = logging.getLogger("nfce.stocks")
TZ = "Asia/Kolkata"
TF = 3
VIX_KEY = "NSE_INDEX|India VIX"
OHLC_URL = "https://api.upstox.com/v3/market-quote/ohlc"
HEADER = ("🧾 NFCE 3-minute stock signals {t} | 🔴 NO EDGE: NFCE on stocks lost money after costs in testing "
          "(−0.29R per trade pooled); the 3-minute timeframe was never tested")


class StockEngine:
    def __init__(self, bridge):
        self.b = bridge
        self.universe: list[dict] = []
        self.hist: dict[str, pd.DataFrame] = {}          # symbol -> 3m bars before today (+ today's at load time)
        self.minutes: dict[str, dict[int, list]] = {}     # symbol -> {1m candle start ms: [o, h, l, c, v]}
        self.day: date | None = None
        self.loading = False
        self.polled: set[int] = set()                     # minute stamps already requested
        self.done: set[datetime] = set()
        self.busy = False
        self.status = "not loaded"
        self._lock = threading.Lock()

    # ---------- history ----------
    def _keys(self) -> dict[str, str]:
        k = {u["symbol"]: u["equity_key"] for u in self.universe}
        k["INDIAVIX"] = VIX_KEY
        return k

    def _load(self, today: date) -> None:
        try:
            uni = self.b.provider.fno_stocks(today)
            self.universe = uni
            hist = {}
            keys = self._keys()
            for i, (sym, key) in enumerate(keys.items()):
                try:
                    h = self.b.provider.candles_5m(key, today - timedelta(days=30), today - timedelta(days=1), minutes=TF)
                    t = self.b.provider.candles_5m(key, today, today, intraday=True, minutes=TF)
                except ProviderError:
                    continue
                d = frame(h + t, TF)
                hist[sym] = d
                self.status = f"loading 3m history {i + 1}/{len(keys)}"
            with self._lock:
                self.hist, self.day = hist, today
            self.status = f"ready: {len(hist) - 1} F&O stocks on 3m"
        except Exception as exc:
            log.exception("stock 3m history failed")
            self.status = f"history failed: {type(exc).__name__}"
        finally:
            self.loading = False

    def ensure_loaded(self, today: date, background: bool = True) -> bool:
        if self.day == today and self.hist:
            return True
        import time as _t
        if self.loading or _t.monotonic() - getattr(self, "_last_try", -1e9) < 300:   # failed load: retry every 5 min
            return False
        self._last_try = _t.monotonic()
        if not self.loading:
            self.loading = True
            if background:
                threading.Thread(target=self._load, args=(today,), daemon=True, name="stock3m-history").start()
            else:
                self._load(today)
        return self.day == today and bool(self.hist)

    # ---------- live 1-minute candles ----------
    def poll_minute(self, now: datetime) -> int:
        """Once a minute (a few seconds after it closes): the last completed 1m candle of every stock, one request."""
        n = now.astimezone(IST)
        stamp = n.hour * 60 + n.minute
        if stamp in self.polled or n.second < 3:
            return 0
        self.polled.add(stamp)
        keys = self._keys()
        by_key = {v: k for k, v in keys.items()}
        got = 0
        vals = list(keys.values())
        for i in range(0, len(vals), 450):
            data = (self.b.provider._get(OHLC_URL, {"instrument_key": ",".join(vals[i:i + 450]), "interval": "I1"})
                    or {}).get("data") or {}
            for q in data.values():
                sym = by_key.get(q.get("instrument_token"))
                p = q.get("prev_ohlc") or {}
                if sym and p.get("ts") and p.get("close"):
                    self.minutes.setdefault(sym, {})[int(p["ts"])] = [p["open"], p["high"], p["low"], p["close"],
                                                                      p.get("volume") or 0]
                    got += 1
        return got

    def bars(self, sym: str, now: datetime) -> pd.DataFrame:
        """History + today's 3m bars built from complete 1-minute triples (completed bars only)."""
        h = self.hist.get(sym)
        if h is None:
            return pd.DataFrame()
        rows = []
        mins = self.minutes.get(sym, {})
        for ms in sorted(mins):
            t = pd.Timestamp(ms, unit="ms", tz="UTC").tz_convert(TZ)
            m = t.hour * 60 + t.minute - (9 * 60 + 15)
            if m % TF:
                continue
            trip = [mins.get(ms + k * 60000) for k in range(TF)]
            if all(trip):
                rows.append([t.isoformat(), trip[0][0], max(x[1] for x in trip), min(x[2] for x in trip), trip[-1][3],
                             sum(x[4] for x in trip), 0])
        d = pd.concat([h, frame(rows, TF)]) if rows else h
        d = d[~d.index.duplicated(keep="last")].sort_index()
        return d[d.index + pd.Timedelta(minutes=TF) <= pd.Timestamp(now).tz_convert(TZ)]

    # ---------- signals ----------
    def run_slot(self, slot: datetime, now: datetime) -> list[tuple]:
        from nfce import Params, prepare, run
        vix = self.bars("INDIAVIX", now)[["close"]]
        hw = [self.bars(s, now)[["open", "close"]] for s in HEAVYWEIGHTS["NIFTY"] if s in self.hist]
        out = []
        early = slot.hour * 60 + slot.minute <= 9 * 60 + 30
        # EARLY mode (owner request 21 Oct 09:57): the tested rules skip the first 15 minutes; for bars closing
        # 09:18-09:30 the skip is switched off, and those signals are labelled EARLY, untested.
        p = Params(instr="STOCK", skip_open=0) if early else Params(instr="STOCK")
        for u in self.universe:
            try:                                           # one bad stock never stops the others
                b = self.bars(u["symbol"], now)
            except Exception:
                log.exception("bars failed on %s", u["symbol"])
                continue
            if len(b) < 200 or b.index[-1] + pd.Timedelta(minutes=TF) != pd.Timestamp(slot):
                continue
            try:
                open_now: list = []
                run(prepare(b, TF, p, vix=vix.reindex(b.index).ffill().dropna() if len(vix) else None,
                            hw=[x.reindex(b.index).ffill().dropna() for x in hw]), p, open_out=open_now)
            except Exception:
                log.exception("engine failed on %s", u["symbol"])
                continue
            for t in open_now:
                if t.entry_time == pd.Timestamp(slot):
                    out.append((u, 1 if t.side == "L" else -1, float(t.entry), float(t.R), float(t.score)))
        return out

    def _work(self, slot: datetime, now: datetime) -> None:
        try:
            sigs = self.run_slot(slot, now)
            if sigs:
                t = f"{slot:%H:%M}"
                from . import human
                early = slot.hour * 60 + slot.minute <= 9 * 60 + 30
                lines = [f"🧾 <b>Stock signals  ·  3-min  ·  {human.e(t)}</b>", "━━━━━━━━━━━━━━"]
                if early:
                    lines.append("⚡ <b>EARLY</b> (first 15 minutes): opening momentum, <i>completely untested</i>")
                for u, side, e, R, score in sigs:
                    note = self.signal_line(u, side, e, R, score, t, now)
                    sid = f"S3M-{u['symbol']}-{now:%Y%m%d}-{t.replace(':', '')}"
                    if sid not in self.b._legs and self.b.s.option_legs:      # an option for EVERY signal
                        self.b.option_leg(sid, "stock3m", u["symbol"], u["equity_key"], e, side, e,
                                          (e - side * R, e + side * R, e + side * 2 * R, e + side * 3 * R),
                                          int(u["lot"]), R, now, short=True, open_paper=False)
                    leg, _ = self.b._legs.get(sid, (None, False))
                    notes_a = []
                    for a in getattr(self.b, "accounts", []):
                        scale = self.b.s.early_risk if early else self.b.s.stock_signal_risk
                        if scale <= 0:
                            continue
                        n_ = a.consider(now, sid, leg, u["equity_key"], side,
                                        [e - side * R, e + side * R, e + side * 2 * R, e + side * 3 * R],
                                        0.0, f"{u['symbol']} 3m signal", scale)
                        if n_:
                            notes_a.append(n_)
                    acct = "\n   ".join(notes_a)
                    lines += ["", human.stock_pick(u["symbol"], side, None, None, e, R, leg=leg,
                                                   leg_note=(leg.note if leg is not None else ""),
                                                   paper=human.paper_words(note.split("(score", 1)[-1], side),
                                                   score=score)]
                    flag = self.b.results_flag(u["symbol"]) if hasattr(self.b, "results_flag") else ""
                    if flag:
                        lines.append(f"   {human.e(flag)}")
                    w = (self.b.scanner.watch if getattr(self.b, "scanner", None) else {}).get(u["symbol"])
                    if w:
                        lines.append(f"   👀 on today's watchlist: {human.e(w)}")
                    if acct:
                        lines.append(f"   {human.e(acct)}")
                lines += ["", "🔴 <b>Track record:</b> no proven edge",
                          "<i>Tested 2022–24 on 210 F&O stocks (16,598 trades): won 52%, but costs ate more than the "
                          "edge: −0.27R per trade as futures; with 4× wider stops −0.03R, still a loss. Shown for "
                          "information; the paper accounts take their options at ¼ size.</i>", "<i>paper signals · not advice · no order placed</i>"]
                self.b.tg.send("\n".join(lines), html=True)
            self.status = f"ok: {len(sigs)} signals at {slot:%H:%M}, {len(self.minutes)} stocks live"
        except Exception as exc:
            log.exception("stock 3m slot failed")
            self.status = f"error {type(exc).__name__}"
        finally:
            self.busy = False

    def signal_line(self, u: dict, side: int, e: float, R: float, score: float, t: str, now: datetime) -> str:
        lv = [e - side * R] + [e + side * k * R for k in (1, 2, 3)]
        text = (f"• {u['symbol']} {'BUY' if side > 0 else 'SELL'} {e:,.2f} SL {lv[0]:,.2f} T1 {lv[1]:,.2f} "
                f"T2 {lv[2]:,.2f} T3 {lv[3]:,.2f} (score {score:.0f})")
        return text + self.paper(u, side, e, R, t, now)

    def paper(self, u: dict, side: int, e: float, R: float, t: str, now: datetime) -> str:
        if self.b.paper.has_open(u["symbol"], "3m", "stock3m"):
            return " | paper: a position is already open"
        try:
            q = (self.b.provider.quotes([u["fut_key"]]) or {}).get(u["fut_key"])
        except ProviderError:
            q = None
        if q is None or not (q.bid and q.ask) or not self.b._fresh(q, now):
            return " | paper: no fresh futures quote"
        from .scanner import STOCK_SPREAD_MAX
        if (q.ask - q.bid) > STOCK_SPREAD_MAX * q.last_price:
            return f" | paper: futures spread {q.ask - q.bid:.2f} too wide"
        basis = q.last_price - e
        tick = float(u["tick"]) or 0.05
        px = (q.ask if side > 0 else q.bid) + side * 2 * tick
        sid = f"S3M-{u['symbol']}-{now:%Y%m%d}-{t.replace(':', '')}"
        tr = PaperTrade(book="stock3m", underlying=u["symbol"], tf="3m", decision="ENGINE", grade="-", side=side,
                        entry=px, sl=e - side * R + basis, t1=e + side * R + basis, t2=e + side * 2 * R + basis,
                        t3=e + side * 3 * R + basis, opened=now.isoformat(), sid=sid, signal_R=R, lots=1,
                        lot_units=int(u["lot"]), tick_size=tick, received=now.isoformat())
        if not self.b.paper.open_trade(tr):
            return " | paper: already open"
        self.b.stock_futures[u["symbol"]] = u["fut_key"]
        note = f" | paper fut {px:,.2f}"
        if self.b.s.option_legs:
            note += " | " + self.b.option_leg(sid, "stock3m", u["symbol"], u["equity_key"], e, side, e,
                                              (e - side * R, e + side * R, e + side * 2 * R, e + side * 3 * R),
                                              int(u["lot"]), R, now, short=True)
        return note

    def step(self, now: datetime) -> None:
        n = now.astimezone(IST)
        mins = n.hour * 60 + n.minute
        if n.weekday() >= 5 or not (8 * 60 + 30 <= mins <= 15 * 60 + 31):
            return
        loaded = self.ensure_loaded(n.date())
        if self.universe and mins >= 9 * 60 + 16 and (self.hist or self.loading):
            self._safe_poll(now)            # FIX (live 10:33): collect 1m candles while the history is still loading
        if not loaded or mins < 9 * 60 + 16:
            return
        m = mins - (9 * 60 + 15)
        slot = n.replace(hour=(9 * 60 + 15 + m - m % TF) // 60, minute=(9 * 60 + 15 + m - m % TF) % 60, second=0,
                         microsecond=0)
        age = (n - slot).total_seconds()
        # the minute that completes the bar ends at `slot`; it is fetched by the first poll in the minute after it
        fetched = slot.hour * 60 + slot.minute in self.polled
        if fetched and age <= 120 and slot not in self.done and not self.busy and mins <= 15 * 60 + 31:
            self.done.add(slot)
            self.busy = True
            threading.Thread(target=self._work, args=(slot, now), daemon=True, name="stock3m-engine").start()

    def _safe_poll(self, now: datetime) -> None:
        try:
            self.poll_minute(now)
        except ProviderError as exc:
            self.status = f"1m feed error: {exc}"[:160]
