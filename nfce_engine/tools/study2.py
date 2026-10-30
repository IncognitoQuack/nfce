"""Study engine v2: a few literature-specified intraday hypotheses, measured costs, one-shot final
(../evidence/study2_protocol.md). Built on tools/study.py (frame, grid matrices, walk, statistics).

  python tools/study2.py dev                       (2022-01 .. 2024-12: every hypothesis; the gate)
  python tools/study2.py final --i-accept-one-shot (2025-01 .. 2026-10-21: the hypotheses that passed the gate, once)
  python tools/study2.py report
  python tools/study2.py costcheck                 (order-book depth of the recorded minute quotes)

What changed against v1 (study_engine_result.md), and why:
- stocks "in play" are SELECTED across the market by relative opening volume (top 20), not every stock traded;
- thresholds and stops are in ATR units (each stock's own volatility), not fixed percentages;
- asymmetric exits from the literature (a tight stop, no target, hold to the close) where the source uses them;
- costs from the recorded order books (depth-walked impact, wider in the first 15 minutes), and the cheaper venue
  (cash-equity intraday: STT 0.025% vs 0.05% on futures since 1 Apr 2026);
- time-of-day effects (last half hour) and dated news (results days) are tested.
"""
from __future__ import annotations

import argparse
import json
import math
import pickle
import sqlite3
import sys
from datetime import date
from multiprocessing import get_context
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce import costs  # noqa: E402
from tools import study as s1  # noqa: E402

WORK = s1.DATA / "study_engine2"
PROTOCOL = s1.ROOT / "evidence" / "study2_protocol.md"
CSV = s1.ROOT / "evidence" / "study2_trades_summary.csv"
RESULTS_CAL = s1.DATA / "results_calendar.csv"
STAGES = {"dev": (date(2022, 1, 1), date(2024, 12, 31)), "final": (date(2025, 1, 1), date(2026, 10, 21))}
HYP = ("H1", "H2", "H3", "H4", "H5", "H6", "H7", "H8")
TITLES = {"H1": "Stocks-in-play ORB, paper stop 0.10 ATR (Zarattini-Barbon-Aziz)",
          "H2": "Stocks-in-play ORB, stop 0.50 ATR",
          "H3": "ORB on results days (dated news), stop 0.50 ATR",
          "H4": "Index: first half hour predicts the last (Gao-Han-Li-Zhou)",
          "H5": "Index: rest of day predicts the last half hour (Baltussen et al.)",
          "H6": "Stocks: end-of-day reversal, 10 long / 10 short",
          "H7": "v1 lead: fade a >= 2% gap down, low VIX, 2R exits",
          "H8": "Fade a gap >= 1 ATR, both sides, 2R exits"}
ALPHA = 0.05
MIN_FINAL = 100

# ---------------------------------------------------------------- costs (fixed from the 22/23 Oct order books)
EQ_NOTIONAL = 300_000                  # Rs per stock trade, cash-equity intraday
EQ_SLIP, EQ_SLIP_OPEN = 0.00037, 0.00050   # per side, depth-walked impact of a Rs 3 L market order (median 3.7 bp; open 4.7)
FUT_SLIP, FUT_SLIP_OPEN = 0.00049, 0.00063  # secondary venue: one ~Rs 7 L stock-futures lot
IDX_SLIP = 0.00010                     # index futures: measured NIFTY half-spread ~2.6 pts ~ 1 bp of price
EQ_STT, EQ_EXCH, EQ_STAMP = 0.00025, 0.0000322, 0.00003
OPEN_END = 9 * 60 + 30                 # an order in a bar starting before 09:30 pays the open slippage
ORB_OPEN_COST_FIX = True               # False = the registered 26 Oct run (ORB entries before 09:30 at the normal rate)


def equity_intraday_fees(entry, exit_, side: int, units):
    """Rupee fees of one cash-equity intraday round trip (Zerodha-type: STT 0.025% sell side, NSE 0.00322% each side,
    SEBI Rs 10/cr, stamp 0.003% buy side, brokerage min(Rs 20, 0.03%) per order, GST 18%)."""
    buy, sell = (entry, exit_) if side > 0 else (exit_, entry)
    bv, sv = np.asarray(buy) * units, np.asarray(sell) * units
    brk = np.minimum(20.0, 0.0003 * bv) + np.minimum(20.0, 0.0003 * sv)
    exch = EQ_EXCH * (bv + sv)
    sebi = costs.SEBI_FEE * (bv + sv)
    return EQ_STT * sv + exch + sebi + EQ_STAMP * bv + brk + costs.GST * (brk + exch + sebi)


def stock_cost(entry, exit_, side: int, open_entry, venue: str = "EQ"):
    """All-in round-trip cost in price points per share/unit, and the units traded."""
    entry, exit_ = np.asarray(entry, float), np.asarray(exit_, float)
    if venue == "EQ":
        units = np.maximum(1, np.round(EQ_NOTIONAL / entry))
        slip = np.where(open_entry, EQ_SLIP_OPEN, EQ_SLIP) * entry + EQ_SLIP * exit_
        return equity_intraday_fees(entry, exit_, side, units) / units + slip, units
    units = np.maximum(1, np.round(s1.NOTIONAL / entry))
    fees = np.asarray(costs.futures_cost_points(entry, exit_, side, costs.CURRENT, units, 1, 2, 0.0))
    return fees + np.where(open_entry, FUT_SLIP_OPEN, FUT_SLIP) * entry + FUT_SLIP * exit_, units


# ---------------------------------------------------------------- per-stock candidate trades
SLOT_1457, SLOT_ENTRY_EOD, SLOT_1518 = 113, 114, 120   # 3m slots: bar closing 14:57, opening 14:57, closing 15:18
LAST_ORB_ENTRY = 15 * 60                               # an ORB entry bar must start by 15:00


def rows_frame(day, sym, side, entry, px, R, cost, units, why, extra=None):
    gross = side * (px - entry)
    out = pd.DataFrame({"day": day, "sym": sym, "side": side, "entry": entry, "exit": px, "R": R,
                        "gross_r": gross / R, "net_r": (gross - cost) / R, "net_bp": (gross - cost) / entry * 1e4,
                        "net_inr": (gross - cost) * units, "reason": why})
    for k, v in (extra or {}).items():
        out[k] = v
    return out


def orb_candidates(d: pd.DataFrame, g: s1.Grid, sym: str, results_days: set) -> pd.DataFrame:
    """Every stock-day with a two-bar (6-minute) opening range: its relative opening volume and both ORB trades
    (stop 0.10 and 0.50 ATR). Selection (top 20 by rvol) happens across stocks later; rvol is known at 09:21."""
    days = np.unique(d["day"].to_numpy())
    S = g.O.shape[1]
    V = np.full((len(days), S), np.nan)
    V[g.row, g.slot] = d["volume"].to_numpy()
    orv = V[:, 0] + V[:, 1]
    base = pd.Series(orv).rolling(14, min_periods=14).mean().shift(1).to_numpy()
    rv = np.where(base > 0, orv / base, np.nan)
    first = d[d["first"]]
    atr = first["atr_prev"].to_numpy()
    pc = first["prev_close"].to_numpy()
    o0, c1 = g.O[:, 0], g.C[:, 1]
    hi, lo = np.fmax(g.H[:, 0], g.H[:, 1]), np.fmin(g.L[:, 0], g.L[:, 1])
    direction = np.sign(c1 - o0)
    ok = (np.isfinite(rv) & (rv >= 1) & np.isfinite(atr) & (atr > 0) & (atr / pc >= 0.01) & (direction != 0)
          & np.isfinite(hi) & np.isfinite(lo))
    last = (LAST_ORB_ENTRY - s1.OPEN) // 3
    cols = np.arange(S)
    el = np.flatnonzero(ok)                          # eligible at 09:21, triggered or not: the top-20 pool
    out = [pd.DataFrame({"day": days[el], "sym": sym, "hyp": "ELIG", "rvol": rv[el]})]
    pos_of = {(r, s): i for i, (r, s) in enumerate(zip(g.row, g.slot))}
    for side in (1, -1):
        rows = np.flatnonzero(ok & (direction == side))
        if not len(rows):
            continue
        lvl = hi[rows] if side > 0 else lo[rows]
        Hr, Lr = g.H[rows], g.L[rows]
        trig = ((Hr >= lvl[:, None]) if side > 0 else (Lr <= lvl[:, None])) & (cols >= 2) & (cols <= last)
        has = trig.any(1)
        rows, lvl, j0 = rows[has], lvl[has], trig[has].argmax(1)
        op = g.O[rows, j0]
        entry = np.where(np.isfinite(op), np.maximum(op, lvl) if side > 0 else np.minimum(op, lvl), lvl)
        pos = np.array([pos_of[(r, s)] for r, s in zip(rows, j0)])
        # Correction (26 Oct 2026, GS phase 0, review A finding 1): an entry bar starting before 09:30 pays the open
        # slippage. The registered run passed all-False here; ORB_OPEN_COST_FIX = False reproduces it.
        open_entry = (s1.OPEN + 3 * j0 < OPEN_END) if ORB_OPEN_COST_FIX else np.zeros(len(rows), bool)
        for k, name in ((0.10, "H1"), (0.50, "H2")):
            R = k * atr[rows]
            px, why = s1.walk(g, pos, side, entry - side * R, np.full(len(rows), side * np.inf))
            c, u = stock_cost(entry, px, side, open_entry)
            cf, uf = stock_cost(entry, px, side, open_entry, "FUT")
            f = rows_frame(days[rows], sym, side, entry, px, R, c, u, why,
                           {"hyp": name, "rvol": rv[rows], "results": [pd.Timestamp(dd) in results_days for dd in days[rows]],
                            "net_r_fut": (side * (px - entry) - cf) / R, "open_entry": open_entry})
            out.append(f)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def eod_candidates(d: pd.DataFrame, g: s1.Grid, sym: str) -> pd.DataFrame:
    """Return from the prior close to 14:57, and both sides of the 14:57 -> 15:18 trade (H6 ranks across stocks)."""
    days = np.unique(d["day"].to_numpy())
    first = d[d["first"]]
    pc, atr = first["prev_close"].to_numpy(), first["atr_prev"].to_numpy()
    r = g.C[:, SLOT_1457] / pc - 1
    entry, px = g.O[:, SLOT_ENTRY_EOD], g.C[:, SLOT_1518]
    ok = np.isfinite(r) & np.isfinite(entry) & np.isfinite(px) & np.isfinite(atr) & (atr > 0)
    out = []
    for side in (1, -1):
        rows = np.flatnonzero(ok)
        R = 0.25 * atr[rows]
        c, u = stock_cost(entry[rows], px[rows], side, np.zeros(len(rows), bool))
        out.append(rows_frame(days[rows], sym, side, entry[rows], px[rows], R, c, u, "eod",
                              {"hyp": "H6", "ret": r[rows]}))
    return pd.concat(out, ignore_index=True)


def gap_trades(d: pd.DataFrame, g: s1.Grid, sym: str, regime: pd.Series) -> pd.DataFrame:
    """H7: v1's GAP_FADE|L|K2|ALL|VIXLO|STK|0.02 exactly (entries from study.py); H8: the gap measured in ATR."""
    gap = (d["day_open"] / d["prev_close"] - 1).to_numpy()
    gap_atr = ((d["day_open"] - d["prev_close"]) / d["atr_prev"]).to_numpy()
    f = d["first"].to_numpy()
    R0 = s1.R_ATR * d["atr_prev"].to_numpy()
    reg = regime.reindex(pd.DatetimeIndex(d["day"].to_numpy())).to_numpy()
    opn = d["open"].to_numpy()
    out = []
    for name, side, sig in (("H7", 1, f & (gap <= -0.02)), ("H8", 1, f & (gap_atr <= -1.0)),
                            ("H8", -1, f & (gap_atr >= 1.0))):
        pos = s1.entries(d, sig, 3, s1.WINDOWS["ALL"])
        pos = pos[np.isfinite(R0[pos]) & (R0[pos] > 0)]
        if name == "H7":
            pos = pos[reg[pos] == "VIXLO"]
        if not len(pos):
            continue
        entry, R = opn[pos], 2 * R0[pos]
        px, why = s1.walk(g, pos, side, entry - side * R, entry + side * R)
        c, u = stock_cost(entry, px, side, d["hm"].to_numpy()[pos] < OPEN_END)
        cf, _ = stock_cost(entry, px, side, d["hm"].to_numpy()[pos] < OPEN_END, "FUT")
        out.append(rows_frame(d["day"].to_numpy()[pos], sym, side, entry, px, R, c, u, why,
                              {"hyp": name, "net_r_fut": (side * (px - entry) - cf) / R}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def results_days_of(sym: str, cal: pd.DataFrame, sessions: np.ndarray) -> set:
    """Sessions on the board-meeting (results) date or the session after it."""
    dates = pd.DatetimeIndex(cal.loc[(cal["symbol"] == sym) & (cal["results"] == 1), "date"])
    if not len(dates):
        return set()
    ses = pd.DatetimeIndex(sessions)
    i = ses.searchsorted(dates)                      # the meeting date, or the next session if it was a holiday
    keep = set()
    for k in i:
        for j in (k, k + 1):
            if 0 <= j < len(ses):
                keep.add(pd.Timestamp(ses[j]))
    return keep


def _stock_job(job):
    files, regime, cal = job
    parts = []
    for f in files:
        sym = f.stem[:-3]
        d = s1.frame(s1.load_bars(f), 3)
        if d.empty:
            continue
        g = s1.make_grid(d, 3)
        rd = results_days_of(sym, cal, np.unique(d["day"].to_numpy()))
        for p in (orb_candidates(d, g, sym, rd), eod_candidates(d, g, sym), gap_trades(d, g, sym, regime)):
            if len(p):
                parts.append(p)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# ---------------------------------------------------------------- index (H4, H5)
IDX_SLOTS = {"r1": 5, "r_rest": 68, "entry": 69, "exit": 74}   # 5m: 09:45 close, 15:00 close-before, 15:00 open, 15:30 close


def index_trades(d: pd.DataFrame, sym: str, lot: tuple) -> pd.DataFrame:
    g = s1.make_grid(d, 5)
    days = np.unique(d["day"].to_numpy())
    first = d[d["first"]]
    pc, atr = first["prev_close"].to_numpy(), first["atr_prev"].to_numpy()
    entry, px = g.O[:, IDX_SLOTS["entry"]], g.C[:, IDX_SLOTS["exit"]]
    out = []
    for name, sig in (("H4", g.C[:, IDX_SLOTS["r1"]] / pc - 1), ("H5", g.C[:, IDX_SLOTS["r_rest"]] / pc - 1)):
        ok = np.isfinite(sig) & (sig != 0) & np.isfinite(entry) & np.isfinite(px) & np.isfinite(atr)
        for side in (1, -1):
            rows = np.flatnonzero(ok & (np.sign(sig) == side))
            R = 0.25 * atr[rows]
            c = np.asarray(costs.futures_cost_points(entry[rows], px[rows], side, costs.CURRENT, lot[0], 1, 2,
                                                     IDX_SLIP * entry[rows]))
            c04 = np.asarray(costs.futures_cost_points(entry[rows], px[rows], side, costs.CURRENT, lot[0], 1, 2, 4 * lot[1]))
            out.append(rows_frame(days[rows], sym, side, entry[rows], px[rows], R, c, lot[0], "eod",
                                  {"hyp": name, "net_r_fut": (side * (px[rows] - entry[rows]) - c04) / R}))
    return pd.concat(out, ignore_index=True)


# ---------------------------------------------------------------- selection into the hypotheses' trade lists
def select(c: pd.DataFrame) -> dict[str, pd.DataFrame]:
    out = {}
    for col in ("rvol", "results"):
        if col not in c:
            c = c.assign(**{col: np.nan if col == "rvol" else False})
    orb = c[c["hyp"].isin(["H1", "H2"])]
    el = c[c["hyp"] == "ELIG"].sort_values(["day", "rvol", "sym"], ascending=[True, False, True]).groupby("day").head(20)
    keys = pd.MultiIndex.from_frame(el[["day", "sym"]])
    for h in ("H1", "H2"):
        x = orb[orb["hyp"] == h]
        out[h] = x[pd.MultiIndex.from_frame(x[["day", "sym"]]).isin(keys)]
    out["H3"] = orb[(orb["hyp"] == "H2") & orb["results"].fillna(False).astype(bool)].assign(hyp="H3")
    e = c[c["hyp"] == "H6"]
    if len(e):
        lng = e[e["side"] > 0].sort_values(["day", "ret", "sym"]).groupby("day").head(10)
        sht = e[e["side"] < 0].sort_values(["day", "ret", "sym"], ascending=[True, False, True]).groupby("day").head(10)
        out["H6"] = pd.concat([lng, sht], ignore_index=True)
    for h in ("H4", "H5", "H7", "H8"):
        out[h] = c[c["hyp"] == h]
    return out


def run_stage(stage: str, workers: int, hyps: tuple = HYP) -> dict:
    a, b = STAGES[stage]
    vix = s1.load_bars(s1.HIST3M / "INDIAVIX_3m.pkl")
    regime = s1.vix_regime(vix)
    cal = pd.read_csv(RESULTS_CAL, parse_dates=["date"])
    files = [f for f in sorted(s1.HIST3M.glob("*_3m.pkl")) if f.stem != "INDIAVIX_3m"]
    parts = []
    if set(hyps) - {"H4", "H5"}:
        jobs = [(files[i::workers], regime, cal) for i in range(workers)]
        with get_context("spawn").Pool(workers) as pool:
            parts += pool.map(_stock_job, jobs)
    if set(hyps) & {"H4", "H5"}:
        for ix, lot in s1.INDEX.items():
            parts.append(index_trades(s1.frame(s1.load_bars(s1.HIST5M / f"{ix}_5m.pkl"), 5), ix, lot))
    c = pd.concat([p for p in parts if len(p)], ignore_index=True)
    c["day"] = pd.to_datetime(c["day"])
    c = c[(c["day"] >= pd.Timestamp(a)) & (c["day"] <= pd.Timestamp(b))]      # nothing outside the stage is kept
    trades = {h: t for h, t in select(c).items() if h in hyps}
    vday = pd.DatetimeIndex(s1.frame(vix, 3)["day"].unique())
    days = vday[(vday >= pd.Timestamp(a)) & (vday <= pd.Timestamp(b))]
    return {"stage": stage, "trades": trades, "days": days, "protocol_sha": s1.hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()}


# ---------------------------------------------------------------- statistics
def acc_of(t: pd.DataFrame, days: pd.DatetimeIndex, col: str = "net_r") -> np.ndarray:
    """Per-day sums in study.FIELDS layout, so study.rule_stats / block_ci / day_series apply unchanged."""
    a = np.zeros((len(days), len(s1.FIELDS)))
    if not len(t):
        return a
    di = days.get_indexer(pd.DatetimeIndex(t["day"]))
    m = di >= 0
    t, di = t[m], di[m]
    vals = np.stack([np.ones(len(t)), t[col], t["gross_r"], (t[col] > 0).astype(float),
                     t["net_inr"].clip(lower=0), (-t["net_inr"]).clip(lower=0),
                     (t["reason"].astype(str).isin(["0", "stop"])).astype(float), np.zeros(len(t)),
                     (t["gross_r"] - t["net_r"])], axis=1)
    np.add.at(a, di, vals)
    return a


def summarize(res: dict) -> dict:
    out = {}
    for h, t in res["trades"].items():
        a = acc_of(t, res["days"])
        s = s1.rule_stats(a, res["days"])
        if s["n"]:
            s["ci"] = s1.block_ci(a)
            s["net_bp"] = float(t["net_bp"].mean())
            s["gross_bp"] = float((t["side"] * (t["exit"] - t["entry"]) / t["entry"] * 1e4).mean())
            s["cost_bp"] = s["gross_bp"] - s["net_bp"]
            if "net_r_fut" in t and t["net_r_fut"].notna().any():
                s["net_r_alt"] = float(t["net_r_fut"].mean())
            s["long_net_r"] = float(t.loc[t["side"] > 0, "net_r"].mean()) if (t["side"] > 0).any() else math.nan
            s["short_net_r"] = float(t.loc[t["side"] < 0, "net_r"].mean()) if (t["side"] < 0).any() else math.nan
        out[h] = s
    return out


def gate(s: dict) -> bool:
    return bool(s.get("n")) and s["net_r"] > 0


def judge_final(fin: dict) -> dict:
    sm = summarize(fin)
    hs = [h for h in sm if sm[h].get("n")]
    p = np.array([sm[h]["p_day"] for h in hs])
    adj = s1.holm_adjust(p, len(HYP)) if len(p) else p          # family = all 8 registered hypotheses
    for h, a in zip(hs, adj):
        s = sm[h]
        s["holm"] = float(a)
        s["pass"] = bool(s["n"] >= MIN_FINAL and s["net_r"] > 0 and a < ALPHA and s["ci"][0] > 0)
    X = np.stack([s1.day_series(acc_of(fin["trades"][h], fin["days"])) for h in hs], 1) if hs else np.zeros((0, 0))
    return {"stats": sm, "spa": s1.spa(X) if hs else None}


# ---------------------------------------------------------------- order-book cost check
def depth_cost(levels: list, notional: float, mid: float) -> float:
    """Average distance from mid (fraction) of a marketable order of `notional` rupees walking the visible book.
    Anything beyond the visible levels is charged 1.5x the last level's distance plus 2 bp (conservative)."""
    left, cost, last = notional, 0.0, None
    for lv in levels:
        p, q = float(lv["price"]), float(lv["quantity"])
        take = min(left, p * q)
        cost += take * abs(p - mid) / mid
        left -= take
        last = p
        if left <= 0:
            break
    if left > 0:
        if last is None:
            return math.nan
        cost += left * (1.5 * abs(last - mid) / mid + 0.0002)
    return cost / notional


def cost_check(dbs: list[Path], every: int = 7) -> dict:
    rec = []
    for db in dbs:
        if not db.exists():
            continue
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        q = pd.read_sql_query("select ts, symbol, bid, ask, depth from q where bid > 0 and ask >= bid and depth != '' "
                              "and (symbol like 'NSE_EQ:%' or symbol like 'NSE_FO:%FUT')", con)
        con.close()
        for r in q.iloc[::every].itertuples():
            dp, mid = json.loads(r.depth), (r.bid + r.ask) / 2
            venue = "EQ" if r.symbol.startswith("NSE_EQ") else "FUT"
            und = r.symbol.split(":")[1]
            if venue == "FUT":
                und = pd.Series([und]).str.replace(r"\d{2}[A-Z]{3}FUT$", "", regex=True)[0]
            x = {"venue": venue, "und": und, "open": r.ts[11:16] < "09:30", "half": (r.ask - r.bid) / 2 / mid}
            for n in (1e5, 3e5, 7e5):
                x[f"buy_{int(n / 1e5)}L"] = depth_cost(dp.get("sell", []), n, mid)
                x[f"sell_{int(n / 1e5)}L"] = depth_cost(dp.get("buy", []), n, mid)
            rec.append(x)
    if not rec:
        return {"quotes": 0}
    x = pd.DataFrame(rec)
    out = {"quotes": int(len(x))}
    for v in ("EQ", "FUT"):
        y = x[(x["venue"] == v) & ~x["und"].isin(["NIFTY", "BANKNIFTY", "SENSEX"])]
        per = y.groupby("und").median(numeric_only=True)
        op = y[y["open"]].groupby("und").median(numeric_only=True)
        out[v] = {"stocks": int(len(per)), "half": float(per["half"].median()),
                  **{k: float(per[k].median()) for k in per.columns if k.startswith(("buy", "sell"))},
                  **{f"open_{k}": float(op[k].median()) for k in op.columns if k.startswith("buy")}}
    n = x[(x["venue"] == "FUT") & (x["und"] == "NIFTY")]
    if len(n):
        out["NIFTY_half"] = float(n["half"].median())
    return out


# ---------------------------------------------------------------- report
def _f(x, f="+.3f"):
    return "–" if x is None or (isinstance(x, float) and not math.isfinite(x)) else format(x, f)


def table(sm: dict, final: bool = False) -> str:
    L = ["| Hyp | What | n | Days | Win % | Gross R | Net R | Net bp | Cost bp | Long / short net R | 95% day-block | p(day) | Alt cost net R |"
         + (" Holm | Pass |" if final else " Gate |"),
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|" + ("---|---|" if final else "---|")]
    for h in HYP:
        s = sm.get(h)
        if not s:
            continue
        if not s.get("n"):
            L.append(f"| {h} | {TITLES[h]} | 0 | | | | | | | | | | |" + (" | FAIL |" if final else " FAIL |"))
            continue
        tail = (f" {s['holm']:.3f} | {'PASS' if s['pass'] else 'FAIL'} |" if final else
                f" {'pass' if gate(s) else 'FAIL'} |")
        L.append(f"| {h} | {TITLES[h]} | {s['n']:,} | {s['days']} | {s['win'] * 100:.1f} | {_f(s['gross_r'])} | "
                 f"**{_f(s['net_r'])}** | {_f(s['net_bp'], '+.1f')} | {_f(s['cost_bp'], '.1f')} | "
                 f"{_f(s['long_net_r'])} / {_f(s['short_net_r'])} | {_f(s['ci'][0])}..{_f(s['ci'][1])} | "
                 f"{s['p_day']:.4f} | {_f(s.get('net_r_alt'))} |" + tail)
    return "\n".join(L)


def years_table(res: dict) -> str:
    L = ["| Hyp | " + " | ".join(str(y) for y in sorted(set(res["days"].year))) + " |",
         "|---|" + "---|" * len(set(res["days"].year))]
    for h in HYP:
        t = res["trades"].get(h)
        if t is None or not len(t):
            continue
        yr = t.groupby(t["day"].dt.year)["net_r"].agg(["mean", "size"])
        L.append(f"| {h} | " + " | ".join(f"{_f(yr.loc[y, 'mean'])} ({int(yr.loc[y, 'size']):,})" if y in yr.index else "–"
                                         for y in sorted(set(res["days"].year))) + " |")
    return "\n".join(L)


def _load(stage):
    f = WORK / f"{stage}.pkl"
    return pickle.loads(f.read_bytes()) if f.exists() else None


def _save(stage, res):
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / f"{stage}.pkl").write_bytes(pickle.dumps(res))


def report() -> str:
    dev, fin = _load("dev"), _load("final")
    if dev is None:
        sys.exit("run dev first")
    sd = summarize(dev)
    L = ["## Development 2022-01 .. 2024-12 (the gate: net R > 0)", table(sd), "", "Net R per trade by year (trades):",
         years_table(dev)]
    Xd = np.stack([s1.day_series(acc_of(dev["trades"][h], dev["days"])) for h in HYP if h in dev["trades"]], 1)
    pb = s1.pbo_cscv(Xd)
    L.append(f"\nPBO (CSCV, 16 blocks) over the 8 hypotheses on development: **{pb['pbo']:.2f}** "
             f"(in-sample best per-day Sharpe {pb['is_best_sr']:+.3f}, out of sample {pb['oos_sr_of_is_best']:+.3f}).")
    rows = [{"stage": "dev", "hyp": h, **{k: v for k, v in s.items() if k not in ("years", "ci")}} for h, s in sd.items()]
    if fin:
        jf = judge_final(fin)
        L += ["", "## Final 2025-01 .. 2026-10-21 (one shot)", table(jf["stats"], True), "", "Net R per trade by year (trades):",
              years_table(fin)]
        if jf["spa"]:
            L.append(f"\nSPA over the final hypotheses: p = {jf['spa']['spa_p']:.3f}; reality check p = {jf['spa']['rc_p']:.3f}.")
        rows += [{"stage": "final", "hyp": h, **{k: v for k, v in s.items() if k not in ("years", "ci")}}
                 for h, s in jf["stats"].items()]
    pd.DataFrame(rows).to_csv(CSV, index=False)
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["dev", "final", "report", "costcheck"])
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--i-accept-one-shot", action="store_true")
    x = ap.parse_args()
    if x.cmd in STAGES and not PROTOCOL.exists():
        sys.exit(f"register the protocol first: {PROTOCOL}")
    if x.cmd == "dev":
        res = run_stage("dev", x.workers)
    elif x.cmd == "final":
        if not x.i_accept_one_shot:
            sys.exit("the final stage is one-shot: pass --i-accept-one-shot")
        if _load("final") is not None:
            sys.exit("the final stage has already been run once")
        dev = _load("dev")
        sha = s1.hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()
        if dev is None or dev["protocol_sha"] != sha:
            sys.exit("dev missing, or the protocol changed since dev")
        go = tuple(h for h, s in summarize(dev).items() if gate(s))
        print("passed the gate:", go)
        if not go:
            sys.exit("nothing passed the gate: the final is not run")
        res = run_stage("final", x.workers, go)
    elif x.cmd == "costcheck":
        cc = cost_check(s1.QUOTES)
        _save("costcheck", cc)
        print(json.dumps(cc, indent=1))
        return
    else:
        txt = report()
        (WORK / "result_tables.md").write_text(txt)
        print(txt)
        return
    _save(x.cmd, res)
    print(f"{x.cmd}: " + ", ".join(f"{h} {len(t):,}" for h, t in res["trades"].items()))


if __name__ == "__main__":
    main()
