"""End-of-day analysis report (read-only): writes ~/Downloads/nfce/reports/EOD_YYYY-MM-DD.md.

    PYTHONPATH=. .venv/bin/python ops/eod_report.py [YYYY-MM-DD]

Sections, each computed on its own so one missing source never stops the report:
  1. market context (NIFTY move from the recorded chain spot, VIX from the daily file or the stream);
  2. accounts today and since inception (return, max drawdown, best/worst day, share of positive days);
  3. P&L attribution of every signal book: by book and leg, by direction, by hour, by exit reason;
  4. costs: fees paid and their share of gross;
  5. research tracks: GS by branch, OVN v2 / v3, OPX-1 gate, SCALP-1 on the day's stream ticks.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "nfce_engine"))
from ops import desk  # noqa: E402

DATA = ROOT / "data"
REPORTS = ROOT.parent / "reports"
START_CAPITAL = 500_000.0


def capital(con: sqlite3.Connection, acct: str) -> float:
    """The account's own starting capital (Account stores it as account_<name>_capital); ₹5 L for older ones."""
    r = con.execute("SELECT v FROM kv WHERE k=?", (f"account_{acct}_capital",)).fetchone()
    try:
        return float(json.loads(r[0])) if r else START_CAPITAL
    except (TypeError, ValueError):
        return START_CAPITAL


def performance(con: sqlite3.Connection, upto: str) -> dict:
    """Per account: daily closing equity → since-inception stats (paper, after costs)."""
    out = {}
    for (acct,) in con.execute("SELECT DISTINCT acct FROM account_equity"):
        rows = con.execute("SELECT substr(ts,1,10) d, equity FROM account_equity WHERE acct=? AND substr(ts,1,10) <= ? "
                           "AND ts IN (SELECT max(ts) FROM account_equity WHERE acct=? GROUP BY substr(ts,1,10)) "
                           "ORDER BY d", (acct, upto, acct)).fetchall()
        if not rows:
            continue
        cap = capital(con, acct)                         # G20 starts at ₹20 L (28 Oct)
        eq = [cap] + [r[1] for r in rows]
        daily = [b - a for a, b in zip(eq, eq[1:])]
        peak, mdd = eq[0], 0.0
        for e in eq:
            peak = max(peak, e)
            mdd = min(mdd, (e - peak) / peak)
        out[acct] = {"days": len(rows), "equity": eq[-1], "capital": cap, "total_pct": (eq[-1] / cap - 1) * 100,
                     "max_dd_pct": mdd * 100, "best_day": max(daily), "worst_day": min(daily),
                     "pos_days": sum(d > 0 for d in daily), "flat_days": sum(d == 0 for d in daily)}
    return out


def attribution(con: sqlite3.Connection, day: str) -> dict:
    nxt = desk._next(day)
    rows = []
    for r in con.execute("SELECT book, opened, side, status, exit_reason, net_pts, state FROM paper_trades "
                         "WHERE opened >= ? AND opened < ?", (day, nxt)):
        s = json.loads(r[6])
        if r[3] == "OPEN":
            continue
        rows.append({"book": r[0], "leg": "futures", "hour": r[1][11:13], "dir": "BUY" if r[2] == 1 else "SELL",
                     "exit": (r[4] or "").split(" ")[0], "net": (r[5] or 0) * s.get("lot_units", 1) * s.get("lots", 1)})
    for r in con.execute("SELECT book, opened, type, status, reason, net_inr FROM option_trades WHERE opened >= ? "
                         "AND opened < ?", (day, nxt)):
        if r[3] == "OPEN":
            continue
        rows.append({"book": r[0], "leg": "options", "hour": (r[1] or "")[11:13],
                     "dir": "BUY" if r[2] == "CE" else "SELL", "exit": (r[4] or "").split(" ")[0], "net": r[5] or 0.0})

    def group(keyf):
        g: dict = {}
        for x in rows:
            k = keyf(x)
            d = g.setdefault(k, {"n": 0, "won": 0, "net": 0.0})
            d["n"] += 1
            d["won"] += x["net"] > 0
            d["net"] += x["net"]
        return dict(sorted(g.items()))
    return {"by_book": group(lambda x: f"{x['book']} {x['leg']}"),
            "by_direction": group(lambda x: f"{x['leg']} {x['dir']}"),
            "by_hour": group(lambda x: f"{x['leg']} {x['hour']}:00"),
            "by_exit": group(lambda x: f"{x['leg']} {x['exit'] or '?'}")}


def costs_today(con: sqlite3.Connection, day: str) -> dict:
    r = con.execute("SELECT COUNT(*), COALESCE(SUM(fees),0), COALESCE(SUM(realized),0) FROM account_fills "
                    "WHERE ts >= ? AND ts < ?", (day, desk._next(day))).fetchone()
    gross = r[2] + r[1]
    return {"fills": r[0], "fees": r[1], "net_realised": r[2], "gross_realised": gross,
            "fees_share_of_gross": (r[1] / abs(gross)) if gross else None}


def market(day: str) -> dict:
    out = {}
    f = DATA / f"study_chain_{day.replace('-', '')}.db"
    if f.exists():
        con = desk.ro(f)
        r = con.execute("SELECT min(ts), max(ts) FROM chain WHERE underlying='NIFTY' AND ts >= ?", (f"{day}T09:15",)).fetchone()
        if r[0]:
            first = con.execute("SELECT spot FROM chain WHERE underlying='NIFTY' AND ts=? LIMIT 1", (r[0],)).fetchone()[0]
            last = con.execute("SELECT spot FROM chain WHERE underlying='NIFTY' AND ts <= ? ORDER BY ts DESC LIMIT 1",
                               (f"{day}T15:15",)).fetchone()[0]
            out |= {"nifty_first": first, "nifty_1515": last, "nifty_move_pct": (last / first - 1) * 100}
        con.close()
    s = DATA / f"stream_{day.replace('-', '')}.db"
    if s.exists():
        con = desk.ro(s)
        r = con.execute("SELECT ltp, cp FROM tick WHERE key='NSE_INDEX|India VIX' ORDER BY recv_ts DESC LIMIT 1").fetchone()
        if r:
            out |= {"vix": r[0], "vix_prev_close": r[1]}
        con.close()
    return out


def research(day: str) -> dict:
    out: dict = {"gs": desk.gs_summary()}
    d = date.fromisoformat(day)
    try:
        from tools import opx_gate, overnight_options as ovn, overnight_v3
        v2 = ovn.score_v2()
        out["ovn_v2"] = v2[v2["day"] == day].to_dict("records")
        v3 = overnight_v3.score_v3()
        out["ovn_v3"] = v3[v3["day"] == day].to_dict("records") if len(v3) else []
        opx = opx_gate.score_opx()
        out["opx_1"] = opx[opx["day"] == day][["day", "status", "gate", "ratio", "u_opx"]].to_dict("records")
    except Exception as exc:
        out["overnight_error"] = f"{type(exc).__name__}: {exc}"
    s = DATA / f"stream_{d:%Y%m%d}.db"
    if s.exists():
        try:
            from tools import scalp_sim
            out["scalp_1"] = scalp_sim.run(s)
            out["scalp_1_strict"] = scalp_sim.run(s, strict=True)["summary"]
        except Exception as exc:
            out["scalp_error"] = f"{type(exc).__name__}: {exc}"
    return out


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc(limit=2)}


def manual_review(con: sqlite3.Connection, day: str, stream: Path | None = None) -> dict:
    """The owner's own trades: every position of a `manual` account opened today, and every MANUAL override in the
    strategy accounts. For each: held time, result after costs, the best bid while held, how much was given back,
    and whether a system signal on the same underlying and direction came in the 15 minutes before the buy."""
    nxt = desk._next(day)
    strat = desk._strategies()
    manual = [a for a, st in strat.items() if st == "manual"]
    stream = stream or desk.stream_path(day)
    out = []
    for acct, sid, state in con.execute("SELECT acct, sid, state FROM account_positions") if manual else []:
        p = json.loads(state)
        if acct not in manual or not (day <= p.get("opened", "") < nxt):
            continue
        fills = con.execute("SELECT ts, action, lots, price, realized, reason FROM account_fills WHERE acct=? AND sid=? "
                            "ORDER BY id", (acct, sid)).fetchall()
        sells = [f for f in fills if f[1] == "SELL"]
        t_in = datetime.fromisoformat(p["opened"])
        t_out = datetime.fromisoformat(sells[-1][0]) if sells else None
        peak = None
        if stream.exists() and p.get("key"):
            sc = desk.ro(stream)
            try:
                r = sc.execute("SELECT max(bid1) FROM tick WHERE key=? AND recv_ts>=? AND recv_ts<=? AND bid1>0",
                               (p["key"], p["opened"], sells[-1][0] if sells else nxt)).fetchone()
                peak = r[0] if r else None
            finally:
                sc.close()
        und, side = p["symbol"].split()[0], p.get("side", 1)
        sig = con.execute("SELECT opened, book FROM paper_trades WHERE underlying=? AND side=? AND opened<=? AND opened>=? "
                          "ORDER BY opened DESC LIMIT 1",
                          (und, side, p["opened"], (t_in - timedelta(minutes=15)).isoformat())).fetchone()
        units = p["lots"] * p["lot_units"]
        out.append({"acct": acct, "symbol": p["symbol"], "lots": p["lots"], "entry": p["entry"],
                    "bought": desk._ist(p["opened"])[-5:], "sold": desk._ist(sells[-1][0])[-5:] if sells else "open",
                    "held_min": round((t_out - t_in).total_seconds() / 60) if t_out else None,
                    "net": sum(f[4] for f in sells), "exit": sells[-1][5] if sells else "",
                    "peak_rs": (peak - p["entry"]) * units if peak else None,
                    "signal": f"{sig[1]} {desk._ist(sig[0])[-5:]}" if sig else None})
    overrides = [{"acct": r[0], "t": desk._ist(r[1])[-5:], "symbol": r[2], "lots": r[3], "net": r[4], "reason": r[5]}
                 for r in con.execute("SELECT acct, ts, symbol, lots, realized, reason FROM account_fills WHERE ts>=? AND "
                                      "ts<? AND reason LIKE 'MANUAL%'", (day, nxt)) if r[0] not in manual]
    return {"trades": out, "overrides": overrides}


def build(day: str, db: Path = DATA / "nfce.db") -> dict:
    con = desk.ro(db)
    try:
        rep = {"day": day, "generated": datetime.now().isoformat(timespec="seconds"),
               "market": _safe(market, day), "accounts": _safe(desk.accounts, con, day),
               "performance": _safe(performance, con, day), "books": _safe(desk.books, con, day),
               "attribution": _safe(attribution, con, day), "costs": _safe(costs_today, con, day),
               "manual": _safe(manual_review, con, day)}
    finally:
        con.close()
    rep["research"] = _safe(research, day)
    rep["signal_context"] = _safe(signal_context_summary, day)
    return rep


def signal_context_summary(day: str) -> dict:
    from ops import signal_context
    return signal_context.summary(signal_context.build(day))


def _rs(x):
    return "—" if x is None else (f"−₹{abs(x):,.0f}" if x < 0 else f"₹{x:,.0f}")


def render(rep: dict) -> str:
    L = [f"# End-of-day analysis: {rep['day']}", "", f"_Generated {rep['generated']}. Paper trading only; after all costs._", ""]
    m = rep["market"]
    L += ["## 1. Market", ""]
    if m.get("nifty_move_pct") is not None:
        L.append(f"- NIFTY {m['nifty_first']:,.2f} → {m['nifty_1515']:,.2f} by 15:15 (**{m['nifty_move_pct']:+.2f}%**).")
    if m.get("vix") is not None:
        L.append(f"- India VIX {m['vix']:.2f} (previous close {m.get('vix_prev_close') or 0:.2f}).")
    if m.get("error") or len(L) == 6:
        L.append(f"- Market data not available: {m.get('error', 'no chain or stream file')}.")
    L += ["", "## 2. Accounts", "", "| Account | Today | Equity | Since start | Max drawdown | Best / worst day | Positive days |",
          "|---|---|---|---|---|---|---|"]
    perf = rep["performance"] if isinstance(rep["performance"], dict) else {}
    for a in rep["accounts"] if isinstance(rep["accounts"], list) else []:
        p = perf.get(a["name"], {})
        L.append(f"| {a['name']} ({a['strategy']}) | {_rs(a['day_pnl'])} | {_rs(a['equity'])} | "
                 f"{p.get('total_pct', 0):+.2f}% | {p.get('max_dd_pct', 0):.2f}% | {_rs(p.get('best_day'))} / "
                 f"{_rs(p.get('worst_day'))} | {p.get('pos_days', 0)} of {p.get('days', 0)} |")
    c = rep["costs"]
    L += ["", f"Fills {c.get('fills', 0)}, fees {_rs(c.get('fees'))}, realised {_rs(c.get('net_realised'))}"
          + (f", fees = {c['fees_share_of_gross'] * 100:.0f}% of gross." if c.get("fees_share_of_gross") else "."), ""]
    L += ["## 3. Signal books: attribution (closed trades)", ""]
    at = rep["attribution"] if isinstance(rep["attribution"], dict) else {}
    for title, key in (("By book", "by_book"), ("By direction", "by_direction"), ("By hour opened", "by_hour"),
                       ("By exit", "by_exit")):
        g = at.get(key, {})
        if not g:
            continue
        L += [f"**{title}**", "", "| Group | Trades | Won | Net |", "|---|---|---|---|"]
        L += [f"| {k} | {v['n']} | {v['won']} | {_rs(v['net'])} |" for k, v in g.items()]
        L.append("")
    r = rep["research"] if isinstance(rep["research"], dict) else {}
    L += ["## 4. Research tracks", ""]
    gs = r.get("gs", {})
    if gs.get("available"):
        L += ["**GS (own ₹5 L book)**", "", "| Branch | Fills | Expired | Net |", "|---|---|---|---|"]
        L += [f"| {b['branch']} | {b['fills']} | {b['expired']} | {_rs(b['net']) if b['flat'] else 'open'} |"
              for b in gs["branches"]]
        L.append("")
    for k, title in (("ovn_v2", "OVN v2"), ("ovn_v3", "OVN v3"), ("opx_1", "OPX-1")):
        rows = r.get(k)
        if rows:
            x = rows[0]
            ratio = x.get("ratio")
            ratio_txt = f"{ratio:.2f}" if isinstance(ratio, (int, float)) and ratio == ratio else "—"
            extra = f", gate {x.get('gate')} (ratio {ratio_txt})" if k == "opx_1" else ""
            L.append(f"- **{title}:** {x.get('status')}{extra}; units {x.get('units', x.get('u_opx'))}")
    if r.get("overnight_error"):
        L.append(f"- Overnight scoring error: {r['overnight_error']}")
    sc = r.get("scalp_1")
    if sc:
        s = sc["summary"]
        L += ["", "**SCALP-1 (tick replay, locked protocol)**", "",
              f"- Universe {len(sc['universe'])} stocks; median tick gap {sc.get('tick_gap_median_s')} s.",
              f"- Signals {s.get('signals')}, orders {s.get('orders')}, fills {s.get('fills')} "
              f"(fill rate {s.get('fill_rate', 0):.0%}), trades {s.get('trades')}.",
              f"- Net {_rs(s.get('net_rs'))} = {s.get('unit_bp_per_day', 0):+.1f} bp/day of ₹10 L; per trade gross "
              f"{s.get('gross_bp', 0):+.1f} bp, fees {s.get('fee_bp', 0):.1f} bp, net {s.get('net_bp', 0):+.1f} bp; "
              f"hit {s.get('hit', 0):.0%}; adverse selection 30 s {s.get('adverse_30s_bp')} bp.",
              f"- Exits: {s.get('exits')}. Strict variant net {_rs(r.get('scalp_1_strict', {}).get('net_rs'))}."]
    elif r.get("scalp_error"):
        L.append(f"- SCALP-1 error: {r['scalp_error']}")
    ctx = rep.get("signal_context")
    if isinstance(ctx, dict) and not ctx.get("error"):
        L += ["", "## 5. Signal context (shadow; outcomes deliberately not joined)", "",
              f"- {ctx['signals']} signals: stream context {ctx['with_stream']}, options context {ctx['with_options']}, "
              f"in the morning news brief {ctx.get('in_morning_brief', 0)} (with results numbers "
              f"{ctx.get('with_results_numbers', 0)}), results meeting today {ctx['results_today']}.",
              f"- Aligned with the signal's side: order book {ctx['book_aligned']}, NIFTY {ctx['market_aligned']}, "
              f"breadth {ctx['breadth_aligned']}. Sector: {ctx['sector']}.",
              "- Stored in `nfce_bridge/data/signal_context.db`. A locked protocol must be registered BEFORE these are "
              "joined to the signals' results."]
    mr = rep.get("manual")
    if isinstance(mr, dict) and not mr.get("error") and (mr["trades"] or mr["overrides"]):
        T = mr["trades"]
        L += ["", "## 6. Your manual trades (MAN) and overrides", ""]
        if T:
            done = [t for t in T if t["held_min"] is not None]
            L += [f"- {len(T)} trades: net {_rs(sum(t['net'] for t in T))} after costs; won {sum(t['net'] > 0 for t in T)}, "
                  f"lost {sum(t['net'] <= 0 for t in done)}; median hold "
                  f"{sorted(t['held_min'] for t in done)[len(done) // 2] if done else '—'} min; "
                  f"{sum(1 for t in T if t['signal'])} followed a system signal (same underlying and direction, ≤ 15 min before).",
                  "", "| Bought | Sold | Contract | Lots | Entry | Net | Best open P&L while held | Given back | Held | Followed | Exit |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
            for t in T:
                gb = (t["peak_rs"] - t["net"]) if t["peak_rs"] is not None and t["held_min"] is not None else None
                L.append(f"| {t['bought']} | {t['sold']} | {t['symbol']} | {t['lots']} | {t['entry']:,.2f} | {_rs(t['net'])} | "
                         f"{_rs(t['peak_rs'])} | {_rs(gb)} | {t['held_min'] if t['held_min'] is not None else '—'} min | "
                         f"{t['signal'] or 'own idea'} | {t['exit']} |")
        if mr["overrides"]:
            L += ["", "Manual overrides in the strategy accounts (kept out of their strategy scores):", ""]
            L += [f"- {o['t']} {o['acct']} {o['symbol']} ×{o['lots']}: {_rs(o['net'])} ({o['reason']})" for o in mr["overrides"]]
    errs = [k for k in ("market", "accounts", "performance", "books", "attribution", "costs", "research", "signal_context", "manual")
            if isinstance(rep.get(k), dict) and rep[k].get("error")]
    if errs:
        L += ["", "## Data problems", ""] + [f"- {k}: {rep[k]['error']}" for k in errs]
    return "\n".join(L) + "\n"


def main(day: str | None = None) -> Path:
    day = day or date.today().isoformat()
    rep = build(day)
    REPORTS.mkdir(exist_ok=True)
    path = REPORTS / f"EOD_{day}.md"
    path.write_text(render(rep))
    return path


if __name__ == "__main__":
    print(main(sys.argv[1] if len(sys.argv) > 1 else None))
