"""Perturbation and signal-similarity helpers for the robustness study (review M09).

Perturbations are bounded and on the futures tick grid:
  shift(k)  : every price of a bar moves by the SAME integer number of ticks, uniform in [-k, k]. Candle geometry
              (range, body, wicks) is unchanged, so this isolates sensitivity to the price level and to thresholds.
  jitter(k) : open, high, low and close move independently by integer ticks in [-k, k], then high/low are repaired
              to stay the bar's extremes. This changes candle geometry (ranges grow on average); the mean range
              change is reported with the results so the perturbation is labelled honestly.
Similarity between the baseline and a perturbed signal set uses precision, recall and Jaccard, with a timing
tolerance in bars (a signal one bar later on the same side counts as the same signal when tol >= 1).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _ticks(rng: np.random.Generator, k: int, size) -> np.ndarray:
    return rng.integers(-k, k + 1, size=size)


def shift(bars: pd.DataFrame, k: int, tick: float, seed: int) -> pd.DataFrame:
    b = bars.copy()
    s = _ticks(np.random.default_rng(seed), k, len(b)) * tick
    for c in ("open", "high", "low", "close"):
        b[c] = (b[c] + s).round(6)
    return b


def jitter(bars: pd.DataFrame, k: int, tick: float, seed: int) -> pd.DataFrame:
    b = bars.copy()
    rng = np.random.default_rng(seed)
    for c in ("open", "high", "low", "close"):
        b[c] = (b[c] + _ticks(rng, k, len(b)) * tick).round(6)
    b["high"] = b[["open", "high", "close"]].max(axis=1)
    b["low"] = b[["open", "low", "close"]].min(axis=1)
    return b


def mean_range_change(base: pd.DataFrame, pert: pd.DataFrame) -> float:
    return float(((pert["high"] - pert["low"]) - (base["high"] - base["low"])).mean())


def similarity(base: list[tuple[pd.Timestamp, str]], pert: list[tuple[pd.Timestamp, str]], tol_bars: int,
               bar: pd.Timedelta) -> dict:
    """Greedy one-to-one matching on (time, side) within tol_bars bars."""
    used, matched = set(), 0
    for t, side in sorted(pert):
        best = None
        for j, (u, s2) in enumerate(base):
            if j in used or s2 != side or abs(u - t) > tol_bars * bar:
                continue
            if best is None or abs(u - t) < abs(base[best][0] - t):
                best = j
        if best is not None:
            used.add(best)
            matched += 1
    nb, npt = len(base), len(pert)
    union = nb + npt - matched
    return {"matched": matched, "precision": matched / npt if npt else float("nan"),
            "recall": matched / nb if nb else float("nan"), "jaccard": matched / union if union else 1.0}
