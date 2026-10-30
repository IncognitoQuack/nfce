"""Paper ACCOUNT with real constraints (owner, 21 Oct 13:51): a simulated trading account, ₹2,00,000 to start.

Run like a real account:
* cash: every buy pays its premium from cash; nothing is bought without the cash for it;
* sizing: each trade risks at most ACCOUNT_RISK_PCT of current equity (default 1%) between entry and stop; lots are
  rounded DOWN; a signal whose single lot would risk more is skipped (the reason is logged);
* instruments: options (buy the 1-ITM call/put of the signal; premium = the whole cash at risk, low costs). Futures only
  when ACCOUNT_FUTURES=on and the real margin (Upstox margin API) fits the free cash;
* limits: at most ACCOUNT_MAX_OPEN positions, no new entry after 14:45, daily loss limit ACCOUNT_DAILY_LOSS_PCT of the
  day's starting equity (then no new entries that day), all positions closed at 15:15;
* exits follow the signal's own levels on the UNDERLYING: stop; T1/T2/T3 in whole lots (40/30/30 rounded), stop to
  breakeven after T1 and to T1 after T2; every exit at the live bid with the dated option fees;
* records: every fill in `account_fills` (the ledger), equity marked every minute in `account_equity`, positions in
  `account_positions` (restart-safe). /account and /ledger show them.

Loss-avoidance rules added after the first live day (21 Oct; see LIVE_DAY_2026-10-21.md). They are risk controls chosen
before seeing any result, NOT a measured edge:
* cost gate: skip a trade whose round trip (spread + fees) is more than ACCOUNT_MAX_COST_SHARE (25%) of its risk; costs
  were what sank the 3m stock futures (median 35% of risk, evidence/stock3m_result.md);
* one position per underlying (no doubling up when the 3m, 5m and 15m signals agree);
* at most ACCOUNT_MAX_DEPLOY_PCT (60%) of equity in premium at once;
* after 3 losing exits in a row, no new entries for 30 minutes;
* an option-price stop when the underlying's quote is stale (SENSEX futures were stale most of 21 Oct), and a hard
  stop at 1.5× the planned premium risk whatever the underlying does (IV crush / gamma);
* the admin can pause the account, close positions and change the risk settings from Telegram (persisted).

Strategies (22 Oct evening, evidence/strategy_accounts_protocol.md; ACCOUNTS=NAME:capital:strategy). Same signals,
different handling, so the accounts can be compared side by side:
* base: as above;
* concentrated: 5% risk, stock signals at full size, at most 3 entries a day and 3 open, 10% daily loss limit, up to
  90% of equity in premium ("a few big trades");
* wide: the underlying stop and targets at 2x the signal's distances, the premium stop at 2x the premium distance;
* wide4: the same at 4x (the exits that lost least on 2022-24, evidence/wide_stop_result.md), risk at most the premium;
* confirm: no entry at the signal; buy only if the underlying trades 0.5R beyond the entry within 15 minutes
  (levels unchanged, so 1.5R to the stop);
* cluster: at most 2 new entries of one direction in 30 minutes, and a 30-minute time stop before T1.
* guarded (28 Oct evening, evidence/guarded_account_protocol.md; risk controls, NOT a measured edge): base, plus the
  30-minute time stop before T1, a 15% cost gate, and no index entry without a fresh futures quote.
* manual (28 Oct evening, the owner's own account "MAN"): takes NO signals; the owner buys and sells from the desk
  (manual_buy / manual_sell; no automatic stop or target, the 15:15 square-off still applies). Not a strategy test.
A quiet account sends no messages of its own (only its buys are noted on the alert); it shows in /account and reports.
"""
from __future__ import annotations

import json
import logging
import math
import threading
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta

from .costs import option_fees
from .options import OptionLeg
from .paper import lot_plan
from .providers import IST, ProviderError

log = logging.getLogger("nfce.account")
SCHEMA = """
CREATE TABLE IF NOT EXISTS account_positions (id INTEGER PRIMARY KEY, acct TEXT NOT NULL, sid TEXT NOT NULL, status TEXT,
    state TEXT, UNIQUE (acct, sid));
CREATE TABLE IF NOT EXISTS account_fills (id INTEGER PRIMARY KEY, acct TEXT NOT NULL, ts TEXT, sid TEXT, symbol TEXT,
    action TEXT, lots INTEGER, units INTEGER, price REAL, cash_flow REAL, fees REAL, realized REAL, reason TEXT,
    cash_after REAL);
CREATE TABLE IF NOT EXISTS account_equity (acct TEXT NOT NULL, ts TEXT NOT NULL, equity REAL, cash REAL, open_value REAL,
    n_open INTEGER, PRIMARY KEY (acct, ts));
"""


@dataclass
class Position:
    sid: str
    symbol: str            # e.g. "NIFTY 23050 CE"
    key: str               # option instrument key
    under_key: str         # what is watched for the exits (index spot / stock)
    side: int              # direction of the underlying signal
    lots: int
    lot_units: int
    entry: float           # premium paid
    levels: list           # [sl, t1, t2, t3] on the underlying (already shifted to the watched instrument)
    opened: str
    rem_lots: int = 0
    stop: float = math.nan
    hits: int = 0
    realized: float = 0.0
    status: str = "OPEN"
    notes: list = field(default_factory=list)
    opt_sl: float | None = None   # the leg's delta-mapped premium stop (fallback when the underlying is stale)

    def __post_init__(self):
        if not self.rem_lots:
            self.rem_lots = self.lots
        if math.isnan(self.stop):
            self.stop = self.levels[0]


MAX_COST_SHARE = 0.25
MAX_DEPLOY_PCT = 60.0
LOSS_STREAK, COOL_MIN = 3, 30
HARD_STOP_X = 1.5
# what the admin may change from Telegram, with safe bounds
LIMITS = {"risk_pct": (0.1, 2.0), "daily_loss_pct": (0.5, 5.0), "max_open": (1, 8), "max_cost_share": (0.05, 0.5),
          "max_deploy_pct": (10.0, 90.0)}
STRATEGIES = ("base", "concentrated", "wide", "wide4", "confirm", "cluster", "guarded", "manual")
NEVER = 1e12                              # manual positions: price levels that can never trigger
INDEX_ROOTS = ("NIFTY", "BANKNIFTY", "SENSEX")
GUARDED_COST_SHARE = 0.15                 # evidence/guarded_account_protocol.md
CONC_PER_DAY = 3
CONFIRM_R, CONFIRM_MIN = 0.5, 15
CLUSTER_N, CLUSTER_MIN, TIME_STOP_MIN = 2, 30, 30
DG_PEAK_R, DG_GIVE_BACK = 2.0, 0.5   # give-back stop (DG, evidence/day_rules_result.md; adopted 26 Oct for all accounts)


class Account:
    def __init__(self, bridge, capital: float, risk_pct: float = 1.0, daily_loss_pct: float = 3.0, max_open: int = 4,
                 name: str = "2L", max_cost_share: float = MAX_COST_SHARE, max_deploy_pct: float = MAX_DEPLOY_PCT,
                 strategy: str = "base", quiet: bool = False):
        if strategy not in STRATEGIES:
            raise ValueError(f"unknown account strategy {strategy!r}; one of {', '.join(STRATEGIES)}")
        self.b = bridge
        self.name = name
        self.store = bridge.store
        self.strategy, self.quiet = strategy, quiet
        if strategy == "concentrated":
            risk_pct, daily_loss_pct, max_open, max_deploy_pct = 5.0, 10.0, 3, 90.0
        if strategy == "guarded":
            max_cost_share = min(max_cost_share, GUARDED_COST_SHARE)
        self.risk_pct, self.daily_loss_pct, self.max_open = risk_pct, daily_loss_pct, max_open
        self.max_cost_share, self.max_deploy_pct = max_cost_share, max_deploy_pct
        for key in LIMITS:                                   # an admin change survives restarts
            v = self.store.kv_get(self.k(f"set_{key}"))
            if v is not None:
                setattr(self, key, type(getattr(self, key))(v))
        with self.store._lock:
            self.store.db.executescript(SCHEMA)
        if self.store.kv_get(self.k("cash")) is None:
            self.store.kv_set(self.k("cash"), float(capital))
            self.store.kv_set(self.k("capital"), float(capital))
        self.positions = {}
        self._mx = threading.RLock()   # the poll loop, Telegram and the desk act on one account: one at a time
        with self.store._lock:
            for sid, st in self.store.db.execute("SELECT sid, state FROM account_positions WHERE status='OPEN' AND acct=?",
                                                 (self.name,)):
                self.positions[sid] = Position(**json.loads(st))
        self._last_mark = None
        self._last_qs: dict = {}                  # latest quotes, so reports mark open positions at the bid
        self.pending: dict = self.store.kv_get(self.k("pending")) or {}      # confirm: signals waiting for 0.5R

    # ---------- state ----------
    def k(self, key: str) -> str:
        return f"account_{self.name}_{key}"

    @property
    def cash(self) -> float:
        return float(self.store.kv_get(self.k("cash"), 0.0))

    def _set_cash(self, v: float) -> None:
        self.store.kv_set(self.k("cash"), round(v, 2))

    def _save(self, p: Position) -> None:
        with self.store._lock, self.store.db:
            self.store.db.execute("INSERT INTO account_positions (acct, sid, status, state) VALUES (?,?,?,?) "
                                  "ON CONFLICT(acct, sid) DO UPDATE SET status=excluded.status, state=excluded.state",
                                  (self.name, p.sid, p.status, json.dumps(asdict(p))))

    def _fill(self, now, p: Position, action, lots, price, cash_flow, fees, realized, reason) -> None:
        with self.store._lock, self.store.db:
            self.store.db.execute("INSERT INTO account_fills (acct, ts, sid, symbol, action, lots, units, price, cash_flow, "
                                  "fees, realized, reason, cash_after) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                  (self.name, now.isoformat(), p.sid, p.symbol, action, lots, lots * p.lot_units, price, cash_flow,
                                   fees, realized, reason, self.cash))

    def open_value(self, quotes: dict | None = None) -> float:
        v = 0.0
        for p in self.positions.values():
            q = (quotes or {}).get(p.key)
            px = q.bid if q is not None and q.bid else p.entry
            v += px * p.rem_lots * p.lot_units
        return v

    def equity(self, quotes: dict | None = None) -> float:
        return self.cash + self.open_value(quotes)

    def day_start_equity(self, day: str) -> float:
        k = self.k(f"day_start_{day}")
        v = self.store.kv_get(k)
        if v is None:
            v = self.equity()
            self.store.kv_set(k, v)
        return float(v)

    # ---------- admin controls ----------
    @property
    def paused(self) -> bool:
        return bool(self.store.kv_get(self.k("paused")))

    def set_paused(self, on: bool) -> None:
        self.store.kv_set(self.k("paused"), bool(on))

    def set_param(self, key: str, value: float) -> str:
        if key not in LIMITS:
            return f"unknown setting {key!r}; one of: {', '.join(LIMITS)}"
        lo, hi = LIMITS[key]
        if not lo <= value <= hi:
            return f"{key} must be between {lo:g} and {hi:g}"
        value = type(getattr(self, key))(value)
        setattr(self, key, value)
        self.store.kv_set(self.k(f"set_{key}"), value)
        return f"Account {self.name}: {key} = {value:g}"

    def settings_line(self) -> str:
        return ((f"strategy: {self.strategy} · " if self.strategy != "base" else "") +
                f"risk {self.risk_pct:g}% per trade · daily loss limit {self.daily_loss_pct:g}% · max {self.max_open} open · "
                f"cost gate {self.max_cost_share:.0%} of risk · max {self.max_deploy_pct:g}% of equity in premium"
                + (" · ⏸ PAUSED" if self.paused else ""))

    def close(self, now: datetime, which: str = "all", reason: str = "closed by admin") -> list[str]:
        """Sell positions now at the live bid: which = 'all', a position number (1-based, as /open lists them) or a sid."""
        with self._mx:
            return self._close(now, which, reason)

    def _close(self, now: datetime, which: str, reason: str) -> list[str]:
        ps = list(self.positions.values())
        if which != "all":
            if which.isdigit() and 1 <= int(which) <= len(ps):
                ps = [ps[int(which) - 1]]
            else:
                ps = [p for p in ps if p.sid == which]
        if not ps:
            return []
        qs = self.b.provider.quotes(sorted({p.key for p in ps}))
        out = []
        for p in ps:
            o = qs.get(p.key)
            if o is None or not o.bid:
                out.append(f"Account {self.name}: {p.symbol} has no bid right now; not closed")
                continue
            out.append(self._exit(now, p, p.rem_lots, o.bid, reason))
        return out

    def reset(self, now: datetime, capital: float | None = None) -> str:
        if self.positions:
            return f"Account {self.name}: close the {len(self.positions)} open position(s) first (/close all)"
        capital = float(capital or self.store.kv_get(self.k("capital"), 0.0))
        self.store.kv_set(self.k("cash"), capital)
        self.store.kv_set(self.k("capital"), capital)
        day = now.astimezone(IST).date().isoformat()
        self.store.kv_set(self.k(f"day_start_{day}"), capital)
        self.store.kv_set(self.k(f"halt_{day}"), False)
        with self.store._lock, self.store.db:
            self.store.db.execute("INSERT INTO account_fills (acct, ts, sid, symbol, action, lots, units, price, cash_flow, "
                                  "fees, realized, reason, cash_after) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                  (self.name, now.isoformat(), "", "", "RESET", 0, 0, 0, 0, 0, 0, "reset by admin", capital))
        return f"Account {self.name}: reset to ₹{capital:,.0f}"

    def deployed(self) -> float:
        return sum(p.entry * p.rem_lots * p.lot_units for p in self.positions.values())

    def _cooling(self, now: datetime) -> bool:
        until = self.store.kv_get(self.k("cool_until"))
        return bool(until) and now < datetime.fromisoformat(until)

    # ---------- entries ----------
    def consider(self, now: datetime, sid: str, leg, under_key: str, side: int, levels: list, offset: float,
                 label: str, risk_scale: float = 1.0) -> str:
        """A signal and its option leg; returns a short account note for the alert ('' when nothing to say)."""
        with self._mx:
            note = self._consider(now, sid, leg, under_key, side, levels, offset, label, risk_scale)
        return "" if self.quiet and not note.startswith("💼") else note

    def _entries(self, day: str) -> list:
        return self.store.kv_get(self.k(f"entries_{day}")) or []           # [(iso time, side)] of today's buys

    def _consider(self, now: datetime, sid: str, leg, under_key: str, side: int, levels: list, offset: float,
                  label: str, risk_scale: float = 1.0, confirmed: bool = False) -> str:
        n = now.astimezone(IST)
        day = n.date().isoformat()
        if self.strategy == "manual":                  # the owner's own account: no automatic entries at all
            return ""
        if leg is None or leg.note or not leg.ask:
            return f"Account {self.name}: skipped (no tradeable option: {leg.note if leg is not None else 'none'})"
        if n.hour * 60 + n.minute > 14 * 60 + 45:
            return f"Account {self.name}: skipped (after 14:45)"
        if sid in self.positions or (sid in self.pending and not confirmed):
            return ""
        if self.paused:
            return f"Account {self.name}: skipped (paused by the admin)"
        if any(p.symbol.split()[0] == leg.underlying for p in self.positions.values()):
            return f"Account {self.name}: skipped (already holding {leg.underlying}: one position per underlying)"
        if self._cooling(n):
            return f"Account {self.name}: skipped ({LOSS_STREAK} losses in a row: no new entries until " \
                   f"{datetime.fromisoformat(self.store.kv_get(self.k('cool_until'))):%H:%M})"
        entries = self._entries(day)
        if self.strategy == "concentrated" and len(entries) >= CONC_PER_DAY:
            return f"Account {self.name}: skipped ({CONC_PER_DAY} entries already today)"
        if self.strategy == "guarded" and leg.underlying in INDEX_ROOTS and not self._futures_fresh(leg.underlying):
            return (f"Account {self.name}: skipped (no fresh {leg.underlying} futures quote: the signal's own live check "
                    "could not run)")              # 28 Oct 13:48: a NO_DATA SENSEX entry lost ₹11.5k in 3 accounts
        if self.strategy == "cluster":
            recent = [t for t, s_ in entries if s_ == side and n - timedelta(minutes=CLUSTER_MIN) < datetime.fromisoformat(t) <= n]
            if len(recent) >= CLUSTER_N:
                return (f"Account {self.name}: skipped ({CLUSTER_N} {'BUY' if side > 0 else 'SELL'} entries in the last "
                        f"{CLUSTER_MIN} minutes)")
        if len(self.positions) >= self.max_open:
            return f"Account {self.name}: skipped ({self.max_open} positions already open)"
        start = self.day_start_equity(day)
        if self.store.kv_get(self.k(f"halt_{day}")):
            return f"Account {self.name}: skipped (daily loss limit reached)"
        dg = self.store.kv_get(self.k(f"dg_{day}")) or {}
        if dg.get("halt"):
            return (f"Account {self.name}: skipped (give-back stop since {dg['halt']}: the day peaked at "
                    f"+₹{dg['peak']:,.0f} and gave back half)")
        if self.strategy == "confirm" and not confirmed:
            e0 = (levels[0] + levels[1]) / 2 + offset
            trig = e0 + side * CONFIRM_R * abs(levels[1] - levels[0]) / 2
            until = n + timedelta(minutes=CONFIRM_MIN)
            self.pending[sid] = {"leg": asdict(leg), "under_key": under_key, "side": side, "levels": list(levels),
                                 "offset": offset, "label": label, "risk_scale": risk_scale, "trigger": trig,
                                 "until": until.isoformat()}
            self.store.kv_set(self.k("pending"), self.pending)
            return (f"Account {self.name}: waiting for confirmation ({leg.underlying} through {trig:,.0f} by "
                    f"{until:%H:%M})")
        if self.strategy in ("wide", "wide4"):
            m = 4 if self.strategy == "wide4" else 2       # wide4: evidence/wide_stop_result.md (K4 lost least)
            e0, d = (levels[0] + levels[1]) / 2, abs(levels[1] - levels[0]) / 2
            levels = [e0 - side * m * d, e0 + side * m * d, e0 + side * 2 * m * d, e0 + side * 3 * m * d]
            leg = replace(leg, sl=max(leg.ask - m * (leg.ask - leg.sl), 0.05))   # at most the whole premium
        if self.strategy == "concentrated":
            risk_scale = 1.0                                         # stock signals at full size too
        eq = self.equity()
        budget = eq * self.risk_pct / 100 * risk_scale
        per_lot_risk = max(leg.ask - leg.sl, 0.05) * leg.units
        rt = (leg.ask - (leg.bid or leg.ask)) + option_fees(leg.ask, max(leg.ask - (leg.ask - leg.sl), 0.05), leg.units,
                                                             n.date()).total / leg.units
        share = rt / max(leg.ask - leg.sl, 0.05)
        if share > self.max_cost_share:
            return (f"Account {self.name}: skipped (spread + fees ₹{rt * leg.units:,.0f} a lot = {share:.0%} of the risk, "
                    f"above {self.max_cost_share:.0%})")
        lots = int(budget // per_lot_risk)
        if lots < 1:
            return f"Account {self.name}: skipped (1 lot would risk ₹{per_lot_risk:,.0f}, above the ₹{budget:,.0f} budget)"
        lots = min(lots, int(self.cash * 0.95 // (leg.ask * leg.units)))      # never more than the cash
        room = eq * self.max_deploy_pct / 100 - self.deployed()
        lots = min(lots, int(max(room, 0) // (leg.ask * leg.units)))
        if lots < 1 and room < leg.ask * leg.units:
            return (f"Account {self.name}: skipped (₹{self.deployed():,.0f} already in premium; the cap is "
                    f"{self.max_deploy_pct:g}% of equity)")
        if lots < 1:
            return f"Account {self.name}: skipped (cash ₹{self.cash:,.0f} is not enough for 1 lot at ₹{leg.ask * leg.units:,.0f})"
        cost = lots * leg.units * leg.ask
        p = Position(sid, f"{leg.underlying} {leg.strike:g} {leg.typ}", leg.key, under_key, side, lots, leg.units, leg.ask,
                     [x + offset for x in levels], now.isoformat(), opt_sl=leg.sl)
        self._set_cash(self.cash - cost)
        self.positions[sid] = p
        self._save(p)
        self._fill(now, p, "BUY", lots, leg.ask, -cost, 0.0, 0.0, label)
        self.store.kv_set(self.k(f"entries_{day}"), entries + [(n.isoformat(), side)])
        x = self.exposure()
        same = x["sell"] if side < 0 else x["buy"]
        warn = (f"\n   ⚠️ {same} {'SELL' if side < 0 else 'BUY'} positions open, none the other way: one market move hits "
                f"them all (₹{x['at_risk']:,.0f} if every stop is hit)" if same >= 3 and min(x["buy"], x["sell"]) == 0 else "")
        return (f"💼 Account {self.name}: bought {lots} lot{'s' if lots > 1 else ''} of {p.symbol} at {leg.ask:,.2f} = ₹{cost:,.0f} · "
                f"risk ₹{lots * per_lot_risk:,.0f} ({lots * per_lot_risk / eq * 100:.1f}%) · cash left ₹{self.cash:,.0f}" + warn)

    def exposure(self) -> dict:
        """Portfolio view (22 Oct: four SELLs were one bet): direction count and the loss if every premium stop is hit."""
        ps = list(self.positions.values())
        at_risk = sum(max(p.entry - (p.opt_sl if p.opt_sl is not None else 0.0), 0.0) * p.rem_lots * p.lot_units for p in ps)
        return {"buy": sum(p.side > 0 for p in ps), "sell": sum(p.side < 0 for p in ps), "at_risk": at_risk}

    # ---------- exits and marks ----------
    def _exit(self, now, p: Position, lots: int, bid: float, reason: str) -> str:
        units = lots * p.lot_units
        fees = option_fees(p.entry, bid, units, now.astimezone(IST).date()).total
        proceeds = bid * units
        realized = (bid - p.entry) * units - fees
        self._set_cash(self.cash + proceeds - fees)
        p.rem_lots -= lots
        p.realized += realized
        self._fill(now, p, "SELL", lots, bid, proceeds - fees, fees, realized, reason)
        self._give_back(now, realized)
        if p.rem_lots <= 0:
            p.status = "CLOSED"
            self.positions.pop(p.sid, None)
            self._streak(now, p.realized)
        self._save(p)
        return (f"💼 Account {self.name}: sold {lots} lot{'s' if lots > 1 else ''} of {p.symbol} at {bid:,.2f} ({reason}) · "
                f"{'+' if realized >= 0 else '−'}₹{abs(realized):,.0f} after costs · equity ₹{self.equity():,.0f}")

    def _give_back(self, now: datetime, realized: float) -> None:
        """DG: once the day's closed P&L (after costs, partial exits included) has reached +2 x the day's risk per trade
        (start-of-day equity x risk %) and then falls to half of that peak, no new entries for the rest of the day.
        Open positions keep their exits. The latch is stored, so it survives a restart."""
        n = now.astimezone(IST)
        day = n.date().isoformat()
        k = self.k(f"dg_{day}")
        st = self.store.kv_get(k) or {"pnl": 0.0, "peak": 0.0, "halt": None}
        st["pnl"] += realized
        st["peak"] = max(st["peak"], st["pnl"])
        r0 = self.day_start_equity(day) * self.risk_pct / 100
        if not st["halt"] and st["peak"] >= DG_PEAK_R * r0 and st["pnl"] <= DG_GIVE_BACK * st["peak"]:
            st["halt"] = f"{n:%H:%M}"
            if not self.quiet:
                self.b.tg.send(f"🛑 Account {self.name}: give-back stop. Today's closed P&L peaked at +₹{st['peak']:,.0f} "
                               f"and is now +₹{st['pnl']:,.0f}: no new entries today; open positions keep their stops.")
        self.store.kv_set(k, st)

    def _streak(self, now: datetime, realized: float) -> None:
        day = now.astimezone(IST).date().isoformat()
        k = self.k(f"streak_{day}")
        n = int(self.store.kv_get(k, 0)) + 1 if realized < 0 else 0
        self.store.kv_set(k, n)
        if n >= LOSS_STREAK:
            until = now + timedelta(minutes=COOL_MIN)
            self.store.kv_set(self.k("cool_until"), until.isoformat())
            self.store.kv_set(k, 0)
            self.b.tg.send(f"🧊 Account {self.name}: {LOSS_STREAK} losing exits in a row. No new entries until "
                           f"{until.astimezone(IST):%H:%M}; open positions keep their stops.")

    def _confirmations(self, now: datetime, qs: dict) -> list[str]:
        """confirm strategy: buy a waiting signal once its underlying trades 0.5R beyond the entry; drop it after 15 min."""
        msgs = []
        for sid, w in list(self.pending.items()):
            if now > datetime.fromisoformat(w["until"]):
                self.pending.pop(sid)
                continue
            u, o = qs.get(w["under_key"]), qs.get(w["leg"]["key"])
            if u is None or o is None or not o.ask or not self.b._fresh(u, now, exchange_time=False):
                continue
            if (u.last_price - w["trigger"]) * w["side"] < 0:
                continue
            self.pending.pop(sid)
            old = OptionLeg(**w["leg"])
            leg = replace(old, ask=o.ask, bid=o.bid, sl=max(o.ask - (1 + CONFIRM_R) * (old.ask - old.sl), 0.05))
            note = self._consider(now, sid, leg, w["under_key"], w["side"], w["levels"], w["offset"],
                                  w["label"] + " (confirmed)", w["risk_scale"], confirmed=True)
            if note:
                msgs.append(note)
        self.store.kv_set(self.k("pending"), self.pending)
        return msgs

    def on_tick(self, now: datetime) -> list[str]:
        with self._mx:
            return self._on_tick(now)

    def _on_tick(self, now: datetime) -> list[str]:
        if not self.positions and not self.pending and (self._last_mark and (now - self._last_mark).total_seconds() < 60):
            return []
        keys = sorted({p.key for p in self.positions.values()} | {p.under_key for p in self.positions.values()}
                      | {w["under_key"] for w in self.pending.values()} | {w["leg"]["key"] for w in self.pending.values()})
        try:
            qs = self.b.provider.quotes(keys) if keys else {}
        except ProviderError:
            return []
        msgs = self._confirmations(now, qs) if self.pending else []
        n = now.astimezone(IST)
        square = n.hour * 60 + n.minute >= 15 * 60 + 15
        for p in list(self.positions.values()):
            u, o = qs.get(p.under_key), qs.get(p.key)
            if o is None or not o.bid:
                continue
            if square:
                msgs.append(self._exit(now, p, p.rem_lots, o.bid, "15:15 square-off"))
                continue
            planned = (p.entry - p.opt_sl) if p.opt_sl is not None else None
            if planned and planned > 0 and o.bid <= p.entry - HARD_STOP_X * planned:
                msgs.append(self._exit(now, p, p.rem_lots, o.bid, "hard premium stop"))
                continue
            if p.hits > 0:                                    # live 23 Oct: runners after T1 rode back to the
                units = p.rem_lots * p.lot_units              # UNDERLYING's breakeven and sold below the premium paid
                floor = p.entry + option_fees(p.entry, o.bid, units, n.date()).total / units
                if o.bid <= floor:
                    msgs.append(self._exit(now, p, p.rem_lots, o.bid, "breakeven (option at cost)"))
                    continue
            if u is None or not self.b._fresh(u, now, exchange_time=False):
                if p.opt_sl is not None and p.hits == 0 and o.bid <= p.opt_sl:   # the underlying is stale: premium stop
                    msgs.append(self._exit(now, p, p.rem_lots, o.bid, "premium stop (underlying quote stale)"))
                continue
            px, s = u.last_price, p.side
            if (px - p.stop) * s <= 0:
                msgs.append(self._exit(now, p, p.rem_lots, o.bid, "stop" if p.hits == 0 else "breakeven/trail stop"))
                continue
            if (self.strategy in ("cluster", "guarded") and p.hits == 0 and (px - p.levels[1]) * s < 0
                    and now - datetime.fromisoformat(p.opened) >= timedelta(minutes=TIME_STOP_MIN)):
                msgs.append(self._exit(now, p, p.rem_lots, o.bid, f"{TIME_STOP_MIN}-minute time stop"))
                continue
            plan = lot_plan(p.lots)
            while p.hits < 3 and p.rem_lots > 0 and (px - p.levels[1 + p.hits]) * s >= 0:
                n_out = p.rem_lots if p.hits == 2 else min(plan[p.hits], p.rem_lots)
                p.hits += 1
                p.stop = self.entry_level(p) if p.hits == 1 else p.levels[1]   # T1 hit: breakeven; T2 hit: T1
                if n_out:
                    msgs.append(self._exit(now, p, n_out, o.bid, f"T{p.hits}"))
                else:
                    self._save(p)
        self.mark(now, qs)
        return [] if self.quiet else msgs

    # ---------- the owner's manual trading (desk; owner request 28 Oct evening) ----------
    def manual_buy(self, now: datetime, leg, lots: int, under_key: str, side: int,
                   reason: str = "MANUAL buy (desk)") -> str:
        """Buy `lots` of `leg` at its ask, as the owner chose (no risk sizing, no signal levels). The position has no
        automatic stop or target: it is sold by the owner (desk Sell) or by the 15:15 square-off. Cash must cover it."""
        with self._mx:
            n = now.astimezone(IST)
            if not (9 * 60 + 15 <= n.hour * 60 + n.minute < 15 * 60 + 10):
                return f"Account {self.name}: not bought (manual buys 09:15–15:10 only)"
            if leg is None or leg.note or not leg.ask or lots < 1:
                return f"Account {self.name}: not bought ({leg.note if leg is not None and leg.note else 'no tradeable option'})"
            cost = lots * leg.units * leg.ask
            if cost > self.cash:
                return f"Account {self.name}: not bought (₹{cost:,.0f} needed, cash ₹{self.cash:,.0f})"
            sid, k = f"MAN-{leg.underlying}-{n:%Y%m%d-%H%M%S}", 1
            def taken(x: str) -> bool:
                with self.store._lock:
                    return bool(self.store.db.execute("SELECT 1 FROM account_positions WHERE acct=? AND sid=?",
                                                      (self.name, x)).fetchone())
            while sid in self.positions or taken(sid):
                k += 1                                          # two buys in one second must not share an id
                sid = f"MAN-{leg.underlying}-{n:%Y%m%d-%H%M%S}-{k}"
            p = Position(sid, f"{leg.underlying} {leg.strike:g} {leg.typ}", leg.key, under_key, side, lots, leg.units,
                         leg.ask, [-side * NEVER, side * NEVER, side * NEVER, side * NEVER], now.isoformat())
            self._set_cash(self.cash - cost)
            self.positions[sid] = p
            self._save(p)
            self._fill(now, p, "BUY", lots, leg.ask, -cost, 0.0, 0.0, reason)
            return (f"💼 Account {self.name}: bought {lots} lot{'s' if lots > 1 else ''} of {p.symbol} {leg.expiry} at "
                    f"{leg.ask:,.2f} = ₹{cost:,.0f} ({reason}) · cash left ₹{self.cash:,.0f}")

    def manual_sell(self, now: datetime, sid: str, lots: int | None = None, reason: str = "MANUAL sell (desk)") -> list[str]:
        """Sell some (`lots`) or all of one position at the live bid."""
        with self._mx:
            p = self.positions.get(sid)
            if p is None:
                return [f"Account {self.name}: no open position {sid}"]
            n_out = p.rem_lots if not lots else max(1, min(int(lots), p.rem_lots))
            o = self.b.provider.quotes([p.key]).get(p.key)
            if o is None or not o.bid:
                return [f"Account {self.name}: {p.symbol} has no bid right now; not sold"]
            return [self._exit(now, p, n_out, o.bid, reason)]

    def _futures_fresh(self, root: str) -> bool:
        """The bridge's own futures-quote freshness check (False when it cannot be made)."""
        try:
            fq, _ = self.b.fresh_quotes(root)
        except Exception:                                       # noqa: BLE001: no check = not fresh
            return False
        return fq is not None

    @staticmethod
    def entry_level(p: Position) -> float:
        """The signal's entry on the watched instrument: halfway between SL and T1 (both 1R from the entry)."""
        return (p.levels[0] + p.levels[1]) / 2

    def mark(self, now: datetime, qs: dict | None = None) -> None:
        if qs:
            self._last_qs = qs
        if self._last_mark and (now - self._last_mark).total_seconds() < 60:
            return
        self._last_mark = now
        day = now.astimezone(IST).date().isoformat()
        eq = self.equity(qs)
        with self.store._lock, self.store.db:
            self.store.db.execute("INSERT OR REPLACE INTO account_equity (acct, ts, equity, cash, open_value, n_open) "
                                  "VALUES (?,?,?,?,?,?)", (self.name, now.replace(second=0, microsecond=0).isoformat(), eq,
                                                          self.cash, eq - self.cash, len(self.positions)))
        start = self.day_start_equity(day)
        if eq < start * (1 - self.daily_loss_pct / 100) and not self.store.kv_get(self.k(f"halt_{day}")):
            self.store.kv_set(self.k(f"halt_{day}"), True)
            self.b.tg.send(f"🛑 Account {self.name}: daily loss limit hit (equity ₹{eq:,.0f}, day start ₹{start:,.0f}). "
                           f"No new entries today; open positions keep their stops.")

    # ---------- reporting ----------
    def report(self) -> str:
        capital = float(self.store.kv_get(self.k("capital"), 0.0))
        eq = self.equity(self._last_qs)                 # open positions at the latest bid (entry if never quoted)
        now = self.b.now() if hasattr(self.b, "now") else datetime.now(IST)     # the bridge's clock, not the PC's
        day = now.astimezone(IST).date().isoformat()
        start = self.day_start_equity(day)
        with self.store._lock:
            fills = self.store.db.execute("SELECT action, realized FROM account_fills WHERE substr(ts,1,10)=? AND acct=?",
                                          (day, self.name)).fetchall()
            dd = self.store.db.execute("SELECT MIN(equity), MAX(equity) FROM account_equity WHERE substr(ts,1,10)=? AND "
                                       "acct=?", (day, self.name)).fetchone()
        sells = [r for a, r in fills if a == "SELL"]
        lines = [f"💼 <b>Paper account {self.name}</b>  (started with ₹{capital:,.0f})",
                 f"<i>{self.settings_line()}</i>",
                 f"Equity <b>₹{eq:,.0f}</b>  ·  cash ₹{self.cash:,.0f}  ·  in positions ₹{eq - self.cash:,.0f}",
                 f"Today: <b>{'+' if eq >= start else '−'}₹{abs(eq - start):,.0f}</b> ({(eq / start - 1) * 100:+.2f}%)  ·  "
                 f"since start {'+' if eq >= capital else '−'}₹{abs(eq - capital):,.0f} ({(eq / capital - 1) * 100:+.2f}%)",
                 f"Exits today: {len(sells)} ({sum(r > 0 for r in sells)} with profit)  ·  open positions: {len(self.positions)}"]
        if dd and dd[0] is not None:
            lines.append(f"Day low/high of equity: ₹{dd[0]:,.0f} / ₹{dd[1]:,.0f}")
        if self.positions:
            x = self.exposure()
            lines.append(f"Risk now: {x['sell']} SELL / {x['buy']} BUY · if every stop is hit: −₹{x['at_risk']:,.0f} "
                         f"({x['at_risk'] / eq * 100:.1f}% of equity)")
        for p in self.positions.values():
            lines.append(f"• {p.symbol}: {p.rem_lots} of {p.lots} lots, bought at {p.entry:,.2f}")
        return "\n".join(lines)

    def summary_line(self) -> str:
        """One line for the side-by-side comparison of the strategy accounts."""
        eq = self.equity(self._last_qs)
        now = self.b.now() if hasattr(self.b, "now") else datetime.now(IST)
        day = now.astimezone(IST).date().isoformat()
        start, capital = self.day_start_equity(day), float(self.store.kv_get(self.k("capital"), 0.0))
        with self.store._lock:
            sells = [r for (r,) in self.store.db.execute("SELECT realized FROM account_fills WHERE substr(ts,1,10)=? AND "
                                                         "acct=? AND action='SELL'", (day, self.name))]
        return (f"• <b>{self.name}</b> ({self.strategy}): ₹{eq:,.0f} · today {'+' if eq >= start else '−'}₹{abs(eq - start):,.0f} "
                f"({(eq / start - 1) * 100:+.2f}%) · since start {(eq / capital - 1) * 100:+.2f}% · exits {len(sells)} "
                f"({sum(r > 0 for r in sells)} won) · open {len(self.positions)}")
