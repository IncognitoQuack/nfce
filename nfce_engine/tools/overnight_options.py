"""Overnight defined-risk NIFTY option selling, forward paper scorer (../evidence/overnight_options_protocol.md).

  python tools/overnight_options.py score  [--data DIR]   (every recorded entry day with a recorded next session)
  python tools/overnight_options.py stress                (historical overnight gaps vs the VIX-implied SD)

Reads the recorded chains (nfce_bridge/data/study_chain_YYYYMMDD.db) and nfce.db.range_forecasts, read-only.
No orders: entries and exits are the recorded quotes at the registered times.
"""
from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce import costs  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "nfce_bridge" / "data"
LOT, STEP = 65, 50
ENTRY, IV_REF, EXIT, EXIT_LAST = "15:20:00", "11:00:00", "09:16:00", "09:30:00"
IV_RISE, F2_PCT, F2_MIN = 1.05, 0.80, 5
WIDEN = 1.5


# ---------------------------------------------------------------- reading
def read_chain(db: Path, underlying: str = "NIFTY") -> pd.DataFrame:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    q = pd.read_sql_query("select ts, expiry, spot, strike, typ, ltp, bid, ask, iv from chain where underlying = ?",
                          con, params=(underlying,))
    con.close()
    q["time"] = q["ts"].str[11:19]
    q["expiry"] = q["expiry"].str[:10]
    return q


def snapshot(ch: pd.DataFrame, at: str, until: str | None = None) -> pd.DataFrame:
    """The first snapshot with time >= at (and <= until, if given)."""
    t = ch.loc[(ch["time"] >= at) & ((ch["time"] <= until) if until else True), "ts"]
    return ch[ch["ts"] == t.min()] if len(t) else ch.iloc[0:0]


def pick_expiry(expiries, next_session: date) -> str | None:
    later = sorted(e for e in set(expiries) if date.fromisoformat(e) > next_session)
    return later[0] if later else None


def atm(snap: pd.DataFrame, expiry: str) -> tuple[float, float, float]:
    """(spot, ATM strike, ATM IV %) of one expiry in one snapshot."""
    x = snap[snap["expiry"] == expiry]
    s = float(x["spot"].iloc[0])
    strikes = np.unique(x["strike"])
    k = float(strikes[np.argmin(np.abs(strikes - s))])
    iv = x.loc[x["strike"] == k, "iv"].astype(float)
    return s, k, float(iv.mean())


# ---------------------------------------------------------------- the structures
def legs(spot: float, k: float, iv: float, kind: str) -> list[tuple[str, float, int]]:
    """[(typ, strike, qty sign)] with -1 = sold. W = 2 SD rounded up to 50; IC shorts at +-1 SD (nearest 50, >= 50)."""
    sd = spot * iv / 100 * math.sqrt(1 / 252)
    w = STEP * math.ceil(2 * sd / STEP)
    if kind == "IF":
        return [("CE", k, -1), ("PE", k, -1), ("CE", k + w, 1), ("PE", k - w, 1)]
    a = max(STEP, STEP * round(sd / STEP))
    return [("CE", k + a, -1), ("PE", k - a, -1), ("CE", k + a + w, 1), ("PE", k - a - w, 1)]


def quote(snap: pd.DataFrame, expiry: str, typ: str, strike: float) -> pd.Series | None:
    x = snap[(snap["expiry"] == expiry) & (snap["typ"] == typ) & (snap["strike"] == strike)]
    return x.iloc[0] if len(x) else None


def fill(q, sign: int, opening: bool, widen: float = 1.0) -> float | None:
    """Sold at entry -> bid; bought at entry -> ask; reversed at exit. widen > 1 moves the fill away from the mid."""
    if q is None or not (q["bid"] > 0 and q["ask"] > 0):
        return None
    mid, half = (q["bid"] + q["ask"]) / 2, (q["ask"] - q["bid"]) / 2 * widen
    pay = (sign > 0) if opening else (sign < 0)                    # we buy -> we pay the ask side
    return float(mid + half if pay else mid - half)


def session(entry_snap, exit_snaps, expiry, kind, widen=1.0) -> dict:
    s, k, iv = atm(entry_snap, expiry)
    lg = legs(s, k, iv, kind)
    ein, flagged = [], False
    for typ, strike, sign in lg:
        p = fill(quote(entry_snap, expiry, typ, strike), sign, True, widen)
        if p is None:
            return {"status": "no quote", "kind": kind}
        ein.append(p)
    eout = []
    for (typ, strike, sign), pin in zip(lg, ein):
        p = None
        for snap in exit_snaps:                                      # 09:16, then later snapshots up to 09:30
            p = fill(quote(snap, expiry, typ, strike), sign, False, widen)
            if p is not None:
                break
        if p is None:
            flagged = True
            q = quote(exit_snaps[0], expiry, typ, strike) if exit_snaps else None
            q0 = quote(entry_snap, expiry, typ, strike)
            spread = float(q0["ask"] - q0["bid"]) * WIDEN
            last = float(q["ltp"]) if q is not None and q["ltp"] > 0 else float(q0["ltp"])
            p = last + spread if sign < 0 else max(0.0, last - spread)
        eout.append(p)
    gross = sum(sign * (pout - pin) for (_, _, sign), pin, pout in zip(lg, ein, eout)) * LOT
    fees = 0.0
    for (_, _, sign), pin, pout in zip(lg, ein, eout):
        buy, sell = (pin, pout) if sign > 0 else (pout, pin)
        fees += costs.option_fees(buy, sell, LOT, costs.CURRENT).total
    credit = sum(-sign * p for (_, _, sign), p in zip(lg, ein))
    width = lg[2][1] - lg[0][1]
    entry_fees = fees / 2
    R = (width - credit) * LOT + entry_fees
    return {"status": "ok", "kind": kind, "spot": s, "atm": k, "iv": iv, "credit": credit * LOT, "width": width,
            "gross": gross, "fees": fees, "net": gross - fees, "R": R, "net_r": (gross - fees) / R,
            "flagged": flagged, "legs": lg}


# ---------------------------------------------------------------- filters
def f1_iv_rising(ch: pd.DataFrame, entry_snap: pd.DataFrame, expiry: str) -> tuple[bool, float]:
    ref = snapshot(ch, IV_REF)
    if ref.empty or (ref["expiry"] == expiry).sum() == 0:
        return False, math.nan
    iv_now, iv_ref = atm(entry_snap, expiry)[2], atm(ref, expiry)[2]
    r = iv_now / iv_ref if iv_ref > 0 else math.nan
    return bool(r >= IV_RISE), r


def last_forecasts(nfce_db: Path) -> pd.Series:
    """NIFTY's last M1 forecast of each session (exp(q50)), indexed by date."""
    con = sqlite3.connect(f"file:{nfce_db}?mode=ro", uri=True)
    f = pd.read_sql_query("select bar_close, q50 from range_forecasts where root = 'NIFTY' and model = 'M1'", con)
    con.close()
    f["day"] = f["bar_close"].str[:10]
    f = f[f["bar_close"].str[11:19] <= ENTRY].sort_values("bar_close")
    return np.exp(f.groupby("day")["q50"].last())


def f2_large_move(fc: pd.Series, day: str) -> tuple[bool | None, float]:
    if day not in fc.index:
        return None, math.nan
    prior = fc[fc.index < day]
    if len(prior) < F2_MIN:
        return None, float(fc[day])
    return bool(fc[day] > prior.quantile(F2_PCT)), float(fc[day])


# ---------------------------------------------------------------- scoring all recorded sessions
def chain_days(data: Path) -> list[tuple[str, Path]]:
    out = []
    for f in sorted(data.glob("study_chain_*.db")):
        d = f.stem.split("_")[-1]
        out.append((f"{d[:4]}-{d[4:6]}-{d[6:]}", f))
    return out


def score(data: Path = DATA, nfce_db: Path | None = None) -> pd.DataFrame:
    days = chain_days(data)
    fc = last_forecasts(nfce_db or data / "nfce.db")
    rows = []
    for (d, f), nxt in zip(days, days[1:] + [None]):
        ch = read_chain(f)
        es = snapshot(ch, ENTRY)
        base = {"day": d}
        if es.empty:
            rows.append(base | {"status": "no entry snapshot"})
            continue
        if nxt is None:
            rows.append(base | {"status": "unresolved (no next session yet)"})
            continue
        nch = read_chain(nxt[1])
        ex = [g for _, g in nch[(nch["time"] >= EXIT) & (nch["time"] <= EXIT_LAST)].groupby("ts")]
        exp = pick_expiry(es["expiry"].unique(), date.fromisoformat(nxt[0]))
        if not ex or exp is None:
            rows.append(base | {"status": "unresolved (no exit snapshot)" if not ex else "no expiry"})
            continue
        f1, iv_ratio = f1_iv_rising(ch, es, exp)
        f2, fcv = f2_large_move(fc, d)
        skip = "F1 IV rising" if f1 else ("F2 large move" if f2 else "")
        for kind in ("IF", "IC"):
            r = session(es, ex, exp, kind)
            w = session(es, ex, exp, kind, WIDEN)
            rows.append(base | {"exit_day": nxt[0], "expiry": exp, "iv_ratio": iv_ratio, "f2": f2, "forecast": fcv,
                                "skip": skip, "net_widened": w.get("net")} | {k: v for k, v in r.items() if k != "legs"})
    return pd.DataFrame(rows)


def judge(t: pd.DataFrame, kind: str, filtered: bool = True) -> dict:
    from scipy.stats import t as student
    if "kind" not in t:                                             # no session scored yet
        return {"n": 0}
    x = t[(t["kind"] == kind) & (t["status"] == "ok")]
    if filtered:
        x = x[x["skip"] == ""]
    n = len(x)
    if n < 2:
        return {"n": n}
    m, sd = x["net"].mean(), x["net"].std(ddof=1)
    tt = m / (sd / math.sqrt(n)) if sd > 0 else 0.0
    eq = x["net"].cumsum()
    return {"n": n, "mean": float(m), "p": float(student.sf(tt, n - 1)), "win": float((x["net"] > 0).mean()),
            "worst": float(x["net"].min()), "mean_widened": float(x["net_widened"].mean()),
            "maxdd": float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max()),
            "mean_r": float(x["net_r"].mean()),
            "pass": bool(n >= 40 and m > 0 and student.sf(tt, n - 1) < 0.025 and x["net_widened"].mean() > 0)}


# ---------------------------------------------------------------- stress check (history)
def stress(hist5m: Path, vix3m: Path) -> dict:
    sys.path.insert(0, str(ROOT / "nfce_engine"))
    from tools import study as s1
    n = s1.frame(pd.read_pickle(hist5m / "NIFTY_5m.pkl"), 5)
    close_1520 = n[n["hm"] == 15 * 60 + 15].set_index("day")["close"]          # the bar closing 15:20
    opens = n[n["first"]].set_index("day")["open"]
    v = s1.frame(pd.read_pickle(vix3m), 3)
    vix = v.groupby("day")["close"].last()
    df = pd.DataFrame({"c": close_1520, "vix": vix}).dropna()
    df["next_open"] = opens.reindex(df.index).shift(-1).to_numpy()
    df = df.dropna()
    df["gap"] = df["next_open"] / df["c"] - 1
    df["z"] = df["gap"] / (df["vix"] / 100 * math.sqrt(1 / 252))
    worst = df.reindex(df["z"].abs().sort_values(ascending=False).index).head(10)
    return {"nights": int(len(df)), "beyond_1sd": float((df["z"].abs() > 1).mean()),
            "beyond_2sd": float((df["z"].abs() > 2).mean()), "median_abs_z": float(df["z"].abs().median()),
            "worst": [(str(i.date()), round(r.gap * 100, 2), round(r.z, 2)) for i, r in worst.iterrows()],
            "first": str(df.index.min().date()), "last": str(df.index.max().date())}


# ================================================================ v2 (../evidence/overnight_options_v2_protocol.md)
# Everything above is v1, kept byte-for-byte so v1 stays reproducible (`score`). v2 below fixes A's findings:
# the next session comes from the exchange calendar, no LTP mark certifies a result (unresolved instead), the exit-fee
# reserve is separate from entry fees, wings = 1 x previous-day ATR14 rounded up to the strike step, Rs 10 L book.
from datetime import datetime, time, timedelta  # noqa: E402

from gs import calendar as cal  # noqa: E402
from gs import costs as gcosts  # noqa: E402
from gs import instruments  # noqa: E402

V2_START = date(2026, 10, 26)
BOOK, BUDGET_PCT = 1_000_000.0, 0.005
V2_ENTRY, V2_CANCEL = "15:20:00", "15:21:00"
V2_EXIT, V2_EXIT_LAST = "09:20:00", "15:15:00"
VIX_MAX, VIX_RISE_MAX, VIX_HALF = 25.0, 0.20, 20.0
ATR_N, ATR_WINDOW = 14, 100
STRESS_SPOT = (-0.10, -0.07, -0.05, -0.03, 0.0, 0.03, 0.05, 0.07, 0.10)
STRESS_IV = (-10.0, 0.0, 10.0, 20.0, 40.0)
STRESS_SPREAD = (1.0, 2.0, 5.0)
DAILY = Path.home() / "Downloads" / "nfce_data" / "daily"


def read_chain2(db: Path, underlying: str = "NIFTY") -> pd.DataFrame:
    """v2 reader: v1's columns plus the visible sizes and, when the recorder stored them (phase 0c), the request-start
    and response-received times of each chain request."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    have = {r[1] for r in con.execute("pragma table_info(chain)")}
    extra = [c for c in ("req_ts", "resp_ts") if c in have]
    cols = ", ".join(["ts", "expiry", "spot", "strike", "typ", "ltp", "bid", "ask", "bid_qty", "ask_qty", "iv"] + extra)
    q = pd.read_sql_query(f"select {cols} from chain where underlying = ?", con, params=(underlying,))
    con.close()
    q["time"] = q["ts"].str[11:19]
    q["expiry"] = q["expiry"].str[:10]
    return q


def read_daily(path: Path) -> pd.DataFrame:
    d = pd.read_pickle(path)
    d.index = pd.DatetimeIndex(d.index).tz_localize(None).normalize() if pd.DatetimeIndex(d.index).tz is not None \
        else pd.DatetimeIndex(d.index).normalize()
    return d[~d.index.duplicated(keep="last")].sort_index()


def atr14_asof(daily: pd.DataFrame, last_day: date) -> float | None:
    """Wilder ATR14 over the ATR_WINDOW completed sessions ending at last_day (inclusive), seeded with the mean of
    the first 14 true ranges of the window. None if last_day's bar is missing (the input is not available yet)."""
    d = daily[daily.index <= pd.Timestamp(last_day)]
    if d.empty or d.index[-1].date() != last_day or len(d) < ATR_N + 1:
        return None
    d = d.iloc[-(ATR_WINDOW + 1):]
    h, lo, c = d["high"].to_numpy(float), d["low"].to_numpy(float), d["close"].to_numpy(float)
    tr = np.maximum(h[1:] - lo[1:], np.maximum(abs(h[1:] - c[:-1]), abs(lo[1:] - c[:-1])))
    a = tr[:ATR_N].mean()
    for x in tr[ATR_N:]:
        a = (a * (ATR_N - 1) + x) / ATR_N
    return float(a)


def vix_state(vix: pd.DataFrame, last_day: date) -> tuple[float | None, float | None]:
    """(previous-close VIX, its 5-session change) as of last_day's close; None if not available."""
    v = vix[vix.index <= pd.Timestamp(last_day)]["close"]
    if v.empty or v.index[-1].date() != last_day or len(v) < 6:
        return None, None
    return float(v.iloc[-1]), float(v.iloc[-1] / v.iloc[-6] - 1)


def snapshots(ch: pd.DataFrame, start: str, end: str) -> list[pd.DataFrame]:
    """Snapshots (one per ts) with start <= time < end, in time order."""
    x = ch[(ch["time"] >= start) & (ch["time"] < end)]
    return [g for _, g in x.groupby("ts", sort=True)]


def valid(q) -> bool:
    return q is not None and q["bid"] > 0 and q["ask"] > 0 and q["ask"] >= q["bid"]


def fill2(q, side: int, widen: float = 1.0) -> float:
    """Marketable fill: a buy pays the ask, a sale gets the bid; widen > 1 moves both away from the mid."""
    mid, half = (q["bid"] + q["ask"]) / 2, (q["ask"] - q["bid"]) / 2 * widen
    return float(mid + half if side > 0 else max(0.0, mid - half))


def pick_strikes(snap: pd.DataFrame, expiry: str, atr: float) -> dict | None:
    """ATM K = the listed strike nearest spot (tie -> lower); wing target = ceil(ATR14 / step) x step; call wing = the
    lowest listed strike >= K + target, put wing = the highest listed strike <= K - target."""
    x = snap[snap["expiry"] == expiry]
    if x.empty:
        return None
    s = float(x["spot"].iloc[0])
    ks = np.unique(x["strike"].astype(float))
    if len(ks) < 3:
        return None
    step = float(np.min(np.diff(ks)))
    k = float(ks[np.lexsort((ks, np.abs(ks - s)))][0])
    w = step * math.ceil(atr / step - 1e-9)
    calls, puts = ks[ks >= k + w], ks[ks <= k - w]
    if not len(calls) or not len(puts):
        return None
    return {"spot": s, "K": k, "step": step, "target": w, "Kc": float(calls.min()), "Kp": float(puts.max())}


def v2_legs(st: dict) -> list[tuple[str, float, int]]:
    """(typ, strike, side) in paper order: wings first (bought, +1), then the shorts (sold, -1)."""
    return [("CE", st["Kc"], 1), ("PE", st["Kp"], 1), ("CE", st["K"], -1), ("PE", st["K"], -1)]


def _bs(spot: float, k: float, t: float, vol: float, typ: str) -> float:
    if t <= 0 or vol <= 0:
        return max(0.0, spot - k) if typ == "CE" else max(0.0, k - spot)
    d1 = (math.log(spot / k) + 0.5 * vol * vol * t) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)
    n = lambda z: 0.5 * (1 + math.erf(z / math.sqrt(2)))  # noqa: E731
    c = spot * n(d1) - k * n(d2)
    return c if typ == "CE" else c - spot + k


def exit_fee_reserve(legs_q, spot: float, exit_day: date, expiry: str, qty: float) -> float:
    """The maximum exit fees over the stress grid (spot -10%..+10%, IV -10..+40 points, spreads x1/x2/x5), priced with
    a plain Black-Scholes mark at the scheduled exit (exit_day 09:20 IST -> expiry 15:30 IST). Never from realized
    exit prices (A section 7)."""
    t = (datetime.combine(date.fromisoformat(expiry), cal.CLOSE, cal.IST)
         - datetime.combine(exit_day, time(9, 20), cal.IST)).total_seconds() / (365 * 86400)
    worst = 0.0
    for m in STRESS_SPOT:
        for dv in STRESS_IV:
            for sm in STRESS_SPREAD:
                f = 0.0
                for (typ, k, side), q in legs_q:
                    iv = float(q["iv"]) if q["iv"] and q["iv"] > 0 else 15.0
                    p = _bs(spot * (1 + m), k, t, max(1.0, iv + dv) / 100, typ)
                    half = (q["ask"] - q["bid"]) / 2 * sm
                    exit_side = -side                                   # bought wings are sold, shorts bought back
                    px = p + half if exit_side > 0 else max(0.0, p - half)
                    f += gcosts.option_fill_fee(exit_side, px, qty, exit_day).total
                worst = max(worst, f)
    return worst


def entry_fees(legs_q, qty: float, when: date, widen: float = 1.0) -> float:
    return sum(gcosts.option_fill_fee(side, fill2(q, side, widen), qty, when).total for (_, _, side), q in legs_q)


def size_lots(legs_q, st, credit, lot, spot, d, n, expiry, budget) -> tuple[int, float, float, float]:
    """Largest whole number of lots whose risk reserve (max(Wc, Wp) - C) x qty + entry fees + exit-fee reserve fits
    the budget and each leg's visible size. Returns (lots, reserve, entry fees, exit-fee reserve) for that size."""
    wmax = max(st["Kc"] - st["K"], st["K"] - st["Kp"])
    def visible(q, side):
        v = q["ask_qty"] if side > 0 else q["bid_qty"]
        return int(v // lot) if v is not None and v == v else 0
    cap = min(visible(q, side) for (_, _, side), q in legs_q)
    best = (0, math.nan, math.nan, math.nan)
    for lots in range(1, max(cap, 0) + 1):
        qty = lots * lot
        ef, xr = entry_fees(legs_q, qty, d), exit_fee_reserve(legs_q, spot, n, expiry, qty)
        r = (wmax - credit) * qty + ef + xr
        if r > budget or 1.25 * wmax * qty > BOOK:
            break
        best = (lots, r, ef, xr)
    if best[0] == 0 and cap >= 1:                                   # report what one lot would have needed
        qty = lot
        ef, xr = entry_fees(legs_q, qty, d), exit_fee_reserve(legs_q, spot, n, expiry, qty)
        best = (0, (wmax - credit) * qty + ef + xr, ef, xr)
    return best


def close_legs(legs_q, files: list[tuple[date, Path]], expiry: str, widen: float = 1.0):
    """Close in order: both shorts at the first snapshot from 09:20 where each has a valid quote, then both wings at
    the first valid snapshot at or after the later short exit. Sessions are tried in calendar order; a missing day
    file or no valid quote by 15:15 moves on to the next session. Returns ([(exit_ts, price)] in legs_q order, or
    None for a leg still open)."""
    out: list = [None] * len(legs_q)
    shorts = [i for i, ((_, _, s), _) in enumerate(legs_q) if s < 0]
    wings = [i for i, ((_, _, s), _) in enumerate(legs_q) if s > 0]
    for day, f in files:
        if f is None or not f.exists():
            continue
        ch = read_chain2(f)
        snaps = snapshots(ch, V2_EXIT, V2_EXIT_LAST)
        for group in (shorts, wings):
            for i in group:
                if out[i] is not None:
                    continue
                if group is wings and any(out[j] is None for j in shorts):
                    break
                floor = max([out[j][0] for j in shorts]) if group is wings else ""
                (typ, k, side), _ = legs_q[i]
                for sn in snaps:
                    ts = sn["ts"].iloc[0]
                    if ts < floor:
                        continue
                    q = quote(sn, expiry, typ, k)
                    if valid(q):
                        out[i] = (ts, fill2(q, -side, widen))
                        break
        if all(o is not None for o in out):
            break
    return out


def session_v2(d: date, entry_file: Path, later: list[tuple[date, Path]], atr: float, vix_mult: float,
               lot: int) -> dict:
    """One entry day. `later` = [(session, chain file)] from the next exchange session on (files may be missing)."""
    n = cal.next_session(d)
    ch = read_chain2(entry_file)
    snaps = snapshots(ch, V2_ENTRY, V2_CANCEL)
    if not snaps:
        return {"status": "no entry snapshot (15:20-15:21)", "covered": False}
    es = snaps[0]
    exp_d = cal.first_expiry_after(es["expiry"].unique(), n)
    if exp_d is None:
        return {"status": "no listed expiry after the next session", "covered": True}
    expiry = exp_d.isoformat()
    st = pick_strikes(es, expiry, atr)
    if st is None:
        return {"status": "strikes not listed", "covered": True}
    legs_q = [((t, k, s), quote(es, expiry, t, k)) for t, k, s in v2_legs(st)]
    base = {"entry_ts": es["ts"].iloc[0], "exit_day": n.isoformat(), "expiry": expiry, "spot": st["spot"],
            "atm": st["K"], "atr14": atr, "wing_target": st["target"], "Kc": st["Kc"], "Kp": st["Kp"],
            "Wc": st["Kc"] - st["K"], "Wp": st["K"] - st["Kp"], "covered": True}
    if not all(valid(q) for _, q in legs_q):
        return base | {"status": "no valid quote on a leg: not entered"}
    credit = sum(-s * fill2(q, s) for (_, _, s), q in legs_q)
    base["credit_pts"] = credit
    if not (0 < credit < min(base["Wc"], base["Wp"])):
        return base | {"status": "credit outside (0, width): not entered"}
    budget = BOOK * BUDGET_PCT * vix_mult
    lots, reserve, ef, xr = size_lots(legs_q, st, credit, lot, st["spot"], d, n, expiry, budget)
    base |= {"budget": budget, "reserve": reserve, "entry_fees": ef, "exit_fee_reserve": xr}
    if lots == 0:
        return base | {"status": "one lot exceeds the budget or visible size: not entered"}
    qty = lots * lot
    files = [(s, f) for s, f in later]
    ex = close_legs(legs_q, files, expiry)
    exw = close_legs(legs_q, files, expiry, WIDEN)
    pin = [fill2(q, s) for (_, _, s), q in legs_q]
    pin_w = [fill2(q, s, WIDEN) for (_, _, s), q in legs_q]
    base |= {"lots": lots, "qty": qty, "credit": credit * qty}
    if any(o is None for o in ex):
        return base | {"status": "unresolved (open legs)", "open_legs": [legs_q[i][0] for i, o in enumerate(ex)
                                                                        if o is None],
                       "net": None, "net_worst": -reserve, "net_best": credit * qty - ef - xr}

    def net_of(entry_px, exits, widen):
        gross = sum(s * (o[1] - p) for ((_, _, s), _), p, o in zip(legs_q, entry_px, exits)) * qty
        exit_day = lambda ts: date.fromisoformat(ts[:10])  # noqa: E731
        fx = sum(gcosts.option_fill_fee(-s, o[1], qty, exit_day(o[0])).total for ((_, _, s), _), o in zip(legs_q, exits))
        return gross, entry_fees(legs_q, qty, d, widen) + fx

    gross, fees = net_of(pin, ex, 1.0)
    gw, fw = net_of(pin_w, exw, WIDEN) if all(o is not None for o in exw) else (math.nan, math.nan)
    t_ex = [o[0] for o in ex]
    return base | {"status": "ok", "gross": gross, "fees": fees, "net": gross - fees, "net_widened": gw - fw,
                   "net_worst": gross - fees, "net_best": gross - fees, "exit_first": min(t_ex), "exit_last": max(t_ex),
                   "exit_session_late": date.fromisoformat(max(t_ex)[:10]) != n}


def score_v2(data: Path = DATA, daily_dir: Path = DAILY, start: date = V2_START, end: date | None = None) -> pd.DataFrame:
    """One row per exchange session from `start` to `end` (default: the last session with a chain file)."""
    files = {date.fromisoformat(d): f for d, f in chain_days(data)}
    if end is None:
        end = max(files) if files else start
    nifty, vix = read_daily(daily_dir / "NIFTY_1d.pkl"), read_daily(daily_dir / "INDIAVIX_1d.pkl")
    rows, blocked_until = [], None
    for d in cal.sessions(start, end):
        row = {"day": d.isoformat(), "units": 0.0}
        n = cal.next_session(d)
        if blocked_until is not None and d < blocked_until:
            rows.append(row | {"status": "blocked (an earlier structure is unresolved)", "covered": True})
            continue
        if d not in files:
            rows.append(row | {"status": "missing data (no chain file)", "covered": False})
            continue
        prev = cal.prev_session(d)
        atr = atr14_asof(nifty, prev)
        v, rise = vix_state(vix, prev)
        if atr is None or v is None:
            rows.append(row | {"status": f"pending (daily NIFTY/VIX to {prev} not loaded)", "covered": False,
                               "units": math.nan})
            continue
        row |= {"vix_prev": v, "vix_rise5": rise}
        if v > VIX_MAX or rise > VIX_RISE_MAX:
            rows.append(row | {"status": "skip: VIX gate", "covered": True})
            continue
        ev = cal.events_between(d, n)
        if ev:
            rows.append(row | {"status": f"skip: event {ev[0][1]} {ev[0][0]}", "covered": True})
            continue
        later, x = [], n
        for _ in range(5):                                      # the exit session and up to 4 more for residual legs
            later.append((x, files.get(x)))
            try:
                x = cal.next_session(x)
            except cal.CalendarError:
                break
        r = session_v2(d, files[d], later, atr, 0.5 if v > VIX_HALF else 1.0,
                       instruments.lot_size("NIFTY", d))
        row |= r
        if r["status"] == "ok":
            row["units"] = r["net"] / (BOOK * BUDGET_PCT)
            row["units_widened"] = r["net_widened"] / (BOOK * BUDGET_PCT)
            if r["exit_session_late"]:                          # legs closed after the exit session: no entry meanwhile
                blocked_until = date.fromisoformat(r["exit_last"][:10])
        elif r["status"].startswith("unresolved"):
            row["units"] = math.nan
            row["units_worst"] = r["net_worst"] / (BOOK * BUDGET_PCT)
            row["units_best"] = r["net_best"] / (BOOK * BUDGET_PCT)
            if n <= end:                                        # past its exit session and still open
                blocked_until = date.max
        rows.append(row)
    return pd.DataFrame(rows)


def stress_v2(daily_dir: Path = DAILY, hist5m: Path | None = None) -> dict:
    """Diagnostic (not a pass condition): the overnight gap 15:20 close -> next-session open, in units of the causal
    previous-day ATR14 (the v2 wing). The next session comes from the calendar; nights with missing bars are listed,
    not silently paired. Covers the calendar's span only."""
    hist5m = hist5m or Path.home() / "Downloads" / "nfce_data" / "hist5m_index"
    n5 = pd.read_pickle(hist5m / "NIFTY_5m.pkl")
    n5.index = pd.DatetimeIndex(n5.index)
    day = n5.index.tz_convert(cal.IST).date if n5.index.tz is not None else n5.index.date
    hm = n5.index.strftime("%H:%M")
    c1520 = pd.Series(n5["close"].to_numpy()[hm == "15:15"], index=np.asarray(day)[hm == "15:15"])
    opens = pd.Series(n5["open"].to_numpy()[hm == "09:15"], index=np.asarray(day)[hm == "09:15"])
    nifty = read_daily(daily_dir / "NIFTY_1d.pkl")
    out, missing = [], []
    for d in sorted(c1520.index):
        if not (cal.COVERED_FROM < d < cal.COVERED_UNTIL) or not cal.is_session(d):
            continue
        try:
            n, prev = cal.next_session(d), cal.prev_session(d)
        except cal.CalendarError:                                  # the calendar's first and last nights
            continue
        if n not in opens.index:
            missing.append(str(n))
            continue
        a = atr14_asof(nifty, prev)
        if a is None:
            continue
        g = float(opens[n] - c1520[d])
        out.append((d, g, g / a))
    z = np.array([x[2] for x in out])
    worst = sorted(out, key=lambda x: -abs(x[2]))[:10]
    return {"nights": len(out), "beyond_1atr": float((abs(z) >= 1).mean()) if len(z) else math.nan,
            "beyond_0.5atr": float((abs(z) >= 0.5).mean()) if len(z) else math.nan,
            "median_abs": float(np.median(abs(z))) if len(z) else math.nan,
            "worst": [(str(d), round(g, 1), round(x, 2)) for d, g, x in worst], "missing_next_open": missing[:20],
            "n_missing": len(missing)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["score", "stress", "score2", "stress2"])
    ap.add_argument("--data", type=Path, default=DATA)
    ap.add_argument("--daily", type=Path, default=DAILY)
    x = ap.parse_args()
    if x.cmd == "stress":
        dd = Path.home() / "Downloads" / "nfce_data"
        print(stress(dd / "hist5m_index", dd / "hist3m_fo" / "INDIAVIX_3m.pkl"))
        return
    if x.cmd == "stress2":
        print(stress_v2(x.daily))
        return
    if x.cmd == "score2":
        t = score_v2(x.data, x.daily)
        pd.set_option("display.width", 250)
        print(t.to_string(index=False))
        return
    t = score(x.data)
    pd.set_option("display.width", 200)
    print(t.drop(columns=[c for c in ("legs",) if c in t]).to_string(index=False))
    for kind in ("IF", "IC"):
        print(kind, "filtered", judge(t, kind), "| unfiltered", judge(t, kind, False))


if __name__ == "__main__":
    main()
