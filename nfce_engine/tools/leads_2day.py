"""The two leads of 21-22 Oct (../evidence/leads_2day_protocol.md).

  python tools/leads_2day.py h1 <hist3m folder> --stage train [--original <old hist3m folder>] [--cache rows.pkl]
  python tools/leads_2day.py h2 <5m data folder> --stage train
  python tools/leads_2day.py h3 <hist3m folder> --stage train --nifty <NIFTY_5m.pkl> [--cache rows.pkl]
    (h3 = H3 and H4 of ../evidence/best_practice_tests_protocol.md)
"""
from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import scanner_research as sr  # noqa: E402
from tools import stock3m_research as s3  # noqa: E402
from tools.research_run import SPLITS as SCAN_SPLITS  # noqa: E402


def passes(s: dict) -> bool:
    return bool(s.get("n")) and s["net_r"] > 0 and s["ci"][0] > 0


def line(name: str, rows: list[dict]) -> dict:
    s = sr.stats(rows)
    if not s["n"]:
        print(f"{name}: n=0")
        return s
    print(f"{name}: n={s['n']} days {s['days']} win {s['win'] * 100:.1f}% gross {s['gross_r']:+.3f} net {s['net_r']:+.3f}R "
          f"CI {s['ci'][0]:+.3f}..{s['ci'][1]:+.3f} PF {s['pf']:.2f} Rs {s['net_inr']:+,.0f}"
          f"{'  PASS' if passes(s) else ''}", flush=True)
    return s


def stock_rows(folder: Path, cache: Path | None) -> list[dict]:
    if cache and cache.exists():
        return pickle.loads(cache.read_bytes())
    rows = s3.trades(folder)
    if cache:
        cache.write_bytes(pickle.dumps(rows))
    return rows


def h1(folder: Path, stage: str, original: Path | None, cache: Path | None = None) -> None:
    a, b = s3.SPLITS[stage]
    rows = [r for r in stock_rows(folder, cache) if a <= r["day"] <= b]
    old = {p.stem[:-3] for p in original.glob("*_3m.pkl")} if original else set()
    print(f"stocks: {len({r['sym'] for r in rows})} ({len(old)} original)")
    line("all day, all stocks      ", rows)
    s = line("H1 before 12:00, all     ", [r for r in rows if r["time"].hour < 12])
    line("12:00 and later, all     ", [r for r in rows if r["time"].hour >= 12])
    if old:
        new = [r for r in rows if r["sym"] not in old]
        line("all day, new stocks only ", new)
        line("H1 before 12:00, new only", [r for r in new if r["time"].hour < 12])
    print("H1:", "PASS" if passes(s) else "FAIL")


def h2(data: Path, stage: str) -> None:
    pn, bars = sr.panel(data)
    a, b = SCAN_SPLITS[stage]
    pooled = []
    for t in sr.TIMES:
        rows = [x for x in sr.trades(pn, bars, f"G1 {t}") if a <= x["day"] <= b]
        line(f"G1 {t} both   ", rows)
        line(f"G1 {t} BUY    ", [x for x in rows if x["side"] > 0])
        sell = [x for x in rows if x["side"] < 0]
        line(f"G1 {t} SELL   ", sell)
        pooled += sell
    s = line("H2 SELL pooled  ", pooled)
    print("H2:", "PASS" if passes(s) else "FAIL")


def nifty_state(nifty: pd.DataFrame, rows: list[dict]) -> None:
    """Adds r["nifty"]: +1 / -1 if the last NIFTY 5m bar closed at or before the entry is above / below the day's open,
    0 if equal, None if there is no completed bar that day (best_practice_tests_protocol.md)."""
    idx = nifty.index
    close_t = idx + pd.Timedelta(minutes=5)                          # a 5m bar labelled 09:15 closes at 09:20
    day_open = nifty["open"].groupby(idx.date).transform("first")
    days = pd.Series(idx.date, index=idx)
    for r in rows:
        k = close_t.searchsorted(r["time"], side="right") - 1
        if k < 0 or days.iloc[k] != r["time"].date():
            r["nifty"] = None
            continue
        diff = nifty["close"].iloc[k] - day_open.iloc[k]
        r["nifty"] = 0 if diff == 0 else (1 if diff > 0 else -1)


def passes_family(s: dict) -> bool:
    return passes(s) and s["p_day"] < 0.025


def h3(folder: Path, stage: str, nifty_path: Path, cache: Path | None) -> None:
    a, b = s3.SPLITS[stage]
    nifty = pd.read_pickle(nifty_path)
    nifty.index = pd.DatetimeIndex(nifty.index).tz_convert("Asia/Kolkata")
    rows = [r for r in stock_rows(folder, cache) if a <= r["day"] <= b and r["time"] < nifty.index[-1]]
    nifty_state(nifty, rows)
    rows = [r for r in rows if r["nifty"] is not None]
    print(f"stocks {len({r['sym'] for r in rows})}, trades with a NIFTY state {len(rows)}")
    line("V0 all                 ", rows)
    aligned = [r for r in rows if r["nifty"] == r["side"]]
    line("counter-aligned/flat   ", [r for r in rows if r["nifty"] != r["side"]])
    s3_ = line("H3 aligned             ", aligned)
    s4_ = line("H4 aligned + morning   ", [r for r in aligned if r["time"].hour < 12])
    line("H1 morning (reference) ", [r for r in rows if r["time"].hour < 12])
    for name, s in (("H3", s3_), ("H4", s4_)):
        print(f"{name}: {'PASS' if passes_family(s) else 'FAIL'} (p(day) {s.get('p_day', float('nan')):.4f})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("which", choices=["h1", "h2", "h3"])
    ap.add_argument("folder", type=Path)
    ap.add_argument("--stage", choices=["train", "validation", "final"], required=True)
    ap.add_argument("--original", type=Path)
    ap.add_argument("--cache", type=Path)
    ap.add_argument("--nifty", type=Path)
    x = ap.parse_args()
    if x.which == "h1":
        h1(x.folder, x.stage, x.original, x.cache)
    elif x.which == "h2":
        h2(x.folder, x.stage)
    else:
        h3(x.folder, x.stage, x.nifty, x.cache)
