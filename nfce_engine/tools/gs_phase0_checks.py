"""GS phase 0 diagnostics for review A's findings that are real but are not fixed inside a registered scorer.

  frames: study.frame keeps a stock-day only if the WHOLE session has >= 50% of its bars (a future-dependent filter,
          finding 2). This counts, per file, the days it drops and how many of them had a complete opening range
          (the first two 3-minute bars), i.e. days a live system would have been able to trade at 09:21.

  nice -n 15 ../nfce_bridge/.venv/bin/python tools/gs_phase0_checks.py frames
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gs import calendar as cal  # noqa: E402
from tools import study as s1  # noqa: E402


def frame_exclusions(b: pd.DataFrame, tf: int) -> dict:
    """Days study.frame drops for having < 50% of the session's bars, and how many of those had the opening range."""
    d = b[["open", "high", "low", "close", "volume"]].astype(float).copy()
    d.index = pd.DatetimeIndex(d.index).tz_convert(s1.TZ)
    d = d[~d.index.duplicated(keep="first")].sort_index()
    hm = d.index.hour * 60 + d.index.minute
    d = d[(hm >= s1.OPEN) & (hm <= 15 * 60 + 30 - tf)]
    key = d.index.normalize()
    cnt = pd.Series(1, index=d.index).groupby(key).size()
    dropped = cnt[cnt < 0.5 * (375 // tf)]
    hm = pd.Series(d.index.hour * 60 + d.index.minute, index=d.index)
    first2 = hm[hm < s1.OPEN + 2 * tf].groupby(hm[hm < s1.OPEN + 2 * tf].index.normalize()).size()
    had_or = [k for k in dropped.index if first2.get(k, 0) >= 2]
    regular = [k for k in had_or if cal.COVERED_FROM <= k.date() <= cal.COVERED_UNTIL and cal.is_session(k.date())]
    return {"days": int(len(cnt)), "dropped": int(len(dropped)), "dropped_with_opening_range": len(had_or),
            "dropped_regular_with_opening_range": len(regular), "examples": [str(k.date()) for k in regular[:5]]}


def frames() -> dict:
    tot = {"files": 0, "days": 0, "dropped": 0, "dropped_with_opening_range": 0, "dropped_regular_with_opening_range": 0}
    per = {}
    for f in sorted(s1.HIST3M.glob("*_3m.pkl")):
        r = frame_exclusions(s1.load_bars(f), 3)
        tot["files"] += 1
        for k in ("days", "dropped", "dropped_with_opening_range", "dropped_regular_with_opening_range"):
            tot[k] += r[k]
        if r["dropped_regular_with_opening_range"]:
            per[f.stem] = r
    tot["worst_files"] = dict(sorted(per.items(), key=lambda kv: -kv[1]["dropped_regular_with_opening_range"])[:8])
    return tot


if __name__ == "__main__":
    if sys.argv[1:] == ["frames"]:
        print(json.dumps(frames(), indent=1))
