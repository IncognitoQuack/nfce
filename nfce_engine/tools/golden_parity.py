"""Bar-by-bar parity: the Python engine vs TradingView, from the strategy's golden export (Pine Logs CSV).

  python tools/golden_parity.py pine-logs-NFCE-S.csv [--warmup-sessions 15]

In TradingView: strategy input "Golden export: log the last N bars" = 5000, then Pine Logs → Download logs.
Each "G|" line carries the bar's inputs and TradingView's own indicator values (nfce_strategy.pine, golden export).

The engine is fed the SAME inputs the Pine script saw:
- bars: OHLCV and the futures OI;
- VIX: India VIX closes;
- heavyweights: each stock's % change from its day open, rebuilt as open = 100, close = 100 x (1 + change / 100).

It then reports, after a warm-up (the export starts mid-history, so recursive indicators need time to converge):
  1. indicator agreement per field (share of bars within tolerance, worst difference);
  2. signals: TradingView signal bars vs engine signal bars (precision / recall);
  3. position path agreement, from the first bar after warm-up where both are flat;
  4. the trade ledger: TradingView's own trade list (NFCE|V|0 line) vs the engine, field by field (tick tolerance).
Verdict PARITY only if indicators, signals, the whole position path AND the ledger agree (exit code 0); anything else
is DIFFERENCES (exit code 1).
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce import Params, prepare, run  # noqa: E402

FIELDS = ["time", "open", "high", "low", "close", "volume", "oi", "vix", "vix_chg", "c1", "c2", "c3", "c4", "c5",
          "pdh", "pdl", "pdc", "htf_c", "htf_e", "atr", "e9", "e21", "e50", "adx", "dip", "dim", "st_dir", "rvol",
          "volz", "chop", "cvd_slope", "vw", "sL", "sS", "sig", "pos", "is_exp"]
RECONSTRUCTED = {"vix_chg": "the export has VIX values on CHART bars; VIX's own bars (which close[5] counts) are "
                             "inferred by dropping forward-filled rows, which is ambiguous when VIX really repeats"}
COMPARE = ["pdh", "pdl", "pdc", "htf_c", "htf_e", "atr", "e9", "e21", "e50", "adx", "dip", "dim", "st_dir", "rvol",
           "volz", "chop", "cvd_slope", "vw", "vix_chg", "is_exp"]


def parse(path: Path) -> tuple[pd.DataFrame, dict, str]:
    rows, meta, v0 = [], {}, ""
    with open(path, newline="") as f:
        for rec in csv.reader(f):
            msg = rec[-1] if rec else ""
            if msg.startswith("G|"):
                p = msg.split("|")[1:]
                if len(p) != len(FIELDS):
                    raise ValueError(f"golden line has {len(p)} fields, expected {len(FIELDS)}")
                rows.append(p)
            elif msg.startswith("NFCE|META|"):
                p = msg.split("|")
                meta = {"sym": p[2], "tf": p[3], **dict(kv.split("=", 1) for kv in p[4:])}
            elif msg.startswith("NFCE|V|0|"):
                v0 = msg
    if not rows:
        raise ValueError("no golden lines: set the strategy's golden export > 0 and download the logs again")
    d = pd.DataFrame(rows, columns=FIELDS)
    for c in FIELDS:
        if c != "sig":
            d[c] = pd.to_numeric(d[c].replace("", np.nan))
    d.index = pd.to_datetime(d.pop("time"), unit="ms", utc=True).dt.tz_convert("Asia/Kolkata")
    d = d[~d.index.duplicated(keep="last")].sort_index()
    return d, meta, v0


def engine_inputs(g: pd.DataFrame):
    bars = g[["open", "high", "low", "close", "volume", "oi"]].copy()
    # VIX's OWN bars: request.security forward-fills VIX onto chart bars it doesn't have (e.g. the futures' 15:30
    # and 15:35 bars), so a row identical to the previous one in both value and 5-bar change is a fill, not a bar.
    vv = g[["vix", "vix_chg"]]
    filled = (vv["vix"] == vv["vix"].shift()) & (vv["vix_chg"] == vv["vix_chg"].shift())
    vix = pd.DataFrame({"close": g["vix"][~filled]}).dropna()
    hw = []
    for k in range(1, 6):
        ch = g[f"c{k}"]
        if ch.notna().any():
            hw.append(pd.DataFrame({"open": 100.0, "close": 100.0 * (1 + ch / 100.0)}, index=g.index).dropna())
    # daily bars: each session's first bar carries the PREVIOUS session's daily high/low/close
    sessions = sorted(set(g.index.normalize()))
    first = g.groupby(g.index.normalize()).first()
    rows = []
    for k, d in enumerate(sessions):
        prev = sessions[k - 1] if k else d - pd.Timedelta(days=1)
        r = first.loc[d]
        if not (np.isnan(r.pdh) or np.isnan(r.pdl) or np.isnan(r.pdc)):
            rows.append((prev, r.pdh, r.pdl, r.pdc))
    daily = pd.DataFrame(rows, columns=["date", "high", "low", "close"]).set_index("date")
    return bars, vix, hw, daily


def close_enough(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    both_nan = np.isnan(a) & np.isnan(b)
    with np.errstate(invalid="ignore"):
        ok = np.abs(a - b) <= 1e-4 * np.maximum(1.0, np.abs(b))
    return both_nan | ok


def main(path: Path, warmup_sessions: int) -> int:
    g, meta, v0 = parse(path)
    tf = int(meta.get("tf", "5"))
    instr = meta.get("instr", "NIFTY")
    p = Params(instr=instr)
    bars, vix, hw, daily = engine_inputs(g)
    pr = prepare(bars, tf, p, vix=vix if len(vix) else None, hw=hw, daily=daily)
    trace = {i: {} for i in range(len(g))}
    trades = run(pr, p, trace=trace)
    days = g.index.normalize()
    first_day = sorted(set(days))[min(warmup_sessions, len(set(days)) - 1)]
    w = np.asarray(days >= first_day)
    print(f"{meta.get('sym')} {tf}m, instr {instr}: {len(g)} golden bars {g.index[0]:%Y-%m-%d} .. {g.index[-1]:%Y-%m-%d};"
          f" compared from {first_day:%Y-%m-%d} ({int(w.sum())} bars, after {warmup_sessions} warm-up sessions)")

    # 1. indicators
    eng = {"pdh": pr.cols["pdh"], "pdl": pr.cols["pdl"], "pdc": pr.cols["pdc"], "htf_c": pr.cols["htf_c"],
           "htf_e": pr.cols["htf_e"], "atr": pr.cols["atr"], "e9": pr.cols["e9"], "e21": pr.cols["e21"],
           "e50": pr.cols["e50"], "adx": pr.cols["adx"], "dip": pr.cols["dip"], "dim": pr.cols["dim"],
           "st_dir": pr.cols["st_dir"], "rvol": pr.cols["rvol"], "volz": pr.cols["volz"], "chop": pr.cols["chop"],
           "cvd_slope": pr.cols["cvd_slope"], "vw": pr.cols["vw"], "vix_chg": pr.cols["vix_chg"],
           "is_exp": pr.cols["is_exp"].astype(float)}
    print("\n1. Indicators (share of bars equal within 1e-4 relative; worst absolute difference and when)")
    bad_fields = []
    for f in COMPARE:
        a, b = np.asarray(eng[f], float)[w], g[f].to_numpy(float)[w]
        ok = close_enough(a, b)
        share = ok.mean()
        diff = np.where(np.isnan(a) | np.isnan(b), np.where(np.isnan(a) == np.isnan(b), 0.0, np.inf), np.abs(a - b))
        j = int(np.argmax(diff))
        when = g.index[w][j]
        print(f"   {f:10s} {share * 100:6.2f}%   worst {diff[j]:.6g} at {when:%Y-%m-%d %H:%M} (engine {a[j]:.6g}, TV {b[j]:.6g})")
        if share < 0.999 and f not in RECONSTRUCTED:
            bad_fields.append(f)
        elif share < 0.999:
            print(f"              ^ input reconstruction limit, not an engine difference: {RECONSTRUCTED[f]}")

    # 2. signals
    idx_of = {t: i for i, t in enumerate(g.index)}
    bar = pd.Timedelta(minutes=tf)
    e_sig = {idx_of[t.entry_time - bar]: t.side for t in trades if (t.entry_time - bar) in idx_of}
    tv_sig = {i: s for i, s in enumerate(g["sig"].fillna("")) if s in ("L", "S")}
    wi = set(np.flatnonzero(w))
    es = {k: v for k, v in e_sig.items() if k in wi}
    ts = {k: v for k, v in tv_sig.items() if k in wi}
    both = {k for k in es if ts.get(k) == es[k]}
    print(f"\n2. Signals after warm-up: TradingView {len(ts)}, engine {len(es)}, identical {len(both)}"
          f" (precision {len(both) / max(len(es), 1):.2f}, recall {len(both) / max(len(ts), 1):.2f})")
    for k in sorted(set(es) ^ set(ts) | {k for k in es if k in ts and ts[k] != es[k]})[:12]:
        t = trace.get(k, {})
        print(f"   {g.index[k]:%Y-%m-%d %H:%M}  TV {ts.get(k, '-')}  engine {es.get(k, '-')}  "
              f"engine gate: {t.get('blocked', '')} sL {t.get('sL', '')} sS {t.get('sS', '')} | TV sL {g['sL'].iloc[k]:.1f} sS {g['sS'].iloc[k]:.1f}")

    # 3. position path, from the first common flat bar after warm-up
    epos = np.zeros(len(g))
    for t in trades:
        s = 1 if t.side == "L" else -1
        i0 = idx_of.get(t.entry_time - bar)
        i1 = idx_of.get(t.exit_time - bar) if t.exit_time is not None else None
        if i0 is not None:
            epos[i0:(i1 if i1 is not None else len(g))] = s
    tpos = g["pos"].to_numpy(float)
    start = next((i for i in np.flatnonzero(w) if epos[i] == 0 and tpos[i] == 0), None)
    first_bad = None
    if start is not None:
        agree = (epos[start:] == tpos[start:]).mean()
        first_bad = next((i for i in range(start, len(g)) if epos[i] != tpos[i]), None)
        print(f"\n3. Position path from {g.index[start]:%Y-%m-%d %H:%M}: {agree * 100:.2f}% of bars agree"
              + (f"; first difference {g.index[first_bad]:%Y-%m-%d %H:%M} (engine {epos[first_bad]:+.0f}, TV {tpos[first_bad]:+.0f})"
                 if first_bad is not None else "; no difference"))

    # 4. trade ledger: every TradingView trade (the strategy's own v0 ledger in the same export) against the engine
    tick = float(meta.get("mintick", 0.05) or 0.05)
    tv_trades = ledger(v0)
    print("\n4. Trade ledger (TradingView v0 ledger vs engine): entry / R / gross pnl / exit")
    eng_by_entry = {t.entry_time: t for t in trades}
    mism, n_cmp = [], 0
    if tv_trades is None:
        print("   no TradingView ledger line (NFCE|V|0) in this export: trade fields NOT reconciled")
    else:
        for tv in tv_trades:
            if tv["entry_time"] < g.index[start] if start is not None else True:
                continue
            n_cmp += 1
            e = eng_by_entry.get(tv["entry_time"])
            if e is None:
                mism.append(f"{tv['entry_time']:%m-%d %H:%M} TV trade has no engine trade")
                continue
            bad = [f for f, a, b, tol in (("entry", e.entry, tv["entry"], tick), ("R", e.R, tv["R"], tick),
                                          ("pnl", e.pnl, tv["pnl"], 2 * tick)) if abs(a - b) > tol + 1e-9]
            if e.exit != tv["exit"]:
                bad.append(f"exit {e.exit} vs {tv['exit']}")
            if e.side != tv["side"]:
                bad.append("side")
            if bad:
                mism.append(f"{tv['entry_time']:%m-%d %H:%M} {', '.join(bad)} (engine entry {e.entry:.2f} R {e.R:.2f} "
                            f"pnl {e.pnl:+.2f}; TV {tv['entry']:.2f} / {tv['R']:.2f} / {tv['pnl']:+.2f})")
        extra = [t for t in trades if start is not None and t.entry_time >= g.index[start]
                 and t.entry_time not in {x["entry_time"] for x in tv_trades}]
        mism += [f"{t.entry_time:%m-%d %H:%M} engine trade not in the TV ledger" for t in extra]
        print(f"   {n_cmp} TradingView trades compared, {len(mism)} differences")
        for m in mism[:12]:
            print("   " + m)
    verdict, problems = judge(bad_fields, len(both) == len(es) == len(ts), start is not None, first_bad is None,
                              tv_trades is not None, len(mism))
    print(f"\nVerdict: {verdict}" + (f" ({'; '.join(problems)})" if problems else ""))
    return 0 if verdict == "PARITY" else 1


def judge(bad_fields: list[str], signals_equal: bool, has_start: bool, path_equal: bool, has_ledger: bool,
          ledger_diffs: int) -> tuple[str, list[str]]:
    """FIX (review round 3, H11): PARITY needs EVERYTHING to agree, including the whole position path and the
    TradingView trade ledger. Without a ledger the best possible verdict says so (and the exit code is 1)."""
    problems = []
    if bad_fields:
        problems.append("indicator fields below 99.9%: " + ", ".join(bad_fields))
    if not signals_equal:
        problems.append("signals differ")
    if not has_start:
        problems.append("no common flat bar after warm-up")
    elif not path_equal:
        problems.append("position path differs")
    if has_ledger and ledger_diffs:
        problems.append(f"{ledger_diffs} trade-ledger differences")
    if problems:
        return "DIFFERENCES", problems
    return ("PARITY", []) if has_ledger else ("PARITY (no TV ledger to reconcile)", [])


def ledger(v0: str) -> list[dict] | None:
    """The strategy's own trade list from its NFCE|V|0 log line (format: see tools/tv_evidence.py)."""
    if not v0:
        return None
    p = v0.split("|")
    out = []
    for t in filter(None, p[9].split(";")):
        f = t.split(",")
        out.append({"entry_time": pd.Timestamp(int(f[0]) * 60, unit="s", tz="UTC").tz_convert("Asia/Kolkata"),
                    "side": f[1], "entry": float(f[4]), "R": float(f[5]), "pnl": float(f[6]), "exit": f[7]})
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", type=Path)
    ap.add_argument("--warmup-sessions", type=int, default=15)
    a = ap.parse_args()
    sys.exit(main(a.logs, a.warmup_sessions))
