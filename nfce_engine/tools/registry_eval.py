"""Score the pre-registered experiments (REGISTRY.md) against their frozen pass/fail rules (nfce/registry.py).

  python tools/registry_eval.py r2 --nifty NIFTY_fut_15m.csv --bank BANKNIFTY_fut_15m.csv
  python tools/registry_eval.py r3 --db ../nfce_bridge/data/bridge.db
  python tools/registry_eval.py r1 --db ../nfce_bridge/data/bridge.db --bars NIFTY_fut_60m.csv --futures-key "NSE_FO|..."

r2  CSVs of 15-minute continuous FUTURES bars with real volume (time, open, high, low, close, volume), ideally
    Jan 2021 onwards. Costs: the CURRENT (2026) schedule on every trade, one lot, two orders, plus the registered
    round-trip friction (1.5 Nifty / 4.0 Bank Nifty points).
r3  the bridge database after live paper trading: closed EXECUTABLE-book trades, PASS vs shadow VETO.
r1  the bridge database (option_quotes, recorded every chain refresh; quotes for the futures leg) and 60-minute
    NIFTY bars covering the same sessions. Each H1 ORB-mid signal is executed twice from recorded quotes:
    1-ITM option (ask in, bid out, nfce/options_exec.py) and the front future (ask/bid, same timestamps).
    Exit time: the close of the bar that triggered the H1 exit, capped at 15:25 IST (the option must still trade).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce import costs  # noqa: E402
from nfce.data import load_csv  # noqa: E402
from nfce.options_exec import execute  # noqa: E402
from nfce.registry import R2_FRICTION_RT_PTS, judge_r1, judge_r2, judge_r3  # noqa: E402
from nfce.simple import orb, orb15_ha  # noqa: E402

LOT = {"NIFTY": 65, "BANKNIFTY": 30}


def r2(paths: dict[str, Path]) -> str:
    per = {}
    for instr, p in paths.items():
        bars, info = load_csv(p, 15)
        out = []
        for t in orb15_ha(bars, instr):
            fees = costs.futures_cost_points(t.entry, t.exit, t.side, costs.CURRENT, LOT[instr], 1, t.orders,
                                             R2_FRICTION_RT_PTS[instr] / 2)
            net = t.pnl - fees
            out.append((pd.Timestamp(t.date).year, net / t.risk, net * LOT[instr]))
        per[instr] = out
        print(f"{instr}: {p.name} sha256 {info['sha256'][:12]} {info['first'][:10]}..{info['last'][:10]}, {len(out)} trades")
    return judge_r2(per).text()


def r3(db: Path) -> str:
    rows = sqlite3.connect(db).execute(
        "SELECT decision, net_pts, r_pts, substr(opened, 1, 10) FROM paper_trades "
        "WHERE book='executable' AND status='CLOSED' AND r_pts > 0").fetchall()
    p = [(n / r, d) for dec, n, r, d in rows if dec == "PASS"]
    v = [(n / r, d) for dec, n, r, d in rows if dec == "VETO"]
    return judge_r3([x for x, _ in p], [x for x, _ in v], [d for _, d in p], [d for _, d in v]).text()


def _futures_quotes(con, futures_key: str | None) -> pd.DataFrame:
    """Front-future quotes with the contract that was front ON THAT DAY (bridge table `contracts`, FIX H08).
    Old databases without that table need an explicit --futures-key (one contract; no rolls)."""
    fq = pd.read_sql("SELECT ts, key, bid, ask FROM quotes WHERE key LIKE 'NSE_FO%'", con)
    fq["time"] = pd.to_datetime(fq.ts, utc=True).dt.tz_convert("Asia/Kolkata")
    fq["day"] = fq.time.dt.strftime("%Y-%m-%d")
    try:
        c = pd.read_sql("SELECT key, day FROM contracts WHERE root='NIFTY'", con)
        fq = fq.merge(c, on=["key", "day"])                   # only the contract that was front that day
    except Exception:
        if not futures_key:
            raise SystemExit("this database has no `contracts` table: pass --futures-key")
        fq = fq[fq.key == futures_key]
    return fq.sort_values("time")


def _fill(q: pd.DataFrame, t: pd.Timestamp, not_before: pd.Timestamp, gap_s: int) -> pd.Series | None:
    """First valid quote at or after max(t, not_before), within gap_s of t, on t's session."""
    a = q[(q.time >= max(t, not_before)) & (q.bid > 0) & (q.ask >= q.bid)].head(1)
    if a.empty or (a.time.iloc[0] - t).total_seconds() > gap_s or a.day.iloc[0] != t.strftime("%Y-%m-%d"):
        return None
    return a.iloc[0]


def r1(db: Path, bars_path: Path, futures_key: str | None = None, lot: int = 65, gap_s: int = 60) -> str:
    con = sqlite3.connect(db)
    oq = pd.read_sql("SELECT ts, expiry, strike, type, bid, ask FROM option_quotes WHERE underlying LIKE '%Nifty 50%'", con)
    if oq.empty:
        return "R1: INCONCLUSIVE (no recorded option quotes in the database)"
    fq = _futures_quotes(con, futures_key)
    if fq.empty:
        return "R1: INCONCLUSIVE (no recorded futures quotes in the database)"
    oq["time"] = pd.to_datetime(oq.ts, utc=True).dt.tz_convert("Asia/Kolkata")
    oq["expiry"] = pd.to_datetime(oq.expiry).dt.date
    bars, _ = load_csv(bars_path, 60)
    first = oq.time.min().normalize()
    trades = [t for t in orb(bars, "mid") if pd.Timestamp(t.entry_time) >= first]
    days = sorted({d.date() for d in bars.index.normalize()})
    sigs = []
    for t in trades:
        dec = t.entry_time + pd.Timedelta(minutes=60)
        ex = min(t.exit_time + pd.Timedelta(minutes=60), t.exit_time.normalize() + pd.Timedelta(hours=15, minutes=25))
        sigs.append({"decision_time": dec, "exit_time": ex, "side": t.side, "spot": t.entry, "risk": t.risk})
    fills = execute(sigs, oq, days, lot_units=lot, max_quote_gap_s=gap_s)
    opt_r, fut_r, stress_r, inr, sess, skipped = [], [], [], [], [], 0
    for s, f in zip(sigs, fills):
        t_in = s["decision_time"] + pd.Timedelta(seconds=5)
        a = _fill(fq, t_in, t_in, gap_s)
        b = _fill(fq, s["exit_time"], a.time if a is not None else s["exit_time"], gap_s) if a is not None else None
        if f.skipped or a is None or b is None:              # identical missing-data rule for both legs
            skipped += 1
            continue
        side = s["side"]
        e_px = a.ask if side > 0 else a.bid
        x_px = b.bid if side > 0 else b.ask
        fut_net = side * (x_px - e_px) * lot - costs.futures_fees(e_px, x_px, side, lot, s["decision_time"].date()).total
        r_inr = s["risk"] * lot
        opt_r.append(f.net_inr / r_inr)
        stress_r.append(f.stressed_net_inr / r_inr)
        fut_r.append(fut_net / r_inr)
        inr.append(f.net_inr)
        sess.append(s["decision_time"].date().isoformat())
    return judge_r1(opt_r, fut_r, skipped, sess, stress_r, inr).text()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("experiment", choices=["r1", "r2", "r3"])
    ap.add_argument("--db", type=Path)
    ap.add_argument("--bars", type=Path)
    ap.add_argument("--futures-key")
    ap.add_argument("--nifty", type=Path)
    ap.add_argument("--bank", type=Path)
    a = ap.parse_args()
    if a.experiment == "r2":
        print(r2({"NIFTY": a.nifty, "BANKNIFTY": a.bank}))
    elif a.experiment == "r3":
        print(r3(a.db))
    else:
        print(r1(a.db, a.bars, a.futures_key))
