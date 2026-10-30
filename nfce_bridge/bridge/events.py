"""Results calendar for the 📰 flag on stock alerts (admin, 23 Oct 11:13: "consider news, like results announcements").

Tested first (evidence/results_days_protocol.md, 2022-24, 16,598 trades): signals in a stock's results window (the
meeting day and the next trading day) did NOT do worse than on other days, so this is information for a person,
not a rule that skips trades.

Source: NSE's public board-meeting list, fetched once a day (one request) and cached in data/. A failed fetch is
logged and the alerts simply go out without the flag.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

log = logging.getLogger("nfce.events")
NSE = "https://www.nseindia.com/api/corporate-board-meetings"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/126.0 Safari/537.36",
           "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9",
           "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-board-meetings"}


def nse_fetch(d0: date, d1: date) -> list[tuple[str, date]]:
    import httpx
    r = httpx.get(NSE, params={"index": "equities", "from_date": f"{d0:%d-%m-%Y}", "to_date": f"{d1:%d-%m-%Y}"},
                  headers=HEADERS, timeout=20, follow_redirects=True)
    r.raise_for_status()
    out = []
    for x in r.json():
        purpose = f"{x.get('bm_purpose', '')} {x.get('bm_desc', '')}".lower()
        if "result" not in purpose:
            continue
        try:
            out.append((str(x["bm_symbol"]), datetime.strptime(x["bm_date"], "%d-%b-%Y").date()))
        except (KeyError, ValueError):
            continue
    return out


def _prev_weekday(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _next_weekday(d: date) -> date:
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


class ResultsCalendar:
    def __init__(self, data_dir: Path, fetch: Callable[[date, date], list] | None = None):
        self.path = Path(data_dir) / "results_calendar_live.json"
        self.fetch = fetch or nse_fetch
        self.day: str | None = None
        self.rows: dict[str, set] = {}
        try:
            c = json.loads(self.path.read_text())
            self.day = c["day"]
            self.rows = {s: {date.fromisoformat(d) for d in ds} for s, ds in c["rows"].items()}
        except (OSError, ValueError, KeyError):
            pass

    def refresh(self, today: date) -> None:
        if self.day == today.isoformat():
            return
        try:
            rows = self.fetch(today - timedelta(days=7), today + timedelta(days=5))
        except Exception as exc:                          # never block alerts on a calendar
            log.warning("results calendar not refreshed: %s", type(exc).__name__)
            return
        self.rows = {}
        for sym, d in rows:
            self.rows.setdefault(sym, set()).add(d)
        self.day = today.isoformat()
        try:
            self.path.write_text(json.dumps({"day": self.day,
                                             "rows": {s: sorted(d.isoformat() for d in ds) for s, ds in self.rows.items()}}))
        except OSError:
            pass

    def flag(self, symbol: str, today: date) -> str:
        ds = self.rows.get(symbol, set())
        if today in ds:
            return "📰 Results today: expect bigger, faster moves (tested: such signals did not do worse; your judgement)"
        if _prev_weekday(today) in ds:
            return "📰 Results yesterday: today is the reaction day (tested: such signals did not do worse; your judgement)"
        nxt = _next_weekday(today)
        if nxt in ds:
            when = "Monday" if nxt.weekday() == 0 and today.weekday() == 4 else "tomorrow"
            return f"📰 Results {when} (next trading day): positions may face a gap after the announcement"
        return ""
