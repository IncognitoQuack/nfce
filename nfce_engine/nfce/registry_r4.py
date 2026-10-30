"""Frozen pass/fail rule of registered experiment R4 (../evidence/r4_protocol.md). SHA-256 recorded in REGISTRY.md."""
from __future__ import annotations

import statistics

from .registry import ALPHA_EXPERIMENT, Verdict, _fmt, day_means, one_sample

R4_MIN_PAIRS = 100
R4_MIN_DIFF_R = 0.05
R4_ALPHA = ALPHA_EXPERIMENT                                # 0.05 / 4: one of the four confirmatory experiments


def judge_r4(pairs: list[tuple[float, float]], days: list | None = None) -> Verdict:
    """pairs: (net R executable, net R r4) of the same signal, both books CLOSED. days: session of each pair; the
    paired test runs on day means. A PASS says range targets beat fixed targets; it says nothing about profit
    (the absolute results of both books are reported next to it and must be judged separately)."""
    v = Verdict("R4 range-calibrated targets vs fixed targets (paired)", "INCONCLUSIVE")
    if len(pairs) < R4_MIN_PAIRS:
        v.note = f"{len(pairs)} paired trades, {R4_MIN_PAIRS} required"
        return v
    diffs = [r4 - ex for ex, r4 in pairs]
    m = statistics.fmean(diffs)
    _, t, p = one_sample(day_means(diffs, days))
    v.checks = {"mean difference (r4 - fixed)": (_fmt(m), f">= +{R4_MIN_DIFF_R}", m >= R4_MIN_DIFF_R),
                "paired one-sided p": (f"{p:.4f} (t={t:+.2f})", f"< {R4_ALPHA:.4f}", p < R4_ALPHA)}
    v.result = "PASS" if all(c[2] for c in v.checks.values()) else "FAIL"
    v.note = (f"absolute results: fixed targets {statistics.fmean(e for e, _ in pairs):+.3f}R, range targets "
              f"{statistics.fmean(r for _, r in pairs):+.3f}R per trade (a relative PASS with losing books is not a "
              f"reason to trade)")
    return v
