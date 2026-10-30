"""GS-SIP-1 replay over recorded minute quotes: EXPLORATORY parity / smoke runs only. Nothing here is evidence.

  nice -n 15 ../nfce_bridge/.venv/bin/python tools/gs_replay.py [2026-10-22 ...]   (default: every study_quotes day)

Feeds the SAME SipEngine methods the bridge adapter uses, in availability order, for three branches (P strict,
P touch, M market) and reports, per day, the selection, every opportunity and its outcome, the adverse-stress series
and the parity checks (two fresh runs and the adapter path must give byte-identical intents and fills).
Why it cannot be evidence (blueprint section 4.2): the quotes are minute snapshots stamped at request START (the
pre-fix recorder), so quote ages, latency and queue position are unknown; 3-minute bars are built from 1-minute
candles where they exist (22 Oct) and otherwise from the snapshots (approximate highs/lows); history after 21 Oct is
patched from those sources too; the waits are widened to 75 s to fit minute data. Read-only on every input.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gs import alpha_sip as sip  # noqa: E402
from gs import calendar as cal  # noqa: E402
from gs import execution as ex  # noqa: E402
from gs import features as ft  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BRIDGE_DATA = ROOT / "nfce_bridge" / "data"
NDATA = Path.home() / "Downloads" / "nfce_data"
RECENT = NDATA / "hist3m_recent"                  # ops/pull3m_recent.py: real 3-minute candles of the last days
REPORT = ROOT / "evidence" / "gs_sip_replay_exploratory.md"
EXPLORE = dict(refresh_wait_s=75.0, max_wait_s=75.0, exploratory=True)
RELAX = dict(select_grace_s=75.0, rvol_min_windows=12)     # --relaxed: NOT the registered rule (smoke runs only)


def configs(relaxed: bool = False):
    kw = EXPLORE | (RELAX if relaxed else {})
    return (sip.SipConfig(branch="P", scenario="strict", **kw), sip.SipConfig(branch="P", scenario="touch", **kw),
            sip.SipConfig(branch="M", scenario="market", **kw))


CONFIGS = configs()


# ---------------------------------------------------------------- inputs
def quote_days(data: Path = BRIDGE_DATA) -> list[date]:
    return [date.fromisoformat(f"{f.stem[-8:-4]}-{f.stem[-4:-2]}-{f.stem[-2:]}") for f in
            sorted(data.glob("study_quotes_2026102*.db"))]


def load_books(day: date, data: Path = BRIDGE_DATA) -> dict:
    """{instrument_id: [Book]} for cash-equity rows (NSE_EQ:SYM), snapshot time as ts (request start: pre-fix)."""
    con = sqlite3.connect(f"file:{data / f'study_quotes_{day:%Y%m%d}.db'}?mode=ro", uri=True)
    rows = con.execute("select ts, symbol, last, volume, depth from q where symbol like 'NSE_EQ:%' order by ts").fetchall()
    con.close()
    out: dict = {}
    for ts, sym, last, vol, depth in rows:
        t = cal.to_ist(datetime.fromisoformat(ts))
        if t.date() != day:
            continue
        try:
            d = json.loads(depth) if depth else {}
        except ValueError:
            d = {}
        out.setdefault(sym, []).append(ex.Book.from_depth(t, d, last, vol))
    return out


def bars_from_1m(path: Path, avail_delay_s: float = 2.0) -> list[ft.Bar]:
    d = pd.read_csv(path)
    d["t"] = pd.to_datetime(d["ts"])
    out = []
    sym = path.stem.split("__")[0]
    for k in range(0, 375, 3):
        s = d["t"].iloc[0].normalize() + pd.Timedelta(minutes=9 * 60 + 15 + k)
        g = d[(d["t"] >= s) & (d["t"] < s + pd.Timedelta(minutes=3))]
        if len(g) == 0:
            continue
        st = s.to_pydatetime()
        out.append(ft.Bar(f"NSE_EQ:{sym}", st, 3, float(g["open"].iloc[0]), float(g["high"].max()),
                          float(g["low"].min()), float(g["close"].iloc[-1]), float(g["volume"].sum()),
                          st + timedelta(minutes=3, seconds=avail_delay_s)))
    return out


def bars_from_books(inst: str, books: list[ex.Book], day: date) -> list[ft.Bar]:
    """Approximate 3-minute bars from minute snapshots of the last price and cumulative volume. available_at = the
    first snapshot at or after the bar's end (when its completion is known)."""
    out = []
    o = datetime.combine(day, cal.OPEN, cal.IST)
    for k in range(125):
        s, e = o + timedelta(minutes=3 * k), o + timedelta(minutes=3 * k + 3)
        inside = [b for b in books if s <= b.ts < e and b.last]
        after = [b for b in books if b.ts >= e]
        before = [b for b in books if b.ts < s and b.volume is not None]
        if not inside or not after:
            continue
        px = [b.last for b in inside]
        v0 = before[-1].volume if before else inside[0].volume
        out.append(ft.Bar(inst, s, 3, px[0], max(px), min(px), px[-1], max(0.0, (inside[-1].volume or 0) - (v0 or 0)),
                          after[0].ts))
    return out


def daily_history(sym: str, day: date, patches: dict) -> list[ft.DailyBar]:
    f = NDATA / "daily" / f"{sym}_1d.pkl"
    out = []
    if f.exists():
        d = pd.read_pickle(f)
        idx = pd.DatetimeIndex(d.index)
        idx = idx.tz_localize(None) if idx.tz is not None else idx
        d.index = idx.normalize()
        d = d[d.index < pd.Timestamp(day)].iloc[-120:]
        out = [ft.DailyBar(i.date(), float(r.open), float(r.high), float(r.low), float(r.close), float(r.volume))
               for i, r in d.iterrows()]
    have = {b.day for b in out}
    for dd, b in sorted(patches.get(sym, {}).items()):
        if dd < day and dd not in have:
            out.append(b)
    return sorted(out, key=lambda b: b.day)


def recent_bars(sym: str, day: date) -> list[ft.Bar]:
    """Real 3-minute candles of `day` from hist3m_recent (available 2 s after each bar closes), or []."""
    f = RECENT / f"{sym}_3m.pkl"
    if not f.exists():
        return []
    d = pd.read_pickle(f)
    idx = pd.DatetimeIndex(d.index).tz_convert(cal.IST)
    g = d[idx.date == day]
    out = []
    for t, r in g.iterrows():
        st = pd.Timestamp(t).tz_convert(cal.IST).to_pydatetime()
        out.append(ft.Bar(f"NSE_EQ:{sym}", st, 3, float(r.open), float(r.high), float(r.low), float(r.close),
                          float(r.volume), st + timedelta(minutes=3, seconds=2)))
    return out


def hist_windows(sym: str) -> list[tuple[date, float]]:
    out = _windows_of(NDATA / "hist3m_fo" / f"{sym}_3m.pkl")
    have = {d for d, _ in out}
    return out + [w for w in _windows_of(RECENT / f"{sym}_3m.pkl") if w[0] not in have]


def _windows_of(f: Path) -> list[tuple[date, float]]:
    if not f.exists():
        return []
    d = pd.read_pickle(f)
    idx = pd.DatetimeIndex(d.index).tz_convert(cal.IST)
    d = d[idx >= pd.Timestamp("2026-08-01", tz=cal.IST)]
    idx = pd.DatetimeIndex(d.index).tz_convert(cal.IST)
    hm = idx.hour * 60 + idx.minute
    g = d[(hm == 555) | (hm == 558)]
    gi = pd.DatetimeIndex(g.index).tz_convert(cal.IST)
    s = g.groupby(gi.date)["volume"].agg(["sum", "size"])
    return [(k, float(r["sum"])) for k, r in s.iterrows() if r["size"] == 2]


def build_day(day: date, books_by_day: dict) -> tuple[dict, list, list[str]]:
    """Universe, the ordered event list, and the notes on what had to be approximated."""
    notes: list[str] = []
    books = books_by_day[day]
    patches: dict = {}
    windows_extra: dict = {}
    one_m_days = {date.fromisoformat(p.name) for p in (BRIDGE_DATA / "study_1m").glob("2026-*") if p.is_dir()}
    src_days = sorted(d0 for d0 in set(books_by_day) | one_m_days if d0 < day)
    for d0 in src_days:
        one_m = BRIDGE_DATA / "study_1m" / d0.isoformat()
        used = set()
        for inst in books:
            sym = inst.split(":")[1]
            f = one_m / f"{sym}__eq.csv"
            rb = recent_bars(sym, d0)
            if rb:
                bars, src = rb, "3m candles"
            elif f.exists():
                bars, src = bars_from_1m(f), "1m"
            elif d0 in books_by_day and inst in books_by_day[d0]:
                bars, src = bars_from_books(inst, books_by_day[d0][inst], d0), "quotes (approximate)"
            else:
                continue
            if not bars:
                continue
            used.add(src)
            patches.setdefault(sym, {})[d0] = ft.DailyBar(d0, bars[0].open, max(b.high for b in bars),
                                                          min(b.low for b in bars), bars[-1].close)
            w = [b for b in bars if b.start.time() in (time(9, 15), time(9, 18))]
            if len(w) == 2:
                windows_extra.setdefault(sym, {})[d0] = sum(b.volume for b in w)
        notes.append(f"{d0}: daily bars and opening windows (where missing) from {'/'.join(sorted(used)) or 'nothing'}")
    one_m_today = BRIDGE_DATA / "study_1m" / day.isoformat()
    universe, events = {}, []
    for inst, bs in books.items():
        sym = inst.split(":")[1]
        hist = daily_history(sym, day, patches)
        win = dict(windows_extra.get(sym, {}))
        win.update(dict(hist_windows(sym)))                       # real 3-minute candles win where they exist
        universe[inst] = sip.StockDay(inst, hist, sorted(win.items()))
        f = one_m_today / f"{sym}__eq.csv"
        bars = recent_bars(sym, day) or (bars_from_1m(f) if f.exists() else bars_from_books(inst, bs, day))
        events += [(b.available_at, 0, inst, "bar", b) for b in bars]
        events += [(b.ts, 1, inst, "book", b) for b in bs]
    src_today = ("3-minute candles" if any(RECENT.glob("*_3m.pkl")) and recent_bars("RELIANCE", day) else
                 "1-minute candles" if one_m_today.exists() else "quote snapshots (approximate)")
    notes.append(f"{day}: bars from {src_today}")
    events.sort(key=lambda x: (x[0], x[1], x[2]))
    return universe, events, notes


def vix_for(day: date) -> tuple[tuple, list[str]]:
    v = pd.read_pickle(NDATA / "daily" / "INDIAVIX_1d.pkl")
    idx = pd.DatetimeIndex(v.index)
    v.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    bars = [ft.DailyBar(i.date(), r.open, r.high, r.low, r.close) for i, r in v.iterrows() if i.date() < day]
    (x, rise), _ = ft.vix_state(bars, datetime.combine(day, time(9, 21), cal.IST))
    if x is not None:
        return (x, rise), []
    last = bars[-6:]
    return (last[-1].close, last[-1].close / last[0].close - 1), [f"{day}: VIX to the previous session missing; "
                                                                  f"the last known close ({last[-1].day}) is used"]


# ---------------------------------------------------------------- running
def feed(engine_like, events, end: datetime, adapter: bool = False) -> None:
    for t, _, inst, kind, obj in events:
        if adapter:
            if kind == "bar":
                engine_like.on_bar(inst, obj.start, obj.minutes, obj.open, obj.high, obj.low, obj.close, obj.volume,
                                   obj.available_at)
            else:
                depth = {"buy": [{"price": p, "quantity": q} for p, q in obj.bids],
                         "sell": [{"price": p, "quantity": q} for p, q in obj.asks]}
                engine_like.on_quote(inst, depth, obj.last, obj.volume, obj.ts)
        else:
            engine_like.on_bar(obj) if kind == "bar" else engine_like.on_book(inst, obj)
    engine_like.on_clock(end)


def load_adapter():
    p = ROOT / "nfce_bridge" / "bridge" / "gs_adapter.py"
    spec = importlib.util.spec_from_file_location("gs_adapter_standalone", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run_day(day: date, books_by_day: dict, configs=CONFIGS) -> dict:
    universe, events, notes = build_day(day, books_by_day)
    vix, vnotes = vix_for(day)
    end = datetime.combine(day, time(15, 31), cal.IST)
    res, prints = [], []
    for c in configs:
        prs = []
        for _ in range(2):
            e = sip.SipEngine(c)
            e.start_day(day, universe, vix)
            feed(e, events, end)
            prs.append(e.fingerprint())
        res.append(e.end_day())
        prints.append(prs)
    ad = load_adapter().GSAdapter(None, configs)
    ad.start_day(day, universe, vix)
    feed(ad, events, end, adapter=True)
    ad_prints = ad.fingerprints()
    parity = all(a == b == c for (a, b), c in zip(prints, ad_prints)) and ad.healthy
    strict = res[0]["opportunities"]
    from gs.execution import adverse_stress
    adv = adverse_stress([o["net"] if o["qty"] > 0 else None for o in strict], [o["notional"] for o in strict])
    return {"day": day.isoformat(), "notes": notes + vnotes, "vix": vix, "results": res, "parity": parity,
            "adverse_net": sum(adv), "n_events": len(events), "n_universe": len(universe)}


def report(runs: list[dict], relaxed_runs: list[dict] = ()) -> str:
    L = ["# GS-SIP-1 replay: EXPLORATORY parity and smoke runs (NOT evidence)", "",
         "**Generated by** `nfce_engine/tools/gs_replay.py` on recorded minute quotes. **Not a test of the edge and not a "
         "result:** the inputs are minute snapshots stamped at request start, bars and history after 21 Oct are patched "
         "from approximate sources, and the waits are widened to 75 s. Its only purposes are (1) parity: two fresh "
         "runs and the bridge-adapter path must produce byte-identical intents and fills; (2) a smoke test that the "
         "engine runs end to end on real data shapes. No profit or loss figure below says anything about GS-SIP-1.", ""]
    for r in list(runs) + [dict(x, relaxed=True) for x in relaxed_runs]:
        if r.get("relaxed") and r is not None and r["day"] == (relaxed_runs[0]["day"] if relaxed_runs else None):
            L += ["# Relaxed smoke runs (NOT the registered rule)", "",
                  "Selection grace 75 s (the 09:18 bar is only known at the next minute snapshot) and RVOL from >= 12 of "
                  "the 14 previous windows (23 Oct's opening was not recorded). These exist only to push real books "
                  "through the fill, stop and exit code; the rule as registered selects nothing on these days.", ""]
        L += [f"## {r['day']}" + (" (relaxed)" if r.get("relaxed") else ""), f"- universe {r['n_universe']} stocks, {r['n_events']:,} events; VIX used "
              f"{r['vix'][0]:.2f} (5-session change {r['vix'][1]:+.1%})",
              f"- **parity (replay ×2 = adapter): {'OK' if r['parity'] else 'MISMATCH'}**"]
        L += [f"- note: {n}" for n in r["notes"]]
        L += ["", "| Branch | Selected | Opportunities | Filled | Net ₹ (exploratory) | Unresolved |", "|---|---:|---:|---:|---:|---:|"]
        for x in r["results"]:
            ops = x["opportunities"]
            L.append(f"| {x['branch']} {x['scenario']} | {len(x['selected'])} | {len(ops)} | "
                     f"{sum(1 for o in ops if o['qty'] > 0)} | {x['net']:,.0f} | {len(x['unresolved'])} |")
        L.append(f"| P adverse (from strict) | | | | {r['adverse_net']:,.0f} | |")
        st = r["results"][0]["opportunities"]
        reasons: dict = {}
        for o in st:
            k = o["status"] + (f" ({o['reasons'][0]})" if o["reasons"] else "")
            reasons[k] = reasons.get(k, 0) + 1
        L += ["", "P strict, opportunity outcomes: " + ", ".join(f"{k}: {v}" for k, v in sorted(reasons.items())), ""]
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("days", nargs="*")
    ap.add_argument("--no-write", action="store_true")
    x = ap.parse_args()
    all_days = quote_days()
    days = [date.fromisoformat(d) for d in x.days] if x.days else all_days
    books_by_day = {d: load_books(d) for d in sorted(set(all_days) | set(days)) if d <= max(days)}
    runs = [run_day(d, books_by_day) for d in days]
    relaxed = [run_day(d, books_by_day, configs(True)) for d in days]
    txt = report(runs, relaxed)
    print(txt)
    if not x.no_write:
        REPORT.write_text(txt)


if __name__ == "__main__":
    main()
