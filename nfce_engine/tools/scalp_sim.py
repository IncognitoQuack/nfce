"""SCALP-1 tick-replay simulator (../evidence/scalp_1_protocol.md, SHA-256 96f1bdd3…7803).

  ../nfce_bridge/.venv/bin/python tools/scalp_sim.py ../nfce_bridge/data/stream_YYYYMMDD.db [--strict]

Replays the shadow stream's cash-equity ticks in receive order: universe at 09:30 (spread ≤ 3 bp, top 30 by traded
value), book-imbalance signals, passive entries filled only on a strict trade-through within 30 s, exits by stop (8 bp,
marketable), target (12 bp, passive, trade-through), time (180 s) or 15:10; at most 2 open, 40 fills, a ₹10,000 daily
stop; every fill charged by gs/costs.equity_fill_fee. Paper research only.
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gs import costs as gcosts  # noqa: E402


@dataclass(frozen=True)
class Params:
    max_spread_bp: float = 3.0
    universe_n: int = 30
    i1: float = 0.60
    i25: float = 0.30
    ticket: float = 500_000.0
    entry_ttl_s: float = 30.0
    target_bp: float = 12.0
    stop_bp: float = 8.0
    time_stop_s: float = 180.0
    cooldown_s: float = 60.0
    max_open: int = 2
    max_fills: int = 40
    daily_stop_rs: float = 10_000.0
    book: float = 1_000_000.0
    entry_start: str = "09:30:00"
    entry_end: str = "15:00:00"
    flat_at: str = "15:10:00"
    tick_size: float = 0.05
    strict: bool = False


def imbalance(depth) -> tuple[float, float]:
    """(I1, I25) from [(bidP, bidQ, askP, askQ), ...]; nan when a side is empty."""
    if not depth:
        return math.nan, math.nan
    b1, a1 = float(depth[0][1] or 0), float(depth[0][3] or 0)
    i1 = (b1 - a1) / (b1 + a1) if b1 + a1 > 0 else math.nan
    w = [math.exp(-0.5 * (k - 1)) for k in range(2, 6)]
    bw = sum(wi * float(lv[1] or 0) for wi, lv in zip(w, depth[1:5]))
    aw = sum(wi * float(lv[3] or 0) for wi, lv in zip(w, depth[1:5]))
    i25 = (bw - aw) / (bw + aw) if bw + aw > 0 else math.nan
    return i1, i25


def load(db: Path) -> pd.DataFrame:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    t = pd.read_sql_query("SELECT recv_ts, key, ltp, bid1, bidq1, ask1, askq1, depth, vtt FROM tick "
                          "WHERE key LIKE 'NSE_EQ|%' ORDER BY recv_ts", con)
    con.close()
    t["t"] = pd.to_datetime(t["recv_ts"], format="ISO8601")
    t["hms"] = t["t"].dt.strftime("%H:%M:%S")
    return t


def universe(t: pd.DataFrame, p: Params = Params()) -> list[str]:
    w = t[(t["hms"] >= "09:15:00") & (t["hms"] < "09:30:00")].dropna(subset=["bid1", "ask1"])
    w = w[(w["bid1"] > 0) & (w["ask1"] >= w["bid1"])]
    if w.empty:
        return []
    mid = (w["bid1"] + w["ask1"]) / 2
    sp = ((w["ask1"] - w["bid1"]) / mid * 1e4).groupby(w["key"]).median()
    last = w.groupby("key").last()
    value = (last["vtt"].fillna(0) * last["ltp"].fillna(0))
    ok = sp[sp <= p.max_spread_bp].index
    return list(value.loc[value.index.intersection(ok)].sort_values(ascending=False).index[: p.universe_n])


@dataclass
class _Pos:
    side: int
    qty: int
    price: float
    t: datetime
    pending: bool = True
    fill_t: datetime | None = None
    mid_at_fill: float | None = None
    adverse_30s: float | None = None


def _fee(side: int, price: float, qty: int, t: datetime) -> float:
    return gcosts.equity_fill_fee(side, price, qty, t.date()).total


def simulate(t: pd.DataFrame, keys: list[str], p: Params = Params()) -> tuple[pd.DataFrame, dict]:
    t = t[t["key"].isin(set(keys))]
    t = t[(t["hms"] >= p.entry_start) & (t["hms"] <= p.flat_at)]
    book: dict[str, _Pos] = {}
    last_exit: dict[str, datetime] = {}
    trades, fills, realized, halted = [], 0, 0.0, False
    stats = {"signals": 0, "orders": 0, "cancelled": 0}

    def close(k, pos, px, when, why):
        nonlocal realized, halted
        gross = pos.side * (px - pos.price) * pos.qty
        fees = _fee(pos.side, pos.price, pos.qty, pos.fill_t) + _fee(-pos.side, px, pos.qty, when)
        net = gross - fees
        realized += net
        if realized <= -p.daily_stop_rs:
            halted = True
        trades.append({"key": k, "side": pos.side, "qty": pos.qty, "entry_t": pos.fill_t, "entry": pos.price,
                       "exit_t": when, "exit": px, "reason": why, "gross": gross, "fees": fees, "net": net,
                       "net_bp": net / (pos.price * pos.qty) * 1e4, "gross_bp": gross / (pos.price * pos.qty) * 1e4,
                       "adverse_30s_bp": pos.adverse_30s, "hold_s": (when - pos.fill_t).total_seconds()})
        last_exit[k] = when
        del book[k]

    for r in t.itertuples(index=False):
        k, now = r.key, r.t
        bid, ask, ltp = r.bid1, r.ask1, r.ltp
        pos = book.get(k)
        if pos is not None and not pos.pending and pos.adverse_30s is None and pos.mid_at_fill and bid and ask \
                and (now - pos.fill_t).total_seconds() >= 30:
            pos.adverse_30s = pos.side * (((bid + ask) / 2) - pos.mid_at_fill) / pos.mid_at_fill * 1e4
        if pos is not None and pos.pending:
            if (now - pos.t).total_seconds() > p.entry_ttl_s:
                del book[k]
                stats["cancelled"] += 1
            elif ltp and ((pos.side > 0 and ltp < pos.price) or (pos.side < 0 and ltp > pos.price)):
                if fills >= p.max_fills:
                    del book[k]
                    stats["cancelled"] += 1
                    continue
                pos.pending, pos.fill_t = False, now
                pos.mid_at_fill = (bid + ask) / 2 if bid and ask else None
                fills += 1
            continue
        if pos is not None:
            touch = bid if pos.side > 0 else ask
            stop_px = pos.price * (1 - pos.side * p.stop_bp / 1e4)
            tgt = pos.price * (1 + pos.side * p.target_bp / 1e4)
            extra = p.tick_size if p.strict else 0.0
            if r.hms >= p.flat_at and touch:
                close(k, pos, touch, now, "15:10 flat")
            elif touch and ((pos.side > 0 and touch <= stop_px) or (pos.side < 0 and touch >= stop_px)):
                close(k, pos, touch, now, "stop")
            elif ltp and ((pos.side > 0 and ltp > tgt + extra) or (pos.side < 0 and ltp < tgt - extra)):
                close(k, pos, tgt, now, "target")
            elif touch and (now - pos.fill_t).total_seconds() >= p.time_stop_s:
                close(k, pos, touch, now, "time")
            continue
        if halted or fills >= p.max_fills or r.hms > p.entry_end or len(book) >= p.max_open:
            continue
        if k in last_exit and (now - last_exit[k]).total_seconds() < p.cooldown_s:
            continue
        if not bid or not ask or r.depth is None:
            continue
        depth = json.loads(r.depth) if isinstance(r.depth, str) else r.depth
        i1, i25 = imbalance(depth)
        side = 1 if (i1 >= p.i1 and i25 >= p.i25) else -1 if (i1 <= -p.i1 and i25 <= -p.i25) else 0
        if side == 0:
            continue
        stats["signals"] += 1
        px = bid if side > 0 else ask
        qty = int(p.ticket // px)
        if qty < 1:
            continue
        book[k] = _Pos(side, qty, float(px), now)
        stats["orders"] += 1
    for k, pos in list(book.items()):                    # anything still open after the last tick: flat at last touch
        if pos.pending:
            continue
        last = t[t["key"] == k].iloc[-1]
        touch = last["bid1"] if pos.side > 0 else last["ask1"]
        close(k, pos, float(touch), last["t"], "end of data")
    tr = pd.DataFrame(trades)
    summ = stats | {"fills": fills, "trades": len(tr), "halted": halted,
                    "net_rs": float(tr["net"].sum()) if len(tr) else 0.0,
                    "unit_bp_per_day": float(tr["net"].sum()) / p.book * 1e4 if len(tr) else 0.0}
    if len(tr):
        summ |= {"fill_rate": fills / max(1, stats["orders"]), "hit": float((tr["net"] > 0).mean()),
                 "gross_bp": float(tr["gross_bp"].mean()), "fee_bp": float((tr["fees"] / (tr["entry"] * tr["qty"]) * 1e4).mean()),
                 "net_bp": float(tr["net_bp"].mean()),
                 "adverse_30s_bp": float(tr["adverse_30s_bp"].dropna().mean()) if tr["adverse_30s_bp"].notna().any() else None,
                 "exits": tr["reason"].value_counts().to_dict()}
    return tr, summ


def run(db: Path, strict: bool = False) -> dict:
    t = load(db)
    p = Params(strict=strict)
    keys = universe(t, p)
    gaps = t.groupby("key")["t"].diff().dt.total_seconds()
    tr, s = simulate(t, keys, p)
    return {"db": db.name, "universe": keys, "tick_gap_median_s": float(gaps.median()) if gaps.notna().any() else None,
            "summary": s}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    print(json.dumps(run(Path(args[0]), strict="--strict" in sys.argv), indent=1, default=str))
