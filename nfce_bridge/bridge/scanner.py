"""F&O stock scanner: top gainers, top losers and volume surges among F&O stocks, with levels and paper trades.

Rules exactly as tested in evidence/scanner_protocol.md (result: evidence/scanner_result.md, NO EDGE after costs):
* universe: every stock with a live NSE future (Upstox instruments file), about 246;
* at 10:15, 11:15 and 13:15 (after that bar closes): chg = last / previous close - 1; rvol = volume so far / the
  average volume by the same time over the previous 10 sessions;
* G1 gainers (BUY) = top 5 by chg (> 0), G1 losers (SELL) = bottom 5 (< 0); volume surges (G2) = top 5 rvol >= 1.5,
  traded in the direction of the day (last vs open);
* levels: R = 0.5 x daily ATR14 (previous days), SL = entry -/+ R, T1/T2/T3 = 1R/2R/3R, exit by 15:15;
* paper: book `scanner`, one lot of the stock future at its live ask/bid + 2 ticks (levels moved to futures prices by the
  live basis), plus the 1-ITM option leg in the options book.
"""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from .live_engine import frame
from .paper import PaperTrade
from .providers import IST, ProviderError

log = logging.getLogger("nfce.scanner")
STOCK_SPREAD_MAX = 0.0025          # stock futures: 0.25% of price (21 Oct: 0.1% refused a third of the picks; entry
                                   # still pays the whole spread + 2 ticks, so the paper fill stays realistic)
TOP, RVOL_MIN = 5, 1.5
EVIDENCE = {"G1": "gainer/loser continuation: −0.07R per trade after costs over 7,135 tested trades (2022–24)",
            "G2": "volume surge: −0.05 to −0.09R per trade after costs over about 3,200 tested trades (2022–24)"}


def atr14_prev(d: pd.DataFrame) -> float:
    day = d.groupby(d.index.normalize()).agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    pc = day.close.shift(1)
    tr = pd.concat([day.high - day.low, (day.high - pc).abs(), (day.low - pc).abs()], axis=1).max(axis=1)
    a = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    return float(a.iloc[-1]) if len(a) and np.isfinite(a.iloc[-1]) else float("nan")


def avg_cum_volume(d: pd.DataFrame, bar_start_hm: int, n: int = 10) -> float:
    """Mean cumulative volume up to and including the bar starting at bar_start_hm, over the last n sessions."""
    hm = d.index.hour * 60 + d.index.minute
    x = d[hm <= bar_start_hm]
    per = x.volume.groupby(x.index.normalize()).sum().tail(n)
    return float(per.mean()) if len(per) == n else float("nan")


def since_open_line(rule: str, last: float, day_open: float | None, chg: float) -> str:
    """Volume surges (G2) trade the move since the open; say so next to the change vs yesterday's close (26 Oct:
    DRREDDY 'SELL +1.3%' gapped up after results and had fallen below its open)."""
    if rule != "G2" or not day_open:
        return ""
    return (f"↕️ {last / day_open - 1:+.1%} since the open ({chg:+.1%} vs yesterday's close): "
            f"volume surges follow the move since the open")


class Scanner:
    def __init__(self, bridge):
        self.b = bridge
        self.universe: list[dict] = []
        self.hist: dict[str, pd.DataFrame] = {}
        self.day: date | None = None
        self.loading = False
        self.done: set[tuple[date, str]] = set()
        self.status = "not loaded"
        self.watch: dict[str, str] = {}               # symbol -> why it is on today's watchlist (for signal tags)

    # ---------- daily history ----------
    def _load(self, today: date) -> None:
        try:
            uni = self.b.provider.fno_stocks(today)
            hist = {}
            for i, u in enumerate(uni):
                try:
                    hist[u["symbol"]] = frame(self.b.provider.candles_5m(u["equity_key"], today - timedelta(days=35),
                                                                        today - timedelta(days=1)))
                except ProviderError:
                    continue
                self.status = f"loading history {i + 1}/{len(uni)}"
            self.universe, self.hist, self.day = uni, hist, today
            self.status = f"ready: {len(hist)} F&O stocks"
        except Exception as exc:
            log.exception("scanner history failed")
            self.status = f"history failed: {type(exc).__name__}"
        finally:
            self.loading = False

    def ensure_loaded(self, today: date, background: bool = True) -> bool:
        if self.day == today and self.hist:
            return True
        if not self.loading:
            self.loading = True
            if background:
                threading.Thread(target=self._load, args=(today,), daemon=True, name="scanner-history").start()
            else:
                self._load(today)
        return self.day == today and bool(self.hist)

    # ---------- scan ----------
    def rank(self, now: datetime, t: str) -> dict:
        h, m = map(int, t.split(":"))
        bar_start = h * 60 + m - 5
        keys = [u["equity_key"] for u in self.universe]
        qs = {}
        for i in range(0, len(keys), 400):                         # Upstox: up to 500 keys per quote request
            qs.update(self.b.provider.quotes(keys[i:i + 400]))
        rows = []
        for u in self.universe:
            q, d = qs.get(u["equity_key"]), self.hist.get(u["symbol"])
            if q is None or d is None or d.empty or not q.prev_close:
                continue
            avg = avg_cum_volume(d, bar_start)
            atr = atr14_prev(d)
            rows.append({**u, "last": q.last_price, "chg": q.last_price / q.prev_close - 1, "open": q.day_open,
                         "high": q.day_high, "low": q.day_low,
                         "rvol": (q.volume / avg) if (q.volume and avg and np.isfinite(avg) and avg > 0) else np.nan,
                         "atr": atr})
        df = pd.DataFrame(rows)
        if df.empty:
            return {"gainers": df, "losers": df, "surges": df}
        g = df[df.chg > 0].nlargest(TOP, "chg").assign(side=1, rule="G1")
        lo = df[df.chg < 0].nsmallest(TOP, "chg").assign(side=-1, rule="G1")
        seen = set(g.symbol) | set(lo.symbol)                   # no stock twice (21 Oct: ABB was on two lists)
        v = df[(df.rvol >= RVOL_MIN) & df.open.notna() & (df["last"] != df.open) & ~df.symbol.isin(seen)].nlargest(TOP, "rvol")
        v = v.assign(side=np.where(v["last"] > v.open, 1, -1), rule="G2")
        return {"gainers": g, "losers": lo, "surges": v}

    def scan(self, now: datetime, t: str) -> str:
        self._human = []
        lists = self.rank(now, t)
        lines = [f"📊 F&O scanner {t} (all {len(self.universe)} F&O stocks): 🔴 NO EDGE in testing",
                 f"• {EVIDENCE['G1']}", f"• {EVIDENCE['G2']}"]
        titles = {"gainers": "Top 5 gainers → BUY (continuation)", "losers": "Top 5 losers → SELL (continuation)",
                  "surges": "Volume surges (≥1.5× usual volume by now) → with the day's direction"}
        sell_only = self.b.s.scanner_mode == "sell"
        if sell_only:
            titles["gainers"] = "Top 5 gainers → watch only (SCANNER_MODE=sell: buying gainers lost in every test)"
        for name, df in lists.items():
            lines.append(titles[name] + ":")
            self._human.append(("title", name))
            if df.empty:
                lines.append("   none")
            for r in df.itertuples():
                if sell_only and int(r.side) > 0:            # 23 Oct: the BUY side lost on every live day and test
                    lines.append(f"   watch: {r.symbol} {r.chg * 100:+.1f}%")
                    from . import human
                    self._human.append(("watch", human.watch_line(r.symbol, r.chg, r.rvol, r.last,
                                                                  getattr(r, "high", None), getattr(r, "low", None))))
                    continue
                lines.append("   " + self.pick(r, t, now))
        lines.append("Every pick is paper-traded (book `scanner`, 1 lot of the future, and its option leg). "
                     "Alerts only. No order placed. Not a recommendation.")
        self.human_text = self.human_message(t)
        return "\n".join(lines)

    def watch_message(self, t: str, lists: dict) -> str:
        """Watchlist (owner 21 Oct 11:45): gainers / losers / volume surges to WATCH. No BUY/SELL, no paper trades;
        trades come only from real 3-minute signals, which say when the stock is on this list."""
        from . import human
        heads = {"gainers": "🔼 <b>Top gainers</b>", "losers": "🔽 <b>Top losers</b>",
                 "surges": "🔊 <b>Unusual volume</b> (vs the usual volume by this time)"}
        self.watch = {}                                # this scan's list replaces the previous one
        opening = t in ("09:21", "09:30")
        out = [f"👀 <b>F&amp;O {'Opening ' if opening else ''}Watchlist  ·  {human.e(t)}</b>", "━━━━━━━━━━━━━━"]
        if opening:
            out.append("<i>Opening momentum: the strongest early moves. Early moves often reverse; watch, don't chase.</i>")
        for name, df in lists.items():
            out += ["", heads[name]]
            if df.empty:
                out.append("• none")
            for r in df.itertuples():
                out.append(human.watch_line(r.symbol, r.chg, r.rvol, r.last, getattr(r, "high", None),
                                            getattr(r, "low", None)))
                why = {"gainers": "top gainer", "losers": "top loser", "surges": "unusual volume"}[name]
                prev = self.watch.get(r.symbol, "")
                self.watch[r.symbol] = f"{prev}, {why}" if prev and why not in prev else (prev or f"{why} {r.chg * 100:+.1f}%")
        out += ["", "💡 <b>A gainer does not always keep gaining.</b> Watch these; trade only when a 3-min signal "
                "confirms (signals on these stocks are tagged 👀).",
                "<i>watchlist only · no trade suggested · not advice</i>"]
        return "\n".join(out)

    def human_message(self, t: str) -> str:
        from . import human
        heads = {"gainers": "🔼 <b>Top gainers</b> → buy", "losers": "🔽 <b>Top losers</b> → sell",
                 "surges": "🔊 <b>Volume surges</b> → with the day's move"}
        if self.b.s.scanner_mode == "sell":
            heads["gainers"] = "🔼 <b>Top gainers</b> → watch only (buying gainers lost in every test)"
        out = [f"📊 <b>F&amp;O Scanner  ·  {human.e(t)}</b>", "━━━━━━━━━━━━━━"]
        for kind, item in self._human:
            if kind == "title":
                out += ["", heads[item]]
            else:
                out.append(item)
        if len(out) and all(not x.startswith(("🟩", "🟥")) for x in out):
            out.append("No stocks qualified.")
        out += ["", "🔴 <b>Track record:</b> no proven edge",
                "<i>Tested 2022–24: buying gainers / selling losers lost −0.07R per trade after costs. "
                "Use as a watchlist.</i>", "<i>paper picks · not advice · no order placed</i>"]
        return "\n".join(out)

    def pick(self, r, t: str, now: datetime) -> str:
        side, R = int(r.side), 0.5 * float(r.atr)
        head = f"{r.symbol} {r.chg * 100:+.1f}%" + (f" vol {r.rvol:.1f}×" if np.isfinite(r.rvol) else "")
        if not np.isfinite(R) or R <= 0:
            return head + " (no ATR history: no levels)"
        e = float(r.last)
        lv = [e - side * R] + [e + side * k * R for k in (1, 2, 3)]
        text = (f"{head} | {'BUY' if side > 0 else 'SELL'} ~{e:,.2f} SL {lv[0]:,.2f} T1 {lv[1]:,.2f} T2 {lv[2]:,.2f} "
                f"T3 {lv[3]:,.2f}")
        note = self.paper(r, t, now, side, e, R)
        from . import human
        sid = f"SCAN-{r.symbol}-{r.rule}-{now:%Y%m%d}-{t.replace(':', '')}"
        leg, _ = self.b._legs.get(sid, (None, False))
        flag = self.b.results_flag(r.symbol) if hasattr(self.b, "results_flag") else ""
        surge = since_open_line(r.rule, float(r.last), getattr(r, "open", None), float(r.chg))
        if surge:
            flag = f"{surge}\n   {flag}" if flag else surge
        self._human.append(("pick", human.stock_pick(r.symbol, side, r.chg, r.rvol, e, R, leg=leg,
                                                     leg_note=(leg.note if leg is not None else ""),
                                                     paper=human.paper_words(note, side))
                            + (f"\n   {human.e(flag)}" if flag else "")))
        return text + note

    def paper(self, r, t: str, now: datetime, side: int, spot_entry: float, R: float) -> str:
        """Open the futures paper trade (and its option leg) for a pick."""
        try:
            q = (self.b.provider.quotes([r.fut_key]) or {}).get(r.fut_key)
        except ProviderError:
            q = None
        if q is None or not (q.bid and q.ask) or not self.b._fresh(q, now):
            return " | paper: no fresh futures quote"
        if (q.ask - q.bid) > STOCK_SPREAD_MAX * q.last_price:
            return f" | paper: futures spread {q.ask - q.bid:.2f} too wide"
        basis = q.last_price - spot_entry
        tick = float(r.tick) or 0.05
        px = (q.ask if side > 0 else q.bid) + side * 2 * tick
        sid = f"SCAN-{r.symbol}-{r.rule}-{now:%Y%m%d}-{t.replace(':', '')}"
        tr = PaperTrade(book="scanner", underlying=r.symbol, tf=f"{r.rule}@{t}", decision="SCAN", grade="-", side=side,
                        entry=px, sl=spot_entry - side * R + basis, t1=spot_entry + side * R + basis,
                        t2=spot_entry + side * 2 * R + basis, t3=spot_entry + side * 3 * R + basis,
                        opened=now.isoformat(), sid=sid, signal_R=R, lots=1, lot_units=int(r.lot), tick_size=tick,
                        received=now.isoformat())
        if self.b.paper.has_open(r.symbol, tr.tf, "scanner") or not self.b.paper.open_trade(tr):
            return " | paper: already open"
        self.b.stock_futures[r.symbol] = r.fut_key
        note = f" | paper fut entry {px:,.2f}"
        if self.b.s.option_legs:
            note += " | " + self.b.option_leg(sid, "scanner", r.symbol, r.equity_key, spot_entry, side, spot_entry,
                                              (spot_entry - side * R, spot_entry + side * R, spot_entry + side * 2 * R,
                                               spot_entry + side * 3 * R), int(r.lot), R, now, short=True)
        return note

    def step(self, now: datetime) -> str | None:
        n = now.astimezone(IST)
        today = n.date()
        mins = n.hour * 60 + n.minute
        if n.weekday() >= 5 or not (8 * 60 + 30 <= mins <= 15 * 60):
            return None
        if not self.ensure_loaded(today) or mins < 9 * 60 + 15:          # history loads pre-market
            return None
        for t in self.b.s.scanner_times:
            h, m = map(int, t.split(":"))
            if (today, t) not in self.done and 0 <= mins - (h * 60 + m) <= 4:
                self.done.add((today, t))
                if self.b.s.scanner_mode == "watchlist":
                    lists = self.rank(n, t)
                    text = self.watch_message(t, lists)
                    self.last_text = text                      # /watch shows the latest one
                    self.b.tg.send(text, html=True)
                    return text
                text = self.scan(n, t)
                self.b.tg.send(self.human_text, html=True)
                return text
        return None
