"""GS inside the live bridge (GS_ENGINE_FINAL_BLUEPRINT.md section 3): the glue between Bridge.tick and the
unwired `bridge/gs_adapter.py`. Paper only, its own book and database (GS_DB, default data/gs.db). Off unless GS=on.

What it reuses (no extra history requests):
* the 3-minute stock engine's universe, its ~30 days of 3m history (opening windows, recent daily bars, VIX) and
  today's 1-minute candles (three complete minutes = one 3-minute bar, fed with the time GS first sees it);
* the daily pickles in ~/Downloads/nfce_data/daily for the 100-session ATR14 (sessions missing there are filled from
  the 3m history; a stock whose previous session is in neither is ineligible that day).
What it adds: ONE batched 5-level quote request for the <= 20 selected stocks (plus any open GS position) every
10 s from 09:21 to 11:33, every 3 s while a decision or order is pending, and every 10 s for open positions until the
exit: about 180 requests per 30 minutes in the morning, far fewer after.
Timing: GS runs on its own daemon thread every 2 s (the bridge tick is 15 s, too slow for a 2 s latency and a 10 s
fill window); `ensure_thread` is called from Bridge.tick.
Isolation: every call goes through GSAdapter, which is fail-closed (an error disables GS for the day and is never
raised); this module's own work runs inside Bridge._safe. GS never touches the six accounts, nfce.db or Telegram
(except the read-only /gs report).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd

from .gs_adapter import GSAdapter, ft, sip  # gs_adapter puts nfce_engine on sys.path
from .providers import IST

log = logging.getLogger("nfce.gs")
DAILY_DIR = Path.home() / "Downloads" / "nfce_data" / "daily"
QUOTES_PATH = "/market-quote/quotes"
START, SELECT, ENTRY_END, CLOSE = time(9, 0), time(9, 21), time(11, 33), time(15, 31)


def _day_bars_from_3m(d: pd.DataFrame) -> dict:
    """{date: DailyBar} for COMPLETE sessions in a 3m frame (125 bars), from the stock engine's history."""
    out = {}
    if d is None or d.empty:
        return out
    idx = pd.DatetimeIndex(d.index).tz_convert(IST)
    for day, g in d.groupby(idx.date):
        if len(g) < 120:                                   # a partial session is not a daily bar
            continue
        out[day] = ft.DailyBar(day, float(g["open"].iloc[0]), float(g["high"].max()), float(g["low"].min()),
                               float(g["close"].iloc[-1]), float(g["volume"].sum()))
    return out


def _windows_from_3m(d: pd.DataFrame) -> list[tuple[date, float]]:
    if d is None or d.empty:
        return []
    idx = pd.DatetimeIndex(d.index).tz_convert(IST)
    hm = idx.hour * 60 + idx.minute
    g = d[(hm == 555) | (hm == 558)]
    gi = pd.DatetimeIndex(g.index).tz_convert(IST)
    s = g.groupby(gi.date)["volume"].agg(["sum", "size"])
    return [(k, float(r["sum"])) for k, r in s.iterrows() if r["size"] == 2]


def _daily_pickle(sym: str, before: date, daily_dir: Path) -> list:
    f = daily_dir / f"{sym}_1d.pkl"
    if not f.is_file():
        return []
    d = pd.read_pickle(f)
    idx = pd.DatetimeIndex(d.index)
    d.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    d = d[d.index < pd.Timestamp(before)].iloc[-130:]
    return [ft.DailyBar(i.date(), float(r.open), float(r.high), float(r.low), float(r.close), float(r.volume))
            for i, r in d.iterrows()]


REPO = Path(__file__).resolve().parents[2]
PROTOCOL = REPO / "evidence" / "gs_sip_1_protocol.md"


def frozen_check(store) -> tuple[str, str]:
    """("FROZEN" | "DESIGN" | "MISMATCH", detail): the manifest built from the files on disk now vs the one frozen
    in the GS store. GS counts only when they are identical; a mismatch means the code or protocol changed after
    the freeze, and GS must not run under the frozen id."""
    from tools import gs_manifest                      # nfce_engine is on sys.path (gs_adapter)
    rec = store.protocol("GS-SIP-1") if store is not None else None
    if rec is None:
        return "DESIGN", "not frozen: dry run"
    now = gs_manifest.build(start=rec["body"].get("start_session"), status="FROZEN")
    frozen = rec["body"]
    cal_ok = now["calendar_sha256"] == frozen.get("calendar_sha256") or \
        store.protocol(f"GS-SIP-1:calendar:{now['calendar_sha256']}") is not None    # a registered extension
    bad = sorted(k for k, v in now["code_hashes"].items() if frozen["code_hashes"].get(k) != v
                 and not (k == gs_manifest.CALENDAR and cal_ok))
    bad += [k for k in gs_manifest.LIVE_FIELDS if k not in ("code_hashes", "calendar_sha256")
            and now.get(k) != frozen.get(k)]
    if not cal_ok:
        bad.append("calendar_sha256")
    missing = sorted(set(frozen["code_hashes"]) - set(now["code_hashes"]))
    if bad or missing:
        return "MISMATCH", "changed since the freeze: " + ", ".join(bad + missing)
    return "FROZEN", f"GS-SIP-1 frozen {rec['frozen_at'][:16]}, manifest {rec['sha256'][:12]}"


class GSLive:
    def __init__(self, bridge, db_path: Path | None = None, daily_dir: Path = DAILY_DIR, adapter=None):
        self.b = bridge
        self.daily_dir = daily_dir
        if adapter is None:
            import hashlib
            from dataclasses import replace
            from .gs_adapter import DEFAULT_BRANCHES
            sha = hashlib.sha256(PROTOCOL.read_bytes()).hexdigest() if PROTOCOL.is_file() else "missing"
            adapter = GSAdapter(db_path, tuple(replace(c, protocol_hash=sha) for c in DEFAULT_BRANCHES))
        self.adapter = adapter
        self.mode = "DESIGN"
        self.day: date | None = None
        self.fed: set = set()                      # (instrument_id, bar start) already given to GS
        self.last_quote: datetime | None = None
        self.closed_day: date | None = None
        self.status = "waiting for the stock engine"

    # -------------------------------------------------------- the day's inputs
    def _universe(self, today: date) -> tuple[dict, tuple]:
        st = self.b.stocks
        uni = {}
        for u in st.universe:
            h = st.hist.get(u["symbol"])
            daily = {b.day: b for b in _daily_pickle(u["symbol"], today, self.daily_dir)}
            for k, v in _day_bars_from_3m(h).items():
                if k < today:
                    daily.setdefault(k, v)
            uni[u["equity_key"]] = sip.StockDay(u["equity_key"], sorted(daily.values(), key=lambda b: b.day),
                                                [w for w in _windows_from_3m(h) if w[0] < today],
                                                tick=float(u.get("tick") or 0.05))
        vixd = {b.day: b for b in _daily_pickle("INDIAVIX", today, self.daily_dir)}
        for k, v in _day_bars_from_3m(st.hist.get("INDIAVIX")).items():
            if k < today:
                vixd.setdefault(k, v)
        (v, rise), _ = ft.vix_state(sorted(vixd.values(), key=lambda b: b.day),
                                     datetime.combine(today, SELECT, IST))
        return uni, (v, rise)

    def _start(self, now: datetime) -> bool:
        st = self.b.stocks
        today = now.date()
        if st is None or st.day != today or not st.hist or not st.universe:
            return False
        try:
            self.mode, detail = frozen_check(self.adapter.store)
        except Exception as exc:                              # cannot verify the freeze: do not run under its id
            self.mode, detail = "MISMATCH", f"freeze check failed: {type(exc).__name__}"
        if self.mode == "MISMATCH":
            self.day, self.closed_day = today, today          # sit the day out, loudly
            self.status = f"NOT RUN today: {detail}"
            log.error("GS not run on %s: %s", today, detail)
            return True
        uni, vix = self._universe(today)
        self.adapter.start_day(today, uni, vix)
        self.day, self.fed, self.last_quote = today, set(), None
        late = now.time() > SELECT
        self.status = (f"{self.mode} | day started {now:%H:%M}: {len(uni)} stocks, VIX "
                       f"{vix[0] if vix[0] is not None else 'unknown'}" + (" (late start: no selection today)" if late else ""))
        return True

    # -------------------------------------------------------- feeding
    def _feed_bars(self, now: datetime) -> int:
        st = self.b.stocks
        keys = {u["symbol"]: u["equity_key"] for u in st.universe}
        n = 0
        for _ in range(3):                        # the tick thread may add a stock while we copy
            try:
                snapshot = [(k, dict(v)) for k, v in list(st.minutes.items())]
                break
            except RuntimeError:
                continue
        else:
            return 0
        for sym, mins in snapshot:
            inst = keys.get(sym)
            if inst is None:
                continue
            for ms in sorted(mins):
                t = pd.Timestamp(ms, unit="ms", tz="UTC").tz_convert(IST)
                if t.date() != self.day or (t.hour * 60 + t.minute - 555) % 3:
                    continue
                start = t.to_pydatetime()
                if (inst, start) in self.fed or start + timedelta(minutes=3) > now:
                    continue
                trip = [mins.get(ms + k * 60000) for k in range(3)]
                if not all(trip):
                    continue
                self.fed.add((inst, start))
                self.adapter.on_bar(inst, start, 3, float(trip[0][0]), float(max(x[1] for x in trip)),
                                    float(min(x[2] for x in trip)), float(trip[-1][3]),
                                    float(sum(x[4] for x in trip)), now)
                n += 1
        return n

    def _watch(self) -> tuple[set, bool]:
        keys, pending = set(), False
        for e in self.adapter.engines:
            keys |= set(getattr(e, "selected", {}))
            for inst, o in getattr(e, "opps", {}).items():
                if o.open_qty > 0 or o.status in ("triggered", "resting", "market_pending"):
                    keys.add(inst)
                    pending = pending or o.status != "positioned"
        return keys, pending

    def _feed_quotes(self, now: datetime) -> int:
        keys, pending = self._watch()
        if not keys:
            return 0
        if now.time() > ENTRY_END and not any(o.open_qty > 0 for e in self.adapter.engines
                                              for o in getattr(e, "opps", {}).values()):
            return 0
        gap = 3.0 if pending else 10.0
        if self.last_quote is not None and (now - self.last_quote).total_seconds() < gap:
            return 0
        self.last_quote = now
        try:
            data = (self.b.provider._get(QUOTES_PATH, {"instrument_key": ",".join(sorted(keys))}) or {}).get("data") or {}
        except Exception as exc:                  # a failed request: no book this round (GS sees the gap)
            self.status = f"quote request failed: {type(exc).__name__}"
            return 0
        got = self.b.now()                                   # the response-received time
        n = 0
        for q in data.values():
            inst = q.get("instrument_token")
            if inst in keys:
                ts = q.get("timestamp")
                try:
                    exch = datetime.fromisoformat(ts) if isinstance(ts, str) else None
                except ValueError:
                    exch = None
                self.adapter.on_quote(inst, q.get("depth") or {}, q.get("last_price"), q.get("volume"), got, exch)
                n += 1
        return n

    # -------------------------------------------------------- the tick
    def step(self, now: datetime) -> None:
        now = now.astimezone(IST)
        if now.weekday() >= 5 or not (START <= now.time() <= time(15, 40)):
            return
        bot = getattr(self.b, "bot", None)
        if bot is not None and bot.off("gs"):                # /toggle gs off: GS stops feeding at once
            self.status = "switched off by /toggle"
            return
        if self.day != now.date():
            if now.time() >= CLOSE or not self._start(now):
                return
        if self.closed_day == self.day:
            return
        self._feed_bars(now)
        self.adapter.on_clock(now)                            # selection, expiries, the 15:15 exit flag
        if now.time() >= SELECT:
            self._feed_quotes(now)
        if now.time() >= CLOSE:
            res = self.adapter.end_day()
            self.closed_day = self.day
            p = next((r for r in res if r["branch"] == "P" and r["scenario"] == "strict"), None)
            self.status = (f"closed {self.day}: " + (f"{len(p['opportunities'])} opportunities, net ₹{p['net']:+,.0f} "
                                                    f"(strict, paper, not yet evidence)" if p else "no result"))

    # -------------------------------------------------------- the thread
    def ensure_thread(self, every_s: float = 2.0) -> None:
        import threading
        if getattr(self, "_thread", None) is not None and self._thread.is_alive():
            return
        self._stop = threading.Event()

        def loop():
            while not self._stop.is_set():
                try:
                    self.step(self.b.now())
                except Exception as exc:          # GSAdapter already isolates GS; this guards the glue itself
                    self.status = f"glue error {type(exc).__name__}: {exc}"[:200]
                    log.exception("GS glue step failed")
                self._stop.wait(every_s)
        self._thread = threading.Thread(target=loop, daemon=True, name="gs-engine")
        self._thread.start()

    def stop(self) -> None:
        if getattr(self, "_stop", None) is not None:
            self._stop.set()

    # -------------------------------------------------------- /gs
    def report(self) -> str:
        h = self.adapter.health()
        lines = ["GS engine (paper research book, separate from the six accounts; NOT yet evidence)",
                 f"status: {self.status}", f"health: {'ok' if h['healthy'] else 'DISABLED: ' + h['last_error']}"]
        for e in self.adapter.engines:
            ops = list(getattr(e, "opps", {}).values())
            filled = [o for o in ops if o.qty > 0]
            net = sum((o.net() or 0.0) for o in ops)
            lines.append(f"{e.cfg.branch} {e.cfg.scenario}: selected {len(e.selected)}, opportunities {len(ops)}, "
                         f"filled {len(filled)}, open {sum(o.open_qty > 0 for o in ops)}, closed net ₹{net:+,.0f}"
                         + (" | " + e.risk.reasons[-1] if e.risk.reasons else ""))
        lines.append("GS-SIP-1 FROZEN: these days count toward its pilot (paper; still not evidence until the final)."
                     if self.mode == "FROZEN" else "GS-SIP-1 not frozen: these numbers are a dry run.")
        return "\n".join(lines)
