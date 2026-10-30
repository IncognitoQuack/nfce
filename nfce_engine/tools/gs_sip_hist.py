"""GS-SIP-1 on 3-minute history: the development test of ../evidence/gs_sip_1_development_protocol.md.

  nice -n 15 ../nfce_bridge/.venv/bin/python tools/gs_sip_hist.py run [--workers 3]     (stage 1 + every report)

Stage 1 (per stock, parallel): every stock-day with RVOL >= 1 and ATR14/prev close >= 1% (the ranking pool), its
direction, boundary and, for each exit configuration (A0 / C1 / C3), the simulated M and P outcomes per share.
Stage 2 (per day, portfolio): top 20 by RVOL (C2: among RVOL >= 2), sizing by risk and ticket, at most 4 positions
open or pending, the DG latch, event days, then the daily series per branch. Bars cannot prove passive fills: P is a
scenario. Development data (partly seen through study engine v2): no result here is evidence for the forward test.
"""
from __future__ import annotations

import argparse
import json
import math
import pickle
import sqlite3
import sys
from datetime import date, datetime
from multiprocessing import get_context
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gs import calendar as cal  # noqa: E402
from gs import costs as gc  # noqa: E402
from gs import evaluate as ev  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = Path.home() / "Downloads" / "nfce_data"
HIST3M, DAILY = DATA / "hist3m_fo", DATA / "daily"
WORK = DATA / "gs_dev"
QUOTES = [ROOT / "nfce_bridge" / "data" / f"study_quotes_{d}.db" for d in ("20261022", "20261023", "20261026")]
REPORT = ROOT / "evidence" / "gs_sip_1_development.md"
SEED = 20261026
E0, TICKET, RISK = 500_000.0, 100_000.0, 0.0025
TICK = 0.05
SLOTS = 125                                    # 3-minute bars 09:15 .. 15:27
OPEN_MIN = 9 * 60 + 15
S_FIRST = (9 * 60 + 30 - OPEN_MIN) // 3        # 5: the first trigger bar starts 09:30
S_1515 = (15 * 60 + 15 - OPEN_MIN) // 3        # 120
BUCKETS = ((555, "0915"), (570, "0930"), (600, "1000"), (690, "1130"), (840, "1400"))
CONFIGS = {"A0": (0.5, 11 * 60 + 30), "C1": (1.0, 11 * 60 + 30), "C3": (0.5, 10 * 60 + 30)}   # stop x ATR, last close
DG_R0 = RISK * E0


# ---------------------------------------------------------------- spreads
def bucket_of(minute: int) -> str:
    b = BUCKETS[0][1]
    for m, name in BUCKETS:
        if minute >= m:
            b = name
    return b


def measure_spreads(dbs=QUOTES) -> dict:
    """{symbol: {bucket: median half-spread as a fraction}, "_all": {bucket: ...}} from recorded quotes."""
    parts = []
    for db in dbs:
        if not Path(db).exists():
            continue
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        parts.append(pd.read_sql_query("select ts, symbol, bid, ask from q where symbol like 'NSE_EQ:%' "
                                       "and bid > 0 and ask >= bid", con))
        con.close()
    q = pd.concat(parts)
    t = pd.to_datetime(q["ts"].str[:19])
    q["m"] = t.dt.hour * 60 + t.dt.minute
    q = q[(q["m"] >= 555) & (q["m"] < 930)]
    q["b"] = [bucket_of(m) for m in q["m"]]
    q["hs"] = (q["ask"] - q["bid"]) / (q["ask"] + q["bid"])
    q["sym"] = q["symbol"].str[7:]
    out = {"_all": q.groupby("b")["hs"].median().to_dict()}
    for (s, b), v in q.groupby(["sym", "b"])["hs"].median().items():
        out.setdefault(s, {})[b] = float(v)
    return out


def hs_by_slot(spreads: dict, sym: str) -> np.ndarray:
    """Half-spread (fraction) for each of the 125 slots of a stock (the bucket of the bar's start)."""
    mine, alls = spreads.get(sym, {}), spreads["_all"]
    return np.array([mine.get(bucket_of(OPEN_MIN + 3 * k), alls[bucket_of(OPEN_MIN + 3 * k)]) for k in range(SLOTS)])


# ---------------------------------------------------------------- per-stock inputs
def load_3m(path: Path) -> pd.DataFrame:
    d = pd.read_pickle(path)
    d.index = pd.DatetimeIndex(d.index).tz_convert(cal.IST)
    return d[~d.index.duplicated(keep="first")].sort_index()


def grid(d: pd.DataFrame, sessions: list[date]) -> dict:
    """Arrays (n_sessions, 125) of O/H/L/C/V over the CALENDAR sessions (NaN where the stock has no bar)."""
    pos = {s: i for i, s in enumerate(sessions)}
    n = len(sessions)
    out = {k: np.full((n, SLOTS), np.nan) for k in ("O", "H", "L", "C", "V")}
    days = d.index.date
    mins = d.index.hour * 60 + d.index.minute
    slot = (mins - OPEN_MIN) // 3
    ok = (slot >= 0) & (slot < SLOTS) & ((mins - OPEN_MIN) % 3 == 0)
    rows = np.array([pos.get(x, -1) for x in days])
    ok &= rows >= 0
    for k, col in (("O", "open"), ("H", "high"), ("L", "low"), ("C", "close"), ("V", "volume")):
        out[k][rows[ok], slot[ok]] = d[col].to_numpy(float)[ok]
    return out


def wilder_atr(daily: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = daily["high"].to_numpy(float), daily["low"].to_numpy(float), daily["close"].to_numpy(float)
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    a = np.full(len(daily), np.nan)
    if len(tr) >= n:
        x = tr[:n].mean()
        a[n] = x
        for i in range(n, len(tr)):
            x = (x * (n - 1) + tr[i]) / n
            a[i + 1] = x
    return pd.Series(a, index=daily.index)


def daily_asof(sym: str, sessions: list[date]) -> tuple[np.ndarray, np.ndarray]:
    """(ATR14, previous close) known before each session: from the previous calendar session's daily bar only."""
    f = DAILY / f"{sym}_1d.pkl"
    n = len(sessions)
    atr, pc = np.full(n, np.nan), np.full(n, np.nan)
    if not f.exists():
        return atr, pc
    d = pd.read_pickle(f)
    idx = pd.DatetimeIndex(d.index)
    d.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    d = d[~d.index.duplicated(keep="last")].sort_index()
    a = wilder_atr(d)
    by = {i.date(): (a.iloc[k], d["close"].iloc[k]) for k, i in enumerate(d.index)}
    for i, s in enumerate(sessions):
        try:
            prev = cal.prev_session(s)
        except cal.CalendarError:                                     # the calendar's first session
            continue
        if prev in by:
            atr[i], pc[i] = by[prev]
    return atr, pc


# ---------------------------------------------------------------- stage 1: one stock
def simulate_exit(g: dict, rows: np.ndarray, k: np.ndarray, entry: np.ndarray, side: np.ndarray, stop_dist: np.ndarray,
                  hs: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """From fill bar k: stop (gap = the worse open) or the 15:15 open, minus the half-spread. (exit price, slot, why)."""
    L, H, O, C = g["L"][rows], g["H"][rows], g["O"][rows], g["C"][rows]
    n = len(rows)
    px, slot, why = np.full(n, np.nan), np.full(n, -1), np.array([""] * n, dtype=object)
    cols = np.arange(SLOTS)
    stop = entry - side * stop_dist
    for i in range(n):
        s = side[i]
        rng = (cols >= k[i]) & (cols < S_1515)
        adverse = (L[i] <= stop[i]) if s > 0 else (H[i] >= stop[i])
        hit = np.flatnonzero(rng & adverse & np.isfinite(L[i]))
        if len(hit):
            t = hit[0]
            base = stop[i]
            if t > k[i] and np.isfinite(O[i, t]) and ((O[i, t] < stop[i]) if s > 0 else (O[i, t] > stop[i])):
                base = O[i, t]                                     # gapped through the stop
            px[i], slot[i], why[i] = base * (1 - s * hs[t]), t, "stop"
            continue
        after = np.flatnonzero((cols >= max(S_1515, k[i])) & np.isfinite(O[i]))
        if len(after):
            t = after[0]
            px[i], slot[i], why[i] = O[i, t] * (1 - s * hs[t]), t, "time"
        else:
            last = np.flatnonzero(np.isfinite(C[i]))
            t = last[-1] if len(last) else k[i]
            px[i], slot[i], why[i] = C[i, t] * (1 - s * hs[min(t, SLOTS - 1)]), t, "last"
    return px, slot, why


def stock_rows(sym: str, path: Path, sessions: list[date], spreads: dict) -> pd.DataFrame:
    g = grid(load_3m(path), sessions)
    atr, pc = daily_asof(sym, sessions)
    hs = hs_by_slot(spreads, sym)
    ow = g["V"][:, 0] + g["V"][:, 1]                                   # NaN if either bar is missing
    okw = np.isfinite(ow) & (ow > 0)
    base = pd.Series(np.where(okw, ow, np.nan)).rolling(14, min_periods=14).mean().shift(1).to_numpy()
    rv = np.where(okw & np.isfinite(base) & (base > 0), ow / base, np.nan)
    o0, c1 = g["O"][:, 0], g["C"][:, 1]
    hi, lo = np.fmax(g["H"][:, 0], g["H"][:, 1]), np.fmin(g["L"][:, 0], g["L"][:, 1])
    pool = np.isfinite(rv) & (rv >= 1) & np.isfinite(atr) & (atr > 0) & np.isfinite(pc) & (atr / pc >= 0.01)
    rows = np.flatnonzero(pool)
    if not len(rows):
        return pd.DataFrame()
    side = np.sign(c1[rows] - o0[rows]).astype(int)
    bnd = np.where(side > 0, hi[rows], lo[rows])
    out = pd.DataFrame({"day": [sessions[r] for r in rows], "sym": sym, "rvol": rv[rows], "atr": atr[rows],
                        "pc": pc[rows], "side": side, "boundary": bnd})
    live = side != 0
    for name, (mult, last_close) in CONFIGS.items():
        s_last = (last_close - 3 - OPEN_MIN) // 3                       # the last trigger bar's start slot
        C = g["C"][rows]
        beyond = np.where(side[:, None] > 0, C > bnd[:, None], C < bnd[:, None])
        beyond[:, :S_FIRST] = False
        beyond[:, s_last + 1:] = False
        has = beyond.any(1) & live
        j = np.where(has, beyond.argmax(1), -1)
        nxt = j + 1
        ok = has & (nxt < SLOTS)
        ok[ok] = np.isfinite(g["O"][rows[ok], nxt[ok]])
        res = {f"{name}_trig": np.where(ok, j, -1)}
        for b in ("M", "P"):
            res.update({f"{name}_{b}_entry": np.full(len(rows), np.nan), f"{name}_{b}_exit": np.full(len(rows), np.nan),
                        f"{name}_{b}_xslot": np.full(len(rows), -1)})
        res[f"{name}_P_strict"] = np.zeros(len(rows), bool)
        res[f"{name}_P_touch"] = np.zeros(len(rows), bool)
        idx = np.flatnonzero(ok)
        if len(idx):
            r, jj, kk, sd = rows[idx], j[idx], nxt[idx], side[idx]
            # M: the next bar's open plus the half-spread
            m_entry = g["O"][r, kk] * (1 + sd * hs[kk])
            # P: limit at min(boundary, bid) / max(boundary, ask); bid/ask = the decision bar's close -/+ half-spread
            cj = g["C"][r, jj]
            raw = np.where(sd > 0, np.minimum(bnd[idx], cj * (1 - hs[jj])), np.maximum(bnd[idx], cj * (1 + hs[jj])))
            lim = np.where(sd > 0, np.floor(raw / TICK + 1e-9) * TICK, np.ceil(raw / TICK - 1e-9) * TICK)
            lo_n, hi_n = g["L"][r, kk], g["H"][r, kk]
            strict = np.where(sd > 0, lo_n <= lim - TICK + 1e-9, hi_n >= lim + TICK - 1e-9)
            touch = np.where(sd > 0, lo_n <= lim + 1e-9, hi_n >= lim - 1e-9)
            dist = mult * atr[r]
            mx, ms, _ = simulate_exit(g, r, kk, m_entry, sd, dist, hs)
            px, ps, _ = simulate_exit(g, r, kk, lim, sd, dist, hs)
            res[f"{name}_M_entry"][idx], res[f"{name}_M_exit"][idx], res[f"{name}_M_xslot"][idx] = m_entry, mx, ms
            res[f"{name}_P_entry"][idx], res[f"{name}_P_exit"][idx], res[f"{name}_P_xslot"][idx] = lim, px, ps
            res[f"{name}_P_strict"][idx], res[f"{name}_P_touch"][idx] = strict, touch
        res[f"{name}_hs"] = np.where(ok, hs[np.clip(nxt, 0, SLOTS - 1)], np.nan)
        for k, v in res.items():
            out[k] = v
    return out


def _job(args):
    files, sessions, spreads = args
    parts = []
    for f in files:
        try:
            parts.append(stock_rows(f.stem.replace("_3m", ""), f, sessions, spreads))
        except Exception as exc:                                       # one bad file never stops the run
            print("skip", f.name, repr(exc)[:120], flush=True)
    return pd.concat([p for p in parts if len(p)], ignore_index=True) if parts else pd.DataFrame()


def stage1(workers: int = 3) -> tuple[pd.DataFrame, list[date], dict]:
    sessions = cal.sessions(date(2022, 1, 3), date(2026, 10, 19))
    spreads = measure_spreads()
    files = [f for f in sorted(HIST3M.glob("*_3m.pkl")) if f.stem != "INDIAVIX_3m"]
    jobs = [(files[i::workers], sessions, spreads) for i in range(workers)]
    with get_context("spawn").Pool(workers) as pool:
        parts = pool.map(_job, jobs)
    c = pd.concat([p for p in parts if len(p)], ignore_index=True)
    return c, sessions, spreads


# ---------------------------------------------------------------- stage 2: the portfolio, per day
def equity_fees(buy_px, sell_px, qty):
    """Vectorized gs.costs.equity_fill_fee(+1, buy) + (-1, sell) (a test checks they agree)."""
    bv, sv = buy_px * qty, sell_px * qty
    brk = 2 * gc.BROKERAGE
    exch = gc.EQ_EXCH * (bv + sv)
    sebi = gc.SEBI_FEE * (bv + sv)
    return gc.EQ_STT_INTRADAY * sv + exch + sebi + gc.EQ_STAMP * bv + brk + gc.GST * (brk + exch + sebi)


def vix_regime(sessions: list[date]) -> dict:
    v = pd.read_pickle(DAILY / "INDIAVIX_1d.pkl")
    idx = pd.DatetimeIndex(v.index)
    v.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    close = v["close"]
    out = {}
    for s in sessions:
        x = close[close.index < pd.Timestamp(s)]
        if len(x) < 6:
            out[s] = 0.0
            continue
        lv, rise = float(x.iloc[-1]), float(x.iloc[-1] / x.iloc[-6] - 1)
        out[s] = 0.25 if (lv > 25 or rise > 0.20) else (0.5 if lv > 20 else 1.0)
    return out


def size(entry, atr, hs, mult, regime):
    """Risk 0.25% of E0 x regime with L = (mult + 0.25) ATR + half-spread + fees per share; ticket <= Rs 1 L."""
    b = RISK * E0 * regime
    base = (mult + 0.25) * atr + hs * entry
    q = np.floor(np.minimum(TICKET / entry, b / np.maximum(base, 1e-9)))
    for _ in range(3):
        fee_ps = equity_fees(entry, entry, np.maximum(q, 1)) / np.maximum(q, 1)
        q = np.floor(np.minimum(TICKET / entry, b / (base + fee_ps)))
    return np.maximum(q, 0)


def portfolio(c: pd.DataFrame, sessions: list[date], regime: dict, cfg: str, branch: str, rvol_min: float = 1.0,
              top_n: int = 20) -> tuple[pd.DataFrame, pd.Series]:
    """branch: "M", "P_strict", "P_touch". Returns (trades, daily net Rs over every session)."""
    mult, _ = CONFIGS[cfg]
    pool = c[c["rvol"] >= rvol_min].sort_values(["day", "rvol", "sym"], ascending=[True, False, True])
    sel = pool.groupby("day").head(top_n)
    sel = sel[(sel["side"] != 0) & (sel[f"{cfg}_trig"] >= 0)].copy()
    b = "P" if branch.startswith("P") else "M"
    sel["entry"], sel["exit"] = sel[f"{cfg}_{b}_entry"], sel[f"{cfg}_{b}_exit"]
    sel["xslot"], sel["trig"] = sel[f"{cfg}_{b}_xslot"], sel[f"{cfg}_trig"]
    sel["filled"] = True if b == "M" else sel[f"{cfg}_{branch}"]
    sel = sel[np.isfinite(sel["entry"])]
    sel["regime"] = sel["day"].map(regime).fillna(0.0)
    sel["qty"] = size(sel["entry"].to_numpy(), sel["atr"].to_numpy(), sel[f"{cfg}_hs"].to_numpy(), mult,
                      sel["regime"].to_numpy())
    buy = np.where(sel["side"] > 0, sel["entry"], sel["exit"])
    sell = np.where(sel["side"] > 0, sel["exit"], sel["entry"])
    q = sel["qty"].to_numpy()
    sel["gross"] = sel["side"] * (sel["exit"] - sel["entry"]) * q
    sel["fees"] = np.where(q > 0, equity_fees(buy, sell, np.maximum(q, 1)), 0.0)
    sel["net"] = np.where(q > 0, sel["gross"] - sel["fees"], 0.0)
    sel["notional"] = sel["entry"] * q
    rbi = {d for d, k in cal.EVENTS if k == "rbi"}
    budget = {d for d, k in cal.EVENTS if k == "budget"}
    keep = []
    for day, g in sel.sort_values(["day", "trig", "sym"]).groupby("day", sort=True):
        if day in budget:
            continue
        busy: list[int] = []                                  # end slot of each open/pending position
        realized: list[tuple[int, float]] = []
        dg = False
        for r in g.itertuples():
            t = r.trig + 1                                    # the order goes in at the next bar
            if day in rbi and 5 <= r.trig + 1 <= 25:          # RBI: no entries 09:30-10:30
                continue
            if r.qty <= 0:
                continue
            peak = 0.0
            acc = 0.0
            for s, v in sorted(realized):
                if s > r.trig:
                    break
                acc += v
                peak = max(peak, acc)
                if peak >= 2 * DG_R0 and acc <= 0.5 * peak:
                    dg = True
            if dg:
                continue
            busy = [e for e in busy if e >= t]
            if len(busy) >= 4:
                continue
            if r.filled:
                busy.append(int(r.xslot))
                realized.append((int(r.xslot), float(r.net)))
            else:
                busy.append(t)                                # the unfilled order held a slot for one bar
            keep.append(r.Index)
    tr = sel.loc[keep]
    filled = tr[tr["filled"].astype(bool)]
    daily = filled.groupby("day")["net"].sum().reindex(sessions, fill_value=0.0)
    return tr, daily


def adverse(tr: pd.DataFrame, sessions: list[date]) -> pd.Series:
    f = tr[tr["filled"].astype(bool)].copy()
    k = int(math.ceil(0.25 * len(f)))
    best = f.sort_values(["net", "sym", "day"], ascending=[False, True, True]).index[:k]
    f.loc[best, "net"] = 0.0
    rest = f.index.difference(best)
    f.loc[rest, "net"] = f.loc[rest, "net"] - 2e-4 * f.loc[rest, "notional"]
    return f.groupby("day")["net"].sum().reindex(sessions, fill_value=0.0)


def summarize(tr: pd.DataFrame, daily: pd.Series, days: list[date], reps: int = ev.REPS) -> dict:
    d = daily.reindex(days, fill_value=0.0) / E0 * 1e4
    t = tr[tr["day"].isin(set(days))]
    f = t[t["filled"].astype(bool) & (t["qty"] > 0)]
    x = d.to_numpy()
    bm = ev.boot_means(x, ev.BLOCK, reps, ev.SEED) if len(x) > 2 else np.array([np.nan])
    return {"sessions": len(days), "opportunities": int(len(t)), "fills": int(len(f)),
            "fill_rate": float(len(f) / len(t)) if len(t) else math.nan,
            "gross_bp": float((f["gross"] / f["notional"]).mean() * 1e4) if len(f) else math.nan,
            "net_bp": float((f["net"] / f["notional"]).mean() * 1e4) if len(f) else math.nan,
            "bp_day": float(x.mean()), "ci95": (float(np.quantile(bm, 0.025)), float(np.quantile(bm, 0.975))),
            "net_inr": float(daily.reindex(days, fill_value=0.0).sum())}


# ---------------------------------------------------------------- runs and the report
def periods(sessions: list[date]) -> dict:
    dev = [s for s in sessions if s.year <= 2024]
    chk = [s for s in sessions if s.year >= 2025]
    rng = np.random.default_rng(SEED)
    sample = sorted(rng.choice(np.array(dev, dtype=object), 250, replace=False).tolist())
    out = {str(y): [s for s in sessions if s.year == y] for y in range(2022, 2027)}
    out |= {"2022-24": dev, "2025-26": chk, "sample 250 of 2022-24": sample, "all": sessions}
    return out


def evaluate_rule(c, sessions, regime, cfg, rvol_min, keys, reps=ev.REPS) -> dict:
    res = {}
    per = periods(sessions)
    for branch in ("M", "P_strict", "P_touch"):
        tr, daily = portfolio(c, sessions, regime, cfg, branch, rvol_min)
        res[branch] = {k: summarize(tr, daily, per[k], reps) for k in keys}
        if branch == "P_strict":
            adv = adverse(tr, sessions)
            res["P_adverse"] = {k: summarize(tr, adv, per[k], reps) for k in keys}
    return res


def fmt(s: dict) -> str:
    ci = s["ci95"]
    return (f"{s['opportunities']:,} | {s['fills']:,} | {s['gross_bp']:+.1f} | {s['net_bp']:+.1f} | "
            f"**{s['bp_day']:+.2f}** | {ci[0]:+.2f} … {ci[1]:+.2f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("--workers", type=int, default=3)
    x = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    cache = WORK / "stage1.pkl"
    if cache.exists():
        c, sessions, spreads = pickle.loads(cache.read_bytes())
    else:
        c, sessions, spreads = stage1(x.workers)
        cache.write_bytes(pickle.dumps((c, sessions, spreads)))
    regime = vix_regime(sessions)
    per = periods(sessions)
    # 1) the as-designed rule, everything
    keys_all = list(per)
    a0 = evaluate_rule(c, sessions, regime, "A0", 1.0, keys_all)
    # 2) candidates on 2022-24 only (the selection)
    cand = {"C1": ("C1", 1.0), "C2": ("A0", 2.0), "C3": ("C3", 1.0)}
    dev = {k: evaluate_rule(c, sessions, regime, cfg, rv, ["2022-24"]) for k, (cfg, rv) in cand.items()}
    base_dev = {b: a0[b]["2022-24"]["bp_day"] for b in ("M", "P_strict")}
    qual = [k for k in cand if all(dev[k][b]["2022-24"]["bp_day"] > base_dev[b] for b in ("M", "P_strict"))]
    winner = max(qual, key=lambda k: (dev[k]["P_strict"]["2022-24"]["bp_day"], -list(cand).index(k))) if qual else None
    check, adopted = None, "A0"
    if winner:
        cfg, rv = cand[winner]
        check = evaluate_rule(c, sessions, regime, cfg, rv, ["2025-26"])
        if all(check[b]["2025-26"]["bp_day"] > a0[b]["2025-26"]["bp_day"] for b in ("M", "P_strict")):
            adopted = winner
    out = {"a0": a0, "dev": dev, "qualifiers": qual, "winner": winner, "check": check, "adopted": adopted,
           "spreads_all": spreads["_all"], "n_pool": int(len(c))}
    (WORK / "results.json").write_text(json.dumps(out, default=str, indent=1))
    print(json.dumps({"qualifiers": qual, "winner": winner, "adopted": adopted}, indent=1))
    for b in ("M", "P_strict", "P_touch", "P_adverse"):
        print(b, {k: round(a0[b][k]["bp_day"], 3) for k in keys_all})


if __name__ == "__main__":
    main()
