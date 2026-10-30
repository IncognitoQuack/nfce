"""Replay real 5m data through the bridge's paper ledger (theoretical book), as if live, and compare with the engine.

  python tools/paper_replay.py [NSEI|NSEBANK] [--data DIR]     (needs tools/fetch_yahoo.py data)

Every engine signal opens a theoretical PaperTrade at the signal bar's close. Each later bar is fed as four quotes in
the adverse-first order (open, worst extreme, best extreme, close), the same conservative ordering the backtests
use (stop checked before targets; a moved stop is enforced at the close). The ledger should reproduce the engine's
gross result for every trade. Differences are listed, not hidden: the expected one is a stop that the bar OPENS
beyond (the engine fills at the open, the ledger at the stop unless its quote gap rule fires).
FIX v2: rewritten for the v2 bridge API (PaperBook.open_trade / on_quote); the v1 script called removed methods.
"""
from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "nfce_bridge"))
from bridge.paper import PaperBook, PaperTrade  # noqa: E402
from bridge.providers import Quote  # noqa: E402
from bridge.store import Store  # noqa: E402
from nfce import Params, prepare, run  # noqa: E402
from nfce.data import load_csv  # noqa: E402

SETUP = {"NSEI": ("NIFTY", ["HDFCBANK", "ICICIBANK", "RELIANCE", "INFY", "BHARTIARTL"]),
         "NSEBANK": ("BANKNIFTY", ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK"])}


def main(index_name: str, data: Path) -> int:
    instr, hw_names = SETUP[index_name]
    load = lambda n: load_csv(data / f"{n}_5m.csv", 5)[0]  # noqa: E731
    idx, vix, hws = load(index_name), load("INDIAVIX"), [load(s) for s in hw_names]
    bars = idx[["open", "high", "low", "close"]].copy()
    bars["volume"] = sum(h["volume"].reindex(idx.index).fillna(0) for h in hws)
    p = Params(instr=instr)
    trades = run(prepare(bars, 5, p, vix=vix, hw=hws), p)
    by_entry = {t.entry_time: t for t in trades}

    book = PaperBook(Store(Path(":memory:")))
    pairs = []
    for ts, b in bars.iterrows():
        close_t = ts + timedelta(minutes=5)
        if book.open:
            for t in list(book.open):
                path = [b.open, b.low, b.high, b.close] if t.side > 0 else [b.open, b.high, b.low, b.close]
                for k, px in enumerate(path):
                    when = (close_t if k == 3 else ts + timedelta(minutes=k)).to_pydatetime()
                    q = Quote(instr, float(px), when, when)
                    if t.on_quote(q, when, max_gap_s=600):
                        book.open.remove(t)
                        break
        if close_t in by_entry:                       # the engine signalled at this bar's close
            e = by_entry[close_t]
            s = 1 if e.side == "L" else -1
            pt = PaperTrade("theoretical", instr, "5", "PASS", e.grade, s, e.entry, e.entry - s * e.R,
                            e.entry + s * p.r1m * e.R, e.entry + s * p.r2m * e.R, e.entry + s * p.r3m * e.R,
                            close_t.isoformat(), sid=f"replay-{close_t:%Y%m%d%H%M}")
            pt.last_seen = close_t.isoformat()
            book.open.append(pt)
            pairs.append((e, pt))

    same = 0
    print(f"[{instr}] {len(pairs)} engine trades replayed through the paper ledger")
    print(f"{'entry':12s} side engine R  paper R  engine exit / paper exit")
    for e, pt in pairs:
        er = e.pnl / e.R
        pr_ = pt.pnl / pt.R if pt.status == "CLOSED" else float("nan")
        ok = abs(er - pr_) < 1e-6
        same += ok
        print(f"{e.entry_time:%m-%d %H:%M}  {e.side}   {er:+6.2f}   {pr_:+6.2f}   {e.exit} / {pt.exit_reason}"
              f"{'' if ok else '   <-- differs'}")
    print(f"\n{same}/{len(pairs)} trades identical (gross R)")
    return 0 if same == len(pairs) else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("index", nargs="?", default="NSEI", choices=sorted(SETUP))
    ap.add_argument("--data", type=Path, default=ROOT / "data" / "yahoo")
    a = ap.parse_args()
    sys.exit(main(a.index, a.data))
