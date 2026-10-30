"""Market regime labels (28 Oct 2026): descriptive and causal; NOT a trading rule.

The owner asked for a system that "considers the volatile market and is dynamic". Firms switch behaviour by regime only
after measuring that their signals behave differently across regimes. This module supplies the labels so that can be
measured: the desk shows the live regime, and ops/signal_context.py stamps it on every signal. A rule that uses it must
first pass a locked protocol.

Labels (thresholds declared 28 Oct, before any signal outcome was joined to them):
* volatility: VIX's percentile among the previous 252 daily closes → "stressed" if ≥ 0.80 or VIX is up ≥ 8% on the
  day; "calm" if ≤ 0.30; else "normal";
* direction: NIFTY's day change and breadth (share of F&O stocks up) → "trend up" if ≥ +0.6% and breadth ≥ 0.60;
  "trend down" if ≤ −0.6% and breadth ≤ 0.40; without breadth, ±0.8% alone; else "mixed".
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

VIX_DAILY = Path.home() / "Downloads" / "nfce_data" / "daily" / "INDIAVIX_1d.pkl"


@lru_cache(maxsize=4)
def vix_history(path: str = str(VIX_DAILY), n: int = 252) -> tuple:
    """The last n daily VIX closes before today (the daily file holds completed sessions only)."""
    import pandas as pd
    v = pd.read_pickle(path)["close"].dropna()
    return tuple(float(x) for x in v.tail(n))


def vix_percentile(vix: float | None, history) -> float | None:
    if vix is None or not history:
        return None
    return sum(h <= vix for h in history) / len(history)


def classify(vix: float | None, vix_chg_pct: float | None, nifty_chg_pct: float | None, breadth: float | None,
             history=None) -> dict:
    pct = vix_percentile(vix, history if history is not None else _safe_history())
    if pct is None:
        vol = None
    elif pct >= 0.80 or (vix_chg_pct is not None and vix_chg_pct >= 8.0):
        vol = "stressed"
    elif pct <= 0.30:
        vol = "calm"
    else:
        vol = "normal"
    if nifty_chg_pct is None:
        trend = None
    elif breadth is not None:
        trend = ("trend up" if nifty_chg_pct >= 0.6 and breadth >= 0.60 else
                 "trend down" if nifty_chg_pct <= -0.6 and breadth <= 0.40 else "mixed")
    else:
        trend = "trend up" if nifty_chg_pct >= 0.8 else "trend down" if nifty_chg_pct <= -0.8 else "mixed"
    return {"vol": vol, "trend": trend, "vix_pct": pct,
            "text": " · ".join(x for x in (vol, trend) if x) or "unknown"}


def _safe_history() -> tuple:
    try:
        return vix_history()
    except Exception:                          # no daily file: the volatility label is unknown, never an error
        return ()
