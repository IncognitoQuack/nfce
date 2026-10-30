"""Risk gate for the executable paper book. Doing nothing is the default; every block has a stated reason.

Blocks a new executable entry when: halted by /halt, weekend or outside 09:15-15:30 IST, after the last entry
time, the daily stop is hit (spec section 6: 2 losing trades or -2R realised today), or the daily trade cap is
reached. Data-quality blocks (stale quote, wide spread, old alert) are checked by the bridge itself.
"""
from __future__ import annotations

from datetime import datetime

from .providers import IST


def market_open(now: datetime) -> bool:
    now = now.astimezone(IST)
    mins = now.hour * 60 + now.minute
    return now.weekday() < 5 and 9 * 60 + 15 <= mins <= 15 * 60 + 30


class RiskGate:
    def __init__(self, settings, store, paper):
        self.s = settings
        self.store = store
        self.paper = paper

    def halted(self) -> bool:
        return bool(self.store.kv_get("halted", False))

    def set_halted(self, value: bool) -> None:
        self.store.kv_set("halted", bool(value))

    def check(self, now: datetime) -> tuple[bool, str]:
        now = now.astimezone(IST)
        if self.halted():
            return False, "halted (/resume to re-enable)"
        if not market_open(now):
            return False, "market closed"
        hhmm = now.hour * 100 + now.minute
        if hhmm > self.s.last_entry_hhmm:
            return False, f"after last entry time {self.s.last_entry_hhmm}"
        d = self.paper.day_stats(now.date(), "executable")
        if d["losses"] >= self.s.daily_max_losses:
            return False, f"daily stop: {d['losses']} losing trades today"
        if d["r_sum"] <= -self.s.daily_max_loss_r:
            return False, f"daily stop: {d['r_sum']:+.2f}R today"
        if d["trades"] >= self.s.max_trades_per_day:
            return False, f"daily cap: {d['trades']} trades today"
        return True, ""
