"""Reversed stock 3m signals (../evidence/reversed_signals_protocol.md, SHA-256 5e28c28d…fbd68).

  python tools/reversed_signals.py <hist3m folder> [--cache rows.pkl]

Train stage only (2022–24). The same engine run gives V0 (the original exits) and REV (opposite side, mirrored
stop/target), so both are computed on identical signals.
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce.research2 import _walk  # noqa: E402
from tools import stock3m_research as s3  # noqa: E402


def rev_walker(d, j0, side, entry, R0):
    stop, tgt = entry + side * R0, entry - side * R0        # the original target becomes the stop, and vice versa
    px, why, _ = _walk(d, j0, -side, stop, tgt, s3.EOD)
    return 2 * entry - px, why, R0                           # mirrored, so side * (px' - entry) = the reversed gross


def passes(s: dict) -> bool:
    return bool(s.get("n")) and s["net_r"] > 0 and s["ci"][0] > 0 and s["p_day"] < 0.05


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--cache", type=Path)
    x = ap.parse_args()
    if x.cache and x.cache.exists():
        rows = pickle.loads(x.cache.read_bytes())
    else:
        rows = s3.trades(x.folder, mults=(1,), walkers={"REV": rev_walker})
        if x.cache:
            x.cache.write_bytes(pickle.dumps(rows))
    a, b = s3.SPLITS["train"]
    res = {}
    for name in (1, "REV"):
        r = [t for t in rows[name] if a <= t["day"] <= b]
        s = s3.stats(r)
        res["V0" if name == 1 else "REV"] = s | {"pass": passes(s) if name == "REV" else None}
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
