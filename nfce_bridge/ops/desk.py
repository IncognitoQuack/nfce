"""NFCE trading desk: a live monitoring screen and control desk (a separate process from the bridge). It reads the
databases read-only; its only actions are relayed to the bridge's local admin API (bridge/admin_api.py), which audits
them. On the Wi-Fi (--lan) every data or control request needs the VIEW or CONTROL token; this Mac needs none.

    PYTHONPATH=. .venv/bin/python ops/desk.py [--port 8001] [--day 2026-10-27]

Open http://127.0.0.1:8001. It reads data/nfce.db and data/gs.db through SQLite read-only URIs, the bridge's /health
on port 8000, the Upstox token file and the battery. The page refreshes every 5 seconds.

Panels, the way trading firms lay out a desk: system status (feeds, token, power, GS), the six accounts with intraday
equity curves, limit utilisation with traffic lights (daily loss, open positions, premium deployed, the give-back stop,
the loss-streak pause), P&L by book (attribution), the signal blotter, the fill blotter with fees (transaction-cost
analysis), the GS engine, the message audit trail and the research scorecard.
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import Request   # module level: the routes' string annotations must resolve here

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB, GSDB = ROOT / "data" / "nfce.db", ROOT / "data" / "gs.db"
SCORECARD = ROOT.parent / "evidence" / "scorecard.json"
IST = timezone(timedelta(hours=5, minutes=30))
LIMITS = {"concentrated": dict(risk_pct=5.0, loss_pct=10.0, max_open=3, deploy_pct=90.0)}
BASE = dict(risk_pct=1.0, loss_pct=3.0, max_open=4, deploy_pct=60.0)
DG_PEAK_R = 2.0


def ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
    con.row_factory = sqlite3.Row
    return con


def _strategies() -> dict:
    """ACCOUNTS=5L:500000,CONC:500000:concentrated,... from .env (names and strategies only)."""
    out = {}
    try:
        for line in (ROOT / ".env").read_text().splitlines():
            if line.startswith("ACCOUNTS="):
                for item in line.split("=", 1)[1].split(","):
                    parts = item.strip().split(":")
                    if parts and parts[0]:
                        out[parts[0]] = parts[2] if len(parts) > 2 else "base"
    except OSError:
        pass
    return out


def accounts(con: sqlite3.Connection, day: str, strategies: dict | None = None) -> list[dict]:
    strategies = strategies if strategies is not None else _strategies()
    names = [r[0] for r in con.execute("SELECT DISTINCT acct FROM account_equity ORDER BY acct")]
    order = list(strategies) + [n for n in names if n not in strategies]
    out = []
    for name in [n for n in order if n in names]:
        strat = strategies.get(name, "base")
        lim = LIMITS.get(strat, BASE)
        prev = con.execute("SELECT equity FROM account_equity WHERE acct=? AND ts < ? ORDER BY ts DESC LIMIT 1",
                           (name, day)).fetchone()
        curve = [(r["ts"][11:16], r["equity"]) for r in con.execute(
            "SELECT ts, equity FROM account_equity WHERE acct=? AND ts >= ? AND ts < ? ORDER BY ts",
            (name, day, _next(day)))]
        last = con.execute("SELECT equity, cash, open_value, n_open FROM account_equity WHERE acct=? ORDER BY ts DESC "
                           "LIMIT 1", (name,)).fetchone()
        start_eq = prev["equity"] if prev else (curve[0][1] if curve else (last["equity"] if last else 0.0))
        eq = curve[-1][1] if curve else (last["equity"] if last else start_eq)
        open_value = last["open_value"] if last else 0.0
        n_open = last["n_open"] if last else 0
        fills = con.execute("SELECT COUNT(*) n, COALESCE(SUM(fees),0) fees, COALESCE(SUM(realized),0) realized, "
                            "COALESCE(SUM(CASE WHEN realized > 0 THEN 1 ELSE 0 END),0) won, "
                            "COALESCE(SUM(CASE WHEN realized != 0 THEN 1 ELSE 0 END),0) exits "
                            "FROM account_fills WHERE acct=? AND ts >= ? AND ts < ?", (name, day, _next(day))).fetchone()
        day_pnl = eq - start_eq
        risk_rs = start_eq * lim["risk_pct"] / 100
        loss_cap = start_eq * lim["loss_pct"] / 100
        streak = _kv(con, f"account_{name}_streak_{day}") or 0
        dg = _kv(con, f"account_{name}_dg_{day}") or {}
        out.append({
            "name": name, "strategy": strat, "equity": eq, "start_equity": start_eq, "day_pnl": day_pnl,
            "since_start_pct": None, "open": n_open, "open_value": open_value, "fills": fills["n"],
            "fees": fills["fees"], "realized": fills["realized"], "exits": fills["exits"], "won": fills["won"],
            "curve": curve,
            "limits": {
                "daily_loss": {"used": max(0.0, -day_pnl) / loss_cap if loss_cap else 0.0, "cap": loss_cap},
                "open": {"used": n_open / lim["max_open"], "cap": lim["max_open"]},
                "deploy": {"used": (open_value / eq) / (lim["deploy_pct"] / 100) if eq else 0.0, "cap": lim["deploy_pct"]},
                "give_back": {"armed_at": DG_PEAK_R * risk_rs, "peak": dg.get("peak", 0.0) if isinstance(dg, dict) else 0.0,
                              "halted": bool(isinstance(dg, dict) and dg.get("halt"))},
                "streak": {"losses": streak, "pause_at": 3},
            },
            "paused": bool(_kv(con, f"account_{name}_paused")),
            "capital": float(_kv(con, f"account_{name}_capital") or 500_000)})
    return out


def books(con: sqlite3.Connection, day: str) -> list[dict]:
    rows = {}
    for r in con.execute("SELECT book, status, state, net_pts FROM paper_trades WHERE opened >= ? AND opened < ?",
                         (day, _next(day))):
        s = json.loads(r["state"])
        mult = s.get("lot_units", 1) * s.get("lots", 1)
        b = rows.setdefault((r["book"], "futures"), {"book": r["book"], "leg": "futures", "n": 0, "open": 0, "won": 0,
                                                     "closed_pnl": 0.0})
        b["n"] += 1
        if r["status"] == "OPEN":
            b["open"] += 1
        else:
            v = (r["net_pts"] or 0) * mult
            b["closed_pnl"] += v
            b["won"] += v > 0
    for r in con.execute("SELECT book, status, net_inr FROM option_trades WHERE opened >= ? AND opened < ?",
                         (day, _next(day))):
        b = rows.setdefault((r["book"], "options"), {"book": r["book"], "leg": "options", "n": 0, "open": 0, "won": 0,
                                                     "closed_pnl": 0.0})
        b["n"] += 1
        if r["status"] == "OPEN":
            b["open"] += 1
        else:
            b["closed_pnl"] += r["net_inr"] or 0
            b["won"] += (r["net_inr"] or 0) > 0
    return sorted(rows.values(), key=lambda b: (b["book"], b["leg"]))


def signals(con: sqlite3.Connection, day: str, limit: int = 60) -> list[dict]:
    out = []
    for r in con.execute("SELECT opened, closed, book, underlying, side, entry, status, exit_reason, net_pts, state "
                         "FROM paper_trades WHERE opened >= ? AND opened < ? ORDER BY opened DESC LIMIT ?",
                         (day, _next(day), limit)):
        s = json.loads(r["state"])
        mult = s.get("lot_units", 1) * s.get("lots", 1)
        out.append({"time": r["opened"][11:16], "book": r["book"], "symbol": r["underlying"],
                    "side": "BUY" if r["side"] == 1 else "SELL", "entry": r["entry"], "status": r["status"],
                    "exit": r["exit_reason"] or "", "closed": (r["closed"] or "")[11:16],
                    "pnl": None if r["status"] == "OPEN" else (r["net_pts"] or 0) * mult})
    return out


def fills(con: sqlite3.Connection, day: str, limit: int = 60) -> list[dict]:
    return [{"time": r["ts"][11:19], "acct": r["acct"], "symbol": r["symbol"], "action": r["action"], "lots": r["lots"],
             "price": r["price"], "fees": r["fees"], "realized": r["realized"], "reason": r["reason"]}
            for r in con.execute("SELECT ts, acct, symbol, action, lots, price, fees, realized, reason FROM account_fills "
                                 "WHERE ts >= ? AND ts < ? ORDER BY id DESC LIMIT ?", (day, _next(day), limit))]


def messages(con: sqlite3.Connection, limit: int = 15) -> dict:
    out_ = [{"ts": _ist(r["ts"]), "text": (r["text"] or "")[:220]}
            for r in con.execute("SELECT ts, text FROM sent_messages ORDER BY id DESC LIMIT ?", (limit,))]
    in_ = []
    for r in con.execute("SELECT ts, source, raw FROM events WHERE source LIKE 'telegram%' ORDER BY id DESC LIMIT ?",
                         (limit,)):
        try:
            text = json.loads(r["raw"]).get("text", "")
        except (TypeError, ValueError):
            text = r["raw"]
        in_.append({"ts": _ist(r["ts"]), "source": r["source"], "text": (text or "")[:220]})
    return {"out": out_, "in": in_}


def gs_summary(path: Path = GSDB) -> dict:
    """GS paper book: fills and 15:15 exits by branch and fill scenario; net of fees (own store, read-only)."""
    if not path.exists():
        return {"available": False}
    con = ro(path)
    try:
        rows = con.execute("SELECT i.branch, e.scenario, e.kind, e.ts, e.body FROM execution_events e "
                           "JOIN intents i USING(intent_id) ORDER BY e.ts").fetchall()
        n_intents = con.execute("SELECT COUNT(*) FROM intents").fetchone()[0]
    except sqlite3.Error:
        return {"available": False}
    by: dict = {}
    days = set()
    for r in rows:
        b = json.loads(r["body"])
        days.add(str(b.get("ts", r["ts"]))[:10])
        k = f"{r['branch']}/{r['scenario']}"
        d = by.setdefault(k, {"branch": k, "fills": 0, "exits": 0, "expired": 0, "cash": 0.0, "fees": 0.0, "pos": {}})
        if r["kind"] == "expire":
            d["expired"] += 1
            continue
        if r["kind"] not in ("fill", "exit"):
            continue
        d["fills" if r["kind"] == "fill" else "exits"] += 1
        s, q, px = int(b["side"]), int(b["qty"]), float(b["price"])
        d["cash"] -= s * q * px
        d["fees"] += float(b.get("fee") or 0)
        d["pos"][b["instrument_id"]] = d["pos"].get(b["instrument_id"], 0) + s * q
    branches = []
    for d in by.values():
        flat = not any(d["pos"].values())
        branches.append({"branch": d["branch"], "fills": d["fills"], "exits": d["exits"], "expired": d["expired"],
                         "net": d["cash"] - d["fees"] if flat else None, "fees": d["fees"], "flat": flat})
    return {"available": True, "intents": n_intents, "days": sorted(days), "branches": sorted(branches, key=lambda x: x["branch"])}


def health(url: str = "http://127.0.0.1:8000/health") -> dict:
    try:
        import httpx
        r = httpx.get(url, timeout=2.0)
        return {"up": True, **r.json()}
    except Exception as exc:                                        # the bridge is stopped or busy: a state, not a fault
        return {"up": False, "reason": type(exc).__name__}


def system() -> dict:
    try:
        from bridge import panel
        on_ac, pct = panel.power()                                   # (on charger, %): NOT (on battery, %)
        on_batt = None if on_ac is None else not on_ac
        tok_ok, tok_line = panel.token_line()
    except Exception:                                                # the panel helpers are optional here
        on_batt, pct, tok_ok, tok_line = None, None, False, "unknown"
    return {"on_battery": on_batt, "battery_pct": pct, "token_ok": tok_ok, "token": tok_line}


def scorecard() -> list:
    try:
        return json.loads(SCORECARD.read_text())
    except (OSError, ValueError):
        return []


INDEX_KEYS = {"NSE_INDEX|Nifty 50": "NIFTY", "NSE_INDEX|Nifty Bank": "BANKNIFTY", "BSE_INDEX|SENSEX": "SENSEX",
              "NSE_INDEX|India VIX": "VIX"}


def stream_path(day: str) -> Path:
    return ROOT / "data" / f"stream_{day.replace('-', '')}.db"


def latest_ticks(path: Path, keys) -> dict:
    """{key: desk_risk.Tick} from the newest stream row of each key (read-only; older files lack the Greek columns)."""
    from bridge.desk_risk import Tick
    keys = sorted(set(keys))
    if not keys or not path.exists():
        return {}
    con = ro(path)
    try:
        cols = {r[1] for r in con.execute("pragma table_info(tick)")}
        g = ", ".join(c if c in cols else f"NULL AS {c}" for c in ("gamma", "vega", "theta"))
        q = (f"SELECT key, ltp, bid1, ask1, iv, delta, {g}, recv_ts FROM tick WHERE rowid IN "
             f"(SELECT max(rowid) FROM tick WHERE key IN ({','.join('?' * len(keys))}) GROUP BY key)")
        out = {}
        for r in con.execute(q, keys):
            out[r[0]] = Tick(ltp=r[1], bid=r[2], ask=r[3], iv=r[4], delta=r[5], gamma=r[6], vega=r[7], theta=r[8],
                             recv_ts=r[9])
        return out
    finally:
        con.close()


def peak_bids(path: Path, items) -> dict:
    """{(key, opened): the highest stream bid since the position opened} (the accounts only buy options, so the bid is
    what selling would have got). Uses the (key, recv_ts) index; a few ms per open position."""
    items = [(k, o) for k, o in items if k and o]
    if not items or not path.exists():
        return {}
    con = ro(path)
    try:
        out = {}
        for k, o in items:
            r = con.execute("SELECT max(bid1) FROM tick WHERE key=? AND recv_ts>=? AND bid1>0", (k, o)).fetchone()
            if r and r[0] is not None:
                out[(k, o)] = float(r[0])
        return out
    finally:
        con.close()


def control_log(con: sqlite3.Connection, day: str, limit: int = 30) -> list[dict]:
    """Today's admin actions (desk and Telegram), newest first: the audit trail of every control."""
    out = []
    for r in con.execute("SELECT ts, raw FROM events WHERE source='admin' AND ts >= ? AND ts < ? ORDER BY id DESC LIMIT ?",
                         (day, _next(day), limit)):
        try:
            raw = json.loads(r[1])
        except (TypeError, ValueError):
            raw = {"raw": r[1]}
        out.append({"ts": _ist(r[0]), **{k: raw.get(k) for k in ("cmd", "acct", "sid", "via", "device", "chat", "result")}})
    return out


def risk_section(con: sqlite3.Connection, day: str) -> dict:
    from bridge import desk_risk
    pos = [(r[0], json.loads(r[1])) for r in con.execute(
        "SELECT acct, state FROM account_positions WHERE status='OPEN' ORDER BY acct")]
    keys = {s.get("key") for _, s in pos} | {s.get("under_key") for _, s in pos}
    ticks = latest_ticks(stream_path(day), {k for k in keys if k})
    risks = [desk_risk.position_risk(a, s, ticks.get(s.get("key")), ticks.get(s.get("under_key"))) for a, s in pos]
    peaks = peak_bids(stream_path(day), [(s.get("key"), s.get("opened", "")) for _, s in pos])
    for r, (_, s) in zip(risks, pos):                  # owner, 28 Oct: "it was in profit": show what was given back
        pk = peaks.get((s.get("key"), s.get("opened", "")))
        if pk is not None and r.unrealized is not None:
            r.peak_unrealized = max((pk - r.entry) * r.units, r.unrealized)
            r.giveback = r.peak_unrealized - r.unrealized
    grid = desk_risk.scenario_grid(risks)
    ex = desk_risk.exposure(risks)
    return {"positions": [r.__dict__ for r in risks],
            "scenarios": [{"spot": m, "iv": v, "pnl": p} for (m, v), p in grid["grid"].items()],
            "scenario_included": grid["included"], "scenario_excluded": grid["excluded"],
            "exposure": ex, "stream": stream_path(day).exists()}


def stream_health(day: str) -> dict:
    p = stream_path(day)
    if not p.exists():
        return {"available": False}
    con = ro(p)
    try:
        # cheap on a multi-million-row tick table: rowid instead of COUNT(*), distinct keys over the newest rows only
        n, last = con.execute("SELECT max(rowid), recv_ts FROM tick WHERE rowid = (SELECT max(rowid) FROM tick)").fetchone() \
            or (0, None)
        keys = con.execute("SELECT COUNT(DISTINCT key) FROM (SELECT key FROM tick ORDER BY rowid DESC LIMIT 50000)"
                           ).fetchone()[0]
        n = n or 0
        recent = con.execute("SELECT recv_ts, ltt FROM tick WHERE ltt > 0 ORDER BY rowid DESC LIMIT 3000").fetchall()
        lat = sorted(datetime.fromisoformat(a).timestamp() * 1000 - b for a, b in recent if a)
        errs = con.execute("SELECT COUNT(*) FROM info WHERE kind='error'").fetchone()[0]
        follow = con.execute("SELECT COUNT(*) FROM info WHERE kind='follow'").fetchone()[0]
        last_err = con.execute("SELECT recv_ts, body FROM info WHERE kind='error' ORDER BY rowid DESC LIMIT 1").fetchone()
        idx = latest_ticks(p, INDEX_KEYS)
        cp = {k: r[0] for k, r in ((k, con.execute("SELECT cp FROM tick WHERE key=? ORDER BY rowid DESC LIMIT 1",
                                                     (k,)).fetchone()) for k in INDEX_KEYS) if r}
    finally:
        con.close()
    age = (datetime.now(IST) - datetime.fromisoformat(last)).total_seconds() if last else None
    indices = {INDEX_KEYS[k]: {"ltp": t.ltp, "chg_pct": ((t.ltp / cp[k] - 1) * 100) if cp.get(k) and t.ltp else None}
               for k, t in idx.items()}
    regime_ = _safe(lambda: _regime(p, indices))
    return {"available": True, "ticks": n, "keys": keys, "last": last, "age_s": age, "errors": errs, "regime": regime_,
            "follow_events": follow, "last_error": list(last_err) if last_err else None,
            "latency_ms_p50": lat[len(lat) // 2] if lat else None,
            "latency_ms_p95": lat[int(len(lat) * 0.95)] if lat else None, "indices": indices}


def _regime(path: Path, indices: dict) -> dict:
    """Live market regime (bridge/regime.py labels): VIX percentile and day change, NIFTY's move, breadth (cached 60 s,
    the breadth query reads the newest tick of every stock)."""
    from bridge import regime
    from ops import signal_context
    now = datetime.now(IST).isoformat()

    def breadth():
        con = ro(path)
        try:
            return signal_context.breadth_at(con, now)
        finally:
            con.close()
    b = cached("breadth", 60, breadth)
    v, nf = indices.get("VIX") or {}, indices.get("NIFTY") or {}
    return regime.classify(v.get("ltp"), v.get("chg_pct"), nf.get("chg_pct"), b if isinstance(b, float) else None)


_CACHE: dict = {}


def cached(name: str, ttl_s: float, fn):
    """Slow research sections (overnight scoring, the scalp replay) are recomputed at most every ttl_s."""
    import time
    hit = _CACHE.get(name)
    if hit and time.time() - hit[0] < ttl_s:
        return hit[1]
    val = _safe(fn)
    _CACHE[name] = (time.time(), val)
    return val


def research_section(day: str) -> dict:
    def overnight():
        sys.path.insert(0, str(ROOT.parent / "nfce_engine"))
        from tools import opx_gate, overnight_options as ovn, overnight_v3
        keep = ("day", "status", "atm", "forward", "credit_pts", "lots", "units")
        v2, v3, opx = ovn.score_v2(), overnight_v3.score_v3(), opx_gate.score_opx()
        # NaN (e.g. a "pending" row) is not valid JSON and would 500 the whole snapshot: send it as blank
        pick = lambda t, cols: (t[[c for c in cols if c in t]].tail(10).astype(object)  # noqa: E731
                                .where(lambda x: x.notna(), None).to_dict("records") if len(t) else [])
        return {"v2": pick(v2, keep), "v3": pick(v3, keep),
                "opx": pick(opx, ("day", "status", "gate", "ratio", "iv", "forecast_vol", "u_opx")),
                "opx_report": opx_gate.pilot_report(opx)}

    def scalp():
        p = stream_path(day)
        if not p.exists():
            return {"available": False}
        now = datetime.now(IST)
        if day == now.date().isoformat() and "09:00" <= now.strftime("%H:%M") < "15:20":
            return {"available": True, "deferred": True}        # the full-day replay is heavy: after 15:20 only
        sys.path.insert(0, str(ROOT.parent / "nfce_engine"))
        from tools import scalp_sim
        r = scalp_sim.run(p)
        return {"available": True, "universe": len(r["universe"]), "tick_gap_median_s": r["tick_gap_median_s"],
                **r["summary"]}

    return {"overnight": cached("overnight", 1800, overnight),        # changes only at the 09:20 exit / 15:20 entry
            "scalp": cached(f"scalp_{day}", 1800, scalp)}              # ~14 s replay on a full day


def performance_section(con: sqlite3.Connection, day: str) -> dict:
    from ops import eod_report
    perf = eod_report.performance(con, day)
    curves = {}
    for acct in perf:
        rows = con.execute("SELECT substr(ts,1,10), equity FROM account_equity WHERE acct=? AND ts IN "
                           "(SELECT max(ts) FROM account_equity WHERE acct=? GROUP BY substr(ts,1,10)) ORDER BY 1",
                           (acct, acct)).fetchall()
        cap = perf[acct].get("capital", 500_000.0)
        curves[acct] = [[d, (e / cap - 1) * 100] for d, e in rows]      # % since start: accounts of any size compare
    return {"stats": perf, "curves": curves}


def alerts(s: dict, now: datetime | None = None) -> list[dict]:
    """Rule-based alerts on a snapshot: crit / warn / info, newest problems first."""
    now = now or datetime.now(IST)
    mins = now.hour * 60 + now.minute
    market = now.weekday() < 5 and 9 * 60 <= mins <= 15 * 60 + 35
    out = []
    add = lambda lvl, txt: out.append({"level": lvl, "text": txt})  # noqa: E731
    h, sy = s.get("health") or {}, s.get("system") or {}
    if market and not h.get("up"):
        add("crit", "Bridge is not running during market hours")
    if h.get("up"):
        probs = [p for p in h.get("problems") or [] if "SENSEX" not in p]
        for p in probs:
            add("warn", f"Health: {p}")
        if h.get("poll_beat"):
            age = (now - datetime.fromisoformat(h["poll_beat"])).total_seconds()
            if age > 60:
                add("warn", f"Bridge poll loop silent for {age:.0f}s")
        gs = str(h.get("gs") or "")
        if market and mins >= 9 * 60 + 8 and gs and not gs.startswith("FROZEN"):
            add("warn", f"GS: {gs[:80]}")
    if sy.get("token_ok") is False:
        add("crit" if market else "info", "Upstox token expired: the owner must sign in")
    if sy.get("on_battery") and sy.get("battery_pct") is not None:
        add("crit" if sy["battery_pct"] <= 15 else "warn" if sy["battery_pct"] <= 30 else "info",
            f"On battery: {sy['battery_pct']}%")
    for a in s.get("accounts") or []:
        L = a.get("limits", {})
        u = L.get("daily_loss", {}).get("used", 0)
        if u >= 1:
            add("crit", f"{a['name']}: daily loss limit reached")
        elif u >= 0.8:
            add("warn", f"{a['name']}: {u:.0%} of the daily loss limit used")
        if L.get("give_back", {}).get("halted"):
            add("info", f"{a['name']}: give-back stop halted new entries")
        if L.get("streak", {}).get("losses", 0) >= 2:
            add("warn", f"{a['name']}: {L['streak']['losses']} losses in a row (pause at 3)")
    st = s.get("stream") or {}
    if market and st.get("available") and st.get("age_s") is not None and st["age_s"] > 30:
        add("warn", f"Stream silent for {st['age_s']:.0f}s")
    for p in (s.get("risk") or {}).get("positions", []):
        if p.get("mark") is None:
            add("warn", f"{p['acct']} {p['symbol']}: no live mark")
    for k, v in s.items():
        if isinstance(v, dict) and v.get("error"):
            add("warn", f"Desk section '{k}' failed: {v['error'][:100]}")
    order = {"crit": 0, "warn": 1, "info": 2}
    return sorted(out, key=lambda x: order[x["level"]])


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as exc:                                          # one broken source never breaks the desk
        return {"error": f"{type(exc).__name__}: {exc}"}


def json_safe(o):
    """NaN/inf anywhere becomes None: strict JSON fails the WHOLE snapshot on one bad number (28 Oct, 08:57: a pending
    OVN row's NaN took every desk tab down)."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [json_safe(v) for v in o]
    return o


def snapshot(day: str | None = None, db: Path = DB, gsdb: Path = GSDB, with_live: bool = True,
             with_research: bool = True) -> dict:
    day = day or datetime.now(IST).date().isoformat()
    snap = {"day": day, "generated": datetime.now(IST).strftime("%H:%M:%S")}
    con = ro(db)
    try:
        for name, fn in (("accounts", accounts), ("books", books), ("signals", signals), ("fills", fills),
                         ("risk", risk_section), ("performance", performance_section)):
            snap[name] = _safe(fn, con, day)
        snap["messages"] = _safe(messages, con)
        snap["control_log"] = _safe(control_log, con, day)
        h = _safe(_kv, con, "halted")
        snap["halted"] = None if isinstance(h, dict) else bool(h)      # None = unknown (a read error), never "halted"
    finally:
        con.close()
    snap["gs"] = _safe(gs_summary, gsdb)
    snap["scorecard"] = _safe(scorecard)
    snap["stream"] = _safe(stream_health, day)
    if with_research:
        snap["research"] = _safe(research_section, day)
    if with_live:
        # token and battery change slowly; the token check starts a python process, so once a minute, not every 5 s
        snap["health"], snap["system"] = _safe(health), cached("system", 60, system)
    snap["alerts"] = _safe(alerts, snap)
    return snap


def _next(day: str) -> str:
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def _kv(con, key):
    r = con.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
    if r is None:
        return None
    try:
        return json.loads(r[0])
    except (TypeError, ValueError):
        return r[0]


def _ist(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts).astimezone(IST).strftime("%d %b %H:%M")
    except (TypeError, ValueError):
        return str(ts)[:16]


PAGE = (Path(__file__).with_name("desk.html"))


def live_snapshot(day: str | None = None, db: Path = DB) -> dict:
    """Every account's open positions (stream marks: bid for selling, peak since entry, giveback), live equity
    (cash + positions at the bid) and today's fills. Built for a 1-second refresh."""
    day = day or datetime.now(IST).date().isoformat()
    con = ro(db)
    try:
        risk = _safe(risk_section, con, day)               # each part fails alone: the Trade tab never goes blank
        errors = [f"positions: {risk['error']}"] if "error" in risk else []
        pos = risk.get("positions", [])
        caps, cash = {}, {}
        for name in [r[0] for r in con.execute("SELECT DISTINCT acct FROM account_equity")] + \
                [p["acct"] for p in pos]:
            caps[name] = float(_kv(con, f"account_{name}_capital") or 500_000)
            cash[name] = float(_kv(con, f"account_{name}_cash") or 0.0)
        strat = _strategies()
        accts = []
        for name in sorted(caps, key=lambda n: (list(strat).index(n) if n in strat else 99, n)):
            mine = [p for p in pos if p["acct"] == name]
            held = sum((p["mark"] or p["entry"]) * p["units"] for p in mine)
            accts.append({"name": name, "strategy": strat.get(name, "base"), "capital": caps[name], "cash": cash[name],
                          "equity": cash[name] + held, "open": len(mine),
                          "unrealized": sum(p["unrealized"] or 0.0 for p in mine)})
        fl = [dict(r) for r in con.execute(
            "SELECT id, acct, ts, sid, symbol, action, lots, price, fees, realized, reason FROM account_fills "
            "WHERE ts >= ? AND ts < ? ORDER BY id DESC LIMIT 200", (day, _next(day)))]
        for f in fl:
            f["t"] = _ist(f["ts"])[-5:]
        sig = []
        try:
            for r in con.execute(
                    "SELECT p.book, p.sid, p.opened, p.underlying, p.side, p.entry, p.sl, p.t1, p.status, p.exit_reason, "
                    "p.net_pts, s.action FROM paper_trades p LEFT JOIN signals s ON s.sid = p.sid "
                    "WHERE p.opened >= ? AND p.opened < ? AND p.book IN ('stock3m', 'executable', 'scanner') "
                    "ORDER BY p.opened DESC LIMIT 60", (day, _next(day))):
                sig.append({"book": r[0], "sid": r[1], "t": _ist(r[2])[-5:], "underlying": r[3], "side": r[4],
                            "entry": r[5], "sl": r[6], "t1": r[7], "status": r[8], "exit": r[9], "net_pts": r[10],
                            "check": r[11]})
        except sqlite3.Error as exc:
            errors.append(f"signals: {exc}")
        tick_age = None
        if pos:
            ages = [age_s(p.get("recv_ts")) for p in pos if p.get("recv_ts")]
            tick_age = min(ages) if ages else None
        return {"day": day, "generated": datetime.now(IST).strftime("%H:%M:%S"), "positions": pos, "accounts": accts,
                "fills": fl, "signals": sig, "tick_age_s": tick_age, "errors": errors}
    finally:
        con.close()


def age_s(ts: str | None) -> float | None:
    try:
        return round((datetime.now(IST) - datetime.fromisoformat(ts)).total_seconds(), 1)
    except (TypeError, ValueError):
        return None


_KEYS: dict = {}


def underlying_key(name: str) -> str | None:
    """Stream key of an index root or F&O stock (the instruments file's futures rows name their underlying)."""
    name = name.upper().strip()
    if not _KEYS:
        from bridge.config import DEFAULT_UNDERLYINGS
        _KEYS.update(DEFAULT_UNDERLYINGS)
        try:
            for r in json.loads((ROOT / "data" / "instruments_NSE.json").read_text())["rows"]:
                if r.get("instrument_type") == "FUT" and r.get("underlying_type") == "EQUITY":
                    _KEYS.setdefault(r["underlying_symbol"], r["underlying_key"])
        except (OSError, ValueError, KeyError):
            pass
    return _KEYS.get(name)


def ema(xs: list, n: int) -> list:
    out, k, e = [], 2 / (n + 1), None
    for x in xs:
        e = x if e is None else e + k * (x - e)
        out.append(e)
    return out


def rsi(xs: list, n: int = 14) -> list:
    """Wilder RSI; None until n changes exist."""
    out, g, l = [None] * len(xs), 0.0, 0.0
    for i in range(1, len(xs)):
        d = xs[i] - xs[i - 1]
        up, dn = max(d, 0.0), max(-d, 0.0)
        if i <= n:
            g, l = g + up / n, l + dn / n
            if i < n:
                continue
        else:
            g, l = (g * (n - 1) + up) / n, (l * (n - 1) + dn) / n
        out[i] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    return out


def chart_data(day: str | None, name: str, db: Path = DB, stream: Path | None = None) -> dict:
    """1-minute candles of an underlying from the stream, with VWAP (stocks: volume from the cumulative traded
    quantity), EMA 9/21, RSI 14, and today's signals drawn at the spot price of their minute (futures levels moved by
    the same distances, as the alerts do)."""
    day = day or datetime.now(IST).date().isoformat()
    key = underlying_key(name)
    if key is None:
        return {"error": f"{name!r} is not an index root or F&O stock"}
    path = stream or stream_path(day)
    if not path.exists():
        return {"error": "no stream recording for this day"}
    con = ro(path)
    try:
        rows = con.execute("SELECT recv_ts, ltp, vtt FROM tick WHERE key=? AND ltp>0 AND recv_ts>=? ORDER BY recv_ts",
                           (key, f"{day}T09:15")).fetchall()
    finally:
        con.close()
    bars, last_v = [], None
    for ts, px, vtt in rows:
        m = ts[11:16]
        if m > "15:30":
            break
        if not bars or bars[-1]["t"] != m:
            bars.append({"t": m, "o": px, "h": px, "l": px, "c": px, "v": 0.0})
        b = bars[-1]
        b["h"], b["l"], b["c"] = max(b["h"], px), min(b["l"], px), px
        if vtt is not None:
            if last_v is not None and vtt >= last_v:
                b["v"] += vtt - last_v
            last_v = vtt
    closes = [b["c"] for b in bars]
    has_vol = any(b["v"] for b in bars)
    vwap, pv, vv = [], 0.0, 0.0
    for b in bars:
        pv, vv = pv + (b["h"] + b["l"] + b["c"]) / 3 * b["v"], vv + b["v"]
        vwap.append(pv / vv if has_vol and vv else None)
    at = {b["t"]: b["c"] for b in bars}
    sig = []
    dcon = ro(db)
    try:
        for r in dcon.execute("SELECT opened, side, entry, sl, t1, book, status, exit_reason FROM paper_trades WHERE "
                              "underlying=? AND opened>=? AND opened<? AND book IN ('stock3m','executable','scanner') "
                              "ORDER BY opened", (name.upper(), day, _next(day))):
            t = _ist(r[0])[-5:]
            spot = at.get(t) or next((at[k] for k in sorted(at) if k >= t), None)
            if spot is None:
                continue
            sig.append({"t": t, "side": r[1], "entry": spot, "sl": spot + (r[3] - r[2]), "t1": spot + (r[4] - r[2]),
                        "book": r[5], "status": r[6], "exit": r[7]})
    finally:
        dcon.close()
    last = closes[-1] if closes else None
    return {"underlying": name.upper(), "key": key, "bars": bars, "vwap": vwap, "ema9": ema(closes, 9),
            "ema21": ema(closes, 21), "rsi": rsi(closes, 14), "signals": sig, "last": last,
            "day_high": max((b["h"] for b in bars), default=None), "day_low": min((b["l"] for b in bars), default=None),
            "chg_pct": (last / bars[0]["o"] - 1) * 100 if bars and last else None, "has_volume": has_vol}


LOCAL = {"127.0.0.1", "::1", "localhost"}
TOKENS = ("DESK_VIEW_TOKEN", "DESK_CONTROL_TOKEN", "DESK_ADMIN_SECRET")


def env_value(name: str, env_file: Path = ROOT / ".env") -> str:
    try:
        for line in env_file.read_text().splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def role_of(host: str, token: str, view: str, control: str) -> str | None:
    """'control' on this Mac (the owner's own machine, as before) or with the CONTROL token; 'view' with the VIEW token;
    None otherwise (a LAN device without a token sees nothing). Constant-time compares."""
    import hmac
    if host in LOCAL:
        return "control"
    t = (token or "").encode()
    if control and t and hmac.compare_digest(t, control.encode()):
        return "control"
    if view and t and hmac.compare_digest(t, view.encode()):
        return "view"
    return None


def init_tokens(env_file: Path = ROOT / ".env") -> list[str]:
    """Add any missing desk token to .env (never printed; the desk shows the phone links on this Mac only)."""
    import secrets
    have = env_file.read_text() if env_file.exists() else ""
    added = [k for k in TOKENS if not env_value(k, env_file)]
    if added:
        with env_file.open("a") as f:
            f.write(("" if have.endswith("\n") or not have else "\n")
                    + "".join(f"{k}={secrets.token_urlsafe(24)}\n" for k in added))
    return added


def lan_ip() -> str | None:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))                # no packet is sent; picks the Wi-Fi interface's address
        ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None
    finally:
        s.close()


def app(day: str | None = None, port: int = 8001, lan: bool = False,
        bridge_url: str = "http://127.0.0.1:8000"):
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse, JSONResponse
    a = FastAPI(title="NFCE desk")

    def who(request: Request) -> str:
        host = request.client.host if request.client else ""
        role = role_of(host, request.headers.get("x-desk-token", ""), env_value("DESK_VIEW_TOKEN"),
                       env_value("DESK_CONTROL_TOKEN"))
        if role is None:
            raise HTTPException(status_code=401, detail="token needed: open the link shown on the Mac's desk")
        return role

    @a.get("/", response_class=HTMLResponse)
    def index():                                       # the page holds no data; /api/* needs a role
        return PAGE.read_text()

    @a.get("/api/all")
    def all_(request: Request):
        role = who(request)
        snap = snapshot(day)
        snap["role"] = role
        host = request.client.host if request.client else ""
        if host in LOCAL and lan:                      # phone links only ever go to this Mac's own screen
            ip = lan_ip()
            v, c = env_value("DESK_VIEW_TOKEN"), env_value("DESK_CONTROL_TOKEN")
            snap["links"] = {"ip": ip, "view": f"http://{ip}:{port}/?t={v}" if ip and v else None,
                             "control": f"http://{ip}:{port}/?t={c}" if ip and c else None}
        return JSONResponse(json_safe(snap))

    @a.post("/api/control")
    async def control(request: Request):
        if who(request) != "control":
            raise HTTPException(status_code=403, detail="view-only token")
        secret = env_value("DESK_ADMIN_SECRET")
        if not secret:
            raise HTTPException(status_code=503, detail="DESK_ADMIN_SECRET is not set")
        body = await request.json()
        host = request.client.host if request.client else "?"
        ua = request.headers.get("user-agent", "")
        dev = f"{host} {'iPhone' if 'iPhone' in ua else 'Android' if 'Android' in ua else 'Mac' if 'Mac' in ua else ua[:24]}"
        import httpx
        try:
            r = httpx.post(f"{bridge_url}/admin/action", headers={"X-Admin-Secret": secret}, timeout=15,
                           json={k: body.get(k, "") for k in ("action", "acct", "sid", "underlying", "side", "lots")}
                           | {"device": dev})
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"bridge not reachable: {type(exc).__name__}")
        try:
            payload = r.json()
        except ValueError:
            payload = {"detail": r.text[:200]}
        return JSONResponse(payload, status_code=r.status_code)

    @a.get("/api/live")
    def live_(request: Request):
        """The fast path (polled every second): positions marked from the stream, today's fills, cash. No research,
        no health calls, a few ms."""
        role = who(request)
        return JSONResponse(json_safe(live_snapshot(day) | {"role": role}))

    @a.get("/api/chart")
    def chart_(request: Request, u: str = "NIFTY"):
        who(request)
        return JSONResponse(json_safe(_safe(chart_data, day, u)))

    @a.get("/api/universe")
    def universe_(request: Request):
        if who(request) != "control":
            raise HTTPException(status_code=403, detail="view-only token")
        import httpx
        try:
            r = httpx.get(f"{bridge_url}/admin/universe", headers={"X-Admin-Secret": env_value("DESK_ADMIN_SECRET")},
                          timeout=10)
            return JSONResponse(r.json(), status_code=r.status_code)
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=f"bridge not reachable: {type(exc).__name__}")

    return a


if __name__ == "__main__":
    import argparse
    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--day", help="show a past day (YYYY-MM-DD); default today")
    ap.add_argument("--lan", action="store_true", help="listen on the Wi-Fi too (owner OK 28 Oct; tokens required there)")
    ap.add_argument("--init-tokens", action="store_true", help="add missing DESK_* tokens to .env and exit")
    x = ap.parse_args()
    if x.init_tokens:
        print("added:", ", ".join(init_tokens()) or "nothing (all present)")
        raise SystemExit(0)
    if x.lan and not (env_value("DESK_VIEW_TOKEN") and env_value("DESK_CONTROL_TOKEN")):
        raise SystemExit("--lan needs DESK_VIEW_TOKEN and DESK_CONTROL_TOKEN in .env: run with --init-tokens first")
    uvicorn.run(app(x.day, x.port, x.lan), host="0.0.0.0" if x.lan else "127.0.0.1", port=x.port, log_level="warning")
