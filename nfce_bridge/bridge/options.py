"""Option legs: for every signal, the 1-ITM option to BUY (call for a BUY signal, put for a SELL signal), with entry,
stop loss and targets, and an `options` paper book that trades it from real bid/ask quotes.

Rules (the same as registered experiment R1, so live results feed the same question):
* expiry: the nearest listed expiry AFTER today (at least two sessions: no 0DTE);
* strike: the nearest strike strictly in the money on the live spot (call: highest strike below spot; put: lowest
  strike above spot);
* entry: the live ask; the leg is skipped (and says why) without a two-sided quote or with a spread above 5% of the ask;
* stop / targets: the underlying's own levels mapped through the option's live delta,
  premium level = ask + |delta| x (underlying level - underlying entry) x side. This is an approximation: gamma, time
  and IV move the premium too. The paper trade therefore follows the UNDERLYING: it exits all at once, at the live bid,
  when the underlying paper trade closes (stop, breakeven/trail, T3 or 15:15);
* fees: the dated option schedule (STT on sell premium, exchange, SEBI, stamp, GST, Rs 20 per order).
Selling (writing) options is not supported: without a hedge the loss is unlimited.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime

from .costs import option_fees
from .providers import IST, ProviderError

MAX_SPREAD_SHARE = 0.05
SCHEMA = """
CREATE TABLE IF NOT EXISTS option_trades (
    id INTEGER PRIMARY KEY, sid TEXT NOT NULL, book TEXT NOT NULL, underlying TEXT, key TEXT, strike REAL, type TEXT,
    expiry TEXT, units INTEGER, opened TEXT, entry REAL, closed TEXT, exit REAL, status TEXT, reason TEXT, fees REAL,
    net_inr REAL, r_inr REAL, leg TEXT, UNIQUE (sid, book));
"""


@dataclass
class OptionLeg:
    underlying: str
    key: str
    strike: float
    typ: str               # CE / PE
    expiry: str
    bid: float | None
    ask: float | None
    delta: float | None
    units: int
    sl: float | None = None
    t1: float | None = None
    t2: float | None = None
    t3: float | None = None
    note: str = ""

    def line(self) -> str:
        if self.note:
            return f"Option leg: {self.underlying} {self.strike:g} {self.typ} {self.expiry}: {self.note}"
        d = f"delta {abs(self.delta):.2f}" if self.delta is not None else "delta n/a (0.5 assumed)"
        return (f"Option leg (buy): {self.underlying} {self.strike:g} {self.typ} exp {self.expiry} | entry ask {self.ask:.2f} "
                f"(bid {self.bid:.2f}) SL {self.sl:.2f} T1 {self.t1:.2f} T2 {self.t2:.2f} T3 {self.t3:.2f} | {d}, "
                f"{self.units} units; levels are delta-mapped estimates, the trade follows the underlying's levels")


def eligible_expiry(expiries: list[str], today: date) -> str | None:
    later = sorted(e for e in expiries if e > today.isoformat())
    return later[0] if later else None


def pick_leg(provider, spot_key: str, underlying: str, spot: float, side: int, entry: float, sl: float,
             targets: tuple[float, float, float], units: int, today: date, tick: float = 0.05) -> OptionLeg:
    """Raises ProviderError when the chain cannot be fetched; returns a leg with `note` when it cannot be traded."""
    exp = eligible_expiry(provider.expiries(spot_key), today)
    if exp is None:
        raise ProviderError(f"no eligible option expiry for {underlying}")
    chain = provider.chain(spot_key, exp)
    spot = chain.spot or spot
    rows = sorted(chain.rows, key=lambda r: r.strike)
    itm = [r for r in rows if r.strike < spot] if side > 0 else [r for r in rows if r.strike > spot]
    if not itm:
        raise ProviderError(f"no in-the-money strike for {underlying} around {spot:,.1f}")
    r = itm[-1] if side > 0 else itm[0]
    typ = "CE" if side > 0 else "PE"
    bid, ask, delta, key = ((r.call_bid, r.call_ask, r.call_delta, r.call_key) if side > 0
                            else (r.put_bid, r.put_ask, r.put_delta, r.put_key))
    leg = OptionLeg(underlying, key, r.strike, typ, exp, bid, ask, delta, units)
    if not (bid and ask and ask >= bid):
        leg.note = "no two-sided quote, not traded"
        return leg
    if (ask - bid) / ask > MAX_SPREAD_SHARE:
        leg.note = f"spread {ask - bid:.2f} is {100 * (ask - bid) / ask:.0f}% of the premium, not traded"
        return leg
    d = abs(delta) if delta is not None and math.isfinite(delta) and 0 < abs(delta) <= 1 else 0.5
    mv = lambda lvl: max(tick, round((ask + d * side * (lvl - entry)) / tick) * tick)   # noqa: E731
    leg.sl, leg.t1, leg.t2, leg.t3 = mv(sl), mv(targets[0]), mv(targets[1]), mv(targets[2])
    return leg


class OptionBook:
    def __init__(self, store, provider):
        self.store, self.provider = store, provider
        with store._lock:
            store.db.executescript(SCHEMA)

    def open(self, sid: str, book: str, leg: OptionLeg, r_pts: float, now: datetime) -> bool:
        if leg.note or not leg.ask:
            return False
        with self.store._lock, self.store.db:
            cur = self.store.db.execute(
                "INSERT OR IGNORE INTO option_trades (sid, book, underlying, key, strike, type, expiry, units, opened, entry,"
                " status, r_inr, leg) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (sid, book, leg.underlying, leg.key, leg.strike, leg.typ, leg.expiry, leg.units, now.isoformat(), leg.ask,
                 "OPEN", r_pts * leg.units, json.dumps(asdict(leg))))
            return cur.rowcount > 0

    def open_rows(self) -> list[tuple]:
        with self.store._lock:
            return self.store.db.execute("SELECT id, sid, book, key, entry, units, opened, r_inr FROM option_trades "
                                         "WHERE status IN ('OPEN', 'CLOSING')").fetchall()

    def request_close(self, sid: str, book: str, reason: str) -> None:
        with self.store._lock, self.store.db:
            self.store.db.execute("UPDATE option_trades SET status='CLOSING', reason=? WHERE sid=? AND book=? AND status='OPEN'",
                                  (reason, sid, book))

    def settle(self, now: datetime) -> list[tuple[str, str]]:
        """Exit every CLOSING leg at the live bid; a leg without a bid is retried, and is UNRESOLVED after the session."""
        out = []
        rows = [r for r in self.open_rows()]
        closing = {r[0]: r for r in rows}
        with self.store._lock:
            st = dict(self.store.db.execute("SELECT id, status FROM option_trades WHERE status IN ('OPEN','CLOSING')").fetchall())
        keys = [r[3] for i, r in closing.items() if st.get(i) == "CLOSING"]
        if not keys:
            return out
        try:
            qs = self.provider.quotes(sorted(set(keys)))
        except ProviderError:
            qs = {}
        for i, sid, book, key, entry, units, opened, r_inr in closing.values():
            if st.get(i) != "CLOSING":
                continue
            q = qs.get(key)
            day = datetime.fromisoformat(opened).astimezone(IST).date()
            if q is None or not q.bid:
                if now.astimezone(IST).date() > day or now.astimezone(IST).hour * 60 + now.astimezone(IST).minute > 15 * 60 + 29:
                    with self.store._lock, self.store.db:
                        self.store.db.execute("UPDATE option_trades SET status='UNRESOLVED', closed=? WHERE id=?",
                                              (now.isoformat(), i))
                    out.append((book, f"⚠️ Option paper trade {key}: no buyer quote to exit, result not counted"))
                continue
            fees = option_fees(entry, q.bid, units, day).total
            net = (q.bid - entry) * units - fees
            with self.store._lock, self.store.db:
                self.store.db.execute("UPDATE option_trades SET status='CLOSED', closed=?, exit=?, fees=?, net_inr=? WHERE id=?",
                                      (now.isoformat(), q.bid, fees, net, i))
            with self.store._lock:
                u, k, typ = self.store.db.execute("SELECT underlying, strike, type FROM option_trades WHERE id=?",
                                                  (i,)).fetchone()
            icon = "✅" if net > 0 else "⛔"
            out.append((book, f"{icon} <b>Option {u} {k:g} {typ}</b> sold at {q.bid:,.2f} (bought {entry:,.2f})\n"
                              f"Paper: <b>{'+' if net >= 0 else '−'}₹{abs(net):,.0f}</b> after costs"
                              + (f" ({net / r_inr:+.2f}R)" if r_inr else "")))
        return out

    def report(self) -> str:
        with self.store._lock:
            rows = self.store.db.execute("SELECT book, status, net_inr, r_inr FROM option_trades").fetchall()
        if not rows:
            return "Option legs: no paper trades yet."
        out = ["Option legs (buy 1-ITM, ask in / bid out, fees included):"]
        for book in sorted({r[0] for r in rows}):
            g = [r for r in rows if r[0] == book]
            c = [r for r in g if r[1] == "CLOSED" and r[3]]
            line = f"   [{book}] closed {len(c)}, open {sum(r[1] in ('OPEN', 'CLOSING') for r in g)}, unresolved " \
                   f"{sum(r[1] == 'UNRESOLVED' for r in g)}"
            if c:
                rs = [r[2] / r[3] for r in c]
                line += f": net ₹{sum(r[2] for r in c):+,.0f}, {sum(x > 0 for x in rs)}/{len(rs)} winners, " \
                        f"avg {sum(rs) / len(rs):+.2f}R"
            out.append(line)
        return "\n".join(out)
