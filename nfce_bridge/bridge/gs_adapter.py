"""GS adapter for the bridge (GS_ENGINE_FINAL_BLUEPRINT.md section 3). Imported only by `bridge/gs_live.py`, which
Bridge starts only when GS=on (off by default); GS-SIP-1 stays DESIGN until its manifest is frozen.

Contract:
* Paper only, its own books and its own database (default data/gs.db). It never touches the six accounts, nfce.db,
  Telegram, or any order path (there is none).
* Every public method is wrapped: an exception inside GS is logged, marks the adapter unhealthy and stops GS for the
  rest of the day (fail-closed). It is never raised into the bridge.
* It feeds the SAME `gs.alpha_sip.SipEngine` methods the replay tool uses (on_clock / on_bar / on_book), so live
  and replay decisions are identical for identical inputs (tests/test_gs_adapter.py in nfce_engine checks it).
* It imports nothing from `bridge` (so it cannot create import cycles or side effects in the live service).
"""
from __future__ import annotations

import logging
import sys
import traceback
from datetime import date, datetime
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[2] / "nfce_engine"
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from gs import alpha_sip as sip  # noqa: E402
from gs import execution as ex  # noqa: E402
from gs import features as ft  # noqa: E402
from gs import store as gstore  # noqa: E402

log = logging.getLogger("nfce.gs")

DEFAULT_BRANCHES = (sip.SipConfig(branch="P", scenario="strict"), sip.SipConfig(branch="P", scenario="touch"),
                    sip.SipConfig(branch="M", scenario="market"))


class GSAdapter:
    def __init__(self, db_path: str | Path | None = None, configs=DEFAULT_BRANCHES, store=None):
        self.healthy, self.last_error, self.disabled_day = True, "", None
        self.day: date | None = None
        self.results: list = []
        self.configs = tuple(configs)
        self.store = store
        if self.store is None and db_path is not None:
            self.store = self._guard(lambda: gstore.Store(db_path), "open store")
            self.disabled_day = None                       # a store failure leaves GS running without persistence
        self.engines = [sip.SipEngine(c, sink=self.store) for c in self.configs]

    # -------------------------------------------------------- isolation
    def _guard(self, fn, what: str):
        if self.disabled_day is not None and self.disabled_day == self.day:
            return None
        try:
            return fn()
        except Exception as e:  # noqa: BLE001  (GS must never break the bridge)
            self.healthy = False
            self.last_error = f"{what}: {e!r}"
            self.disabled_day = self.day
            log.error("GS adapter disabled for the day after an error in %s: %s\n%s", what, e,
                      traceback.format_exc(limit=5))
            return None

    # -------------------------------------------------------- inputs from the bridge
    def start_day(self, day: date, universe: dict, vix: tuple, vix_avail: datetime | None = None) -> None:
        """universe: {instrument_id: gs.alpha_sip.StockDay}, prepared before 09:15 from completed data only."""
        self.day, self.disabled_day, self.results = day, None, []

        def go():
            for e in self.engines:
                e.start_day(day, universe, vix, vix_avail)
        self._guard(go, "start_day")

    def on_clock(self, now: datetime) -> None:
        self._guard(lambda: [e.on_clock(now) for e in self.engines], "on_clock")

    def on_bar(self, instrument_id: str, start: datetime, minutes: int, o: float, h: float, l: float, c: float,
               v: float, received_at: datetime) -> None:
        """A COMPLETED bar, with the time our process received it (its available_at)."""
        def go():
            b = ft.Bar(instrument_id, start, minutes, o, h, l, c, v, received_at)
            for e in self.engines:
                e.on_bar(b)
        self._guard(go, "on_bar")

    def on_quote(self, instrument_id: str, depth: dict, last: float | None, volume: float | None,
                 received_at: datetime, exchange_ts: datetime | None = None) -> None:
        """A quote with its 5-level depth ({"buy": [...], "sell": [...]}) and its response-received time."""
        def go():
            b = ex.Book.from_depth(received_at, depth, last, volume, exchange_ts)
            for e in self.engines:
                e.on_book(instrument_id, b)
        self._guard(go, "on_quote")

    def end_day(self) -> list:
        def go():
            out = []
            for e in self.engines:
                r = e.end_day()
                out.append(r)
                if self.store is not None:
                    self.store.append_snapshot("day_equity", e.ledger.book, datetime.now().astimezone(),
                                               {k: v for k, v in r.items() if k != "opportunities"}, r["day"])
                    self.store.append_snapshot("risk_state", e.ledger.book, datetime.now().astimezone(),
                                               e.risk.to_dict(), r["day"])
            return out
        self.results = self._guard(go, "end_day") or []
        return self.results

    # -------------------------------------------------------- reporting (/gs later)
    def health(self) -> dict:
        return {"healthy": self.healthy, "last_error": self.last_error,
                "disabled_today": self.disabled_day is not None and self.disabled_day == self.day,
                "books": [{"book": e.ledger.book, "open": len(e.ledger.open_positions()),
                           "intents": len(e.intents), "risk": e.risk.to_dict()} for e in self.engines]}

    def fingerprints(self) -> list[str]:
        return [e.fingerprint() for e in self.engines]
