"""SH-1 shadow replay (evidence/shadow_hold_1_protocol.md): "book at +0.5R, no stop, hold a loser until it is back at
entry, else 15:15" on the day's account option positions, from the stream's recorded ticks. Read-only.
usage (from nfce_bridge/): PYTHONPATH=. .venv/bin/python ops/shadow_hold.py [YYYY-MM-DD]"""
import json
import sqlite3
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

from bridge.costs import option_fees

IST = ZoneInfo("Asia/Kolkata")
BOOK_R, CUTOFF = 0.5, "15:15:00"


def replay(ticks: list, entry: float, r: float) -> tuple[str, float | None, str | None]:
    """ticks: [(ist_iso, bid)] after the entry, in order. Returns (how, exit_bid, ts); exit None while still open."""
    was_below, last = False, (None, None)
    for ts, bid in ticks:
        if ts[11:19] > CUTOFF:
            break
        last = (ts, bid)
        if bid >= entry + BOOK_R * r:
            return "BOOK", bid, ts
        if bid <= entry - r:
            was_below = True
        elif was_below and bid >= entry:
            return "RECOVER", bid, ts
    if last[0] and last[0][11:19] >= "15:14:00":
        return "15:15", last[1], last[0]
    return "open", last[1], last[0]


def main(day: str) -> None:
    con = sqlite3.connect("file:data/nfce.db?mode=ro", uri=True)
    st = sqlite3.connect(f"file:data/stream_{day.replace('-', '')}.db?mode=ro", uri=True)
    rows, tot = [], {"sh": 0.0, "acct": 0.0}
    for acct, sid, state in con.execute("SELECT acct, sid, state FROM account_positions"):
        p = json.loads(state)
        if datetime.fromisoformat(p["opened"]).astimezone(IST).date().isoformat() != day:
            continue
        units = p["lots"] * p["lot_units"]
        r = p["entry"] - p["opt_sl"] if p.get("opt_sl") else None
        t0 = datetime.fromisoformat(p["opened"]).astimezone(IST)
        ticks = []
        for recv, bid in st.execute("SELECT recv_ts, bid1 FROM tick WHERE key=? AND bid1>0 ORDER BY recv_ts", (p["key"],)):
            ts = datetime.fromisoformat(recv).astimezone(IST)
            if ts > t0:
                ticks.append((ts.isoformat(), bid))
        how, px, ts = replay(ticks, p["entry"], r) if r else ("no R", None, None)
        sh = None
        if px is not None:
            sh = (px - p["entry"]) * units - option_fees(p["entry"], px, units, date.fromisoformat(day)).total
        fills = con.execute("SELECT COALESCE(SUM(realized),0), COALESCE(SUM(fees),0) FROM account_fills "
                            "WHERE acct=? AND sid=?", (acct, sid)).fetchone()
        acct_net = fills[0] if p.get("status", "OPEN") != "OPEN" else None
        rows.append((acct, p["symbol"], p["entry"], r, how, px, (ts or "")[11:19], sh, acct_net, p.get("status")))
        if sh is not None and acct_net is not None:
            tot["sh"] += sh
            tot["acct"] += acct_net
    print(f"SH-1 shadow ({day}, as of {datetime.now(IST):%H:%M:%S}): book at +{BOOK_R}R, no stop, hold to entry, else 15:15")
    print("acct | position | entry | R | SH-1 exit | at | SH-1 net ₹ (open: mark) | account | account net ₹")
    for a, s, e, r, how, px, ts, sh, an, stt in rows:
        print(f"{a} | {s} | {e} | {r and round(r, 2)} | {how} {px} | {ts} | "
              f"{'' if sh is None else round(sh)} | {stt} | {'' if an is None else round(an)}")
    print(f"closed on both sides: SH-1 ₹{tot['sh']:,.0f} vs accounts ₹{tot['acct']:,.0f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else datetime.now(IST).date().isoformat())
