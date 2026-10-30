"""Locked evaluation (blueprint section 9; A section 5). numpy only.

* Stationary block bootstrap (Politis-Romano), expected block 5 sessions, 50,000 replicates, seed 20261026, on the
  daily series (zero-trade days included). The one-sided test of mean > 0 is null-centred:
  p = (1 + #{mean*(x - xbar) >= xbar}) / (1 + B). Bounds are basic bootstrap bounds from the same centred draws.
* Robustness hurdles: circular block bootstrap with FIXED blocks of 10 and 20 sessions; both must also pass.
* Power: N = ceil(1.5 x ((z_(1-a) + z_power) x sigma / delta)^2) with z_(1-0.003125) = 2.734, z_0.80 = 0.842.
* Stage rules: pilot futility (upper 90% bound < 0 under strict fills -> FAIL), validation gate, one-look final.
Verdicts: PASS / FAIL / INCONCLUSIVE / INFEASIBLE; "CONTINUE" is a stage decision, not a verdict.
These are asymptotic approximations, not finite-sample guarantees against unknown tails.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

SEED = 20261026
REPS = 50_000
BLOCK = 5
ROBUST_BLOCKS = (10, 20)
ALPHA = 0.003125
Z_ALPHA, Z_POWER = 2.734, 0.842
INFLATION = 1.5
SESSIONS_PER_YEAR = 248
MAX_YEARS = 5


# ------------------------------------------------------------------ resampling
def stationary_indices(n: int, mean_block: float, reps: int, rng: np.random.Generator) -> np.ndarray:
    """reps x n indices: a new block starts with probability 1/mean_block, blocks wrap around (circular)."""
    p = 1.0 / mean_block
    new = rng.random((reps, n)) < p
    new[:, 0] = True
    starts = rng.integers(0, n, (reps, n))
    t = np.arange(n)
    pos = np.maximum.accumulate(np.where(new, t, 0), axis=1)
    return (np.take_along_axis(starts, pos, axis=1) + (t - pos)) % n


def fixed_block_indices(n: int, block: int, reps: int, rng: np.random.Generator) -> np.ndarray:
    """Circular block bootstrap with blocks of exactly `block` sessions."""
    k = math.ceil(n / block)
    starts = rng.integers(0, n, (reps, k))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % n
    return idx.reshape(reps, k * block)[:, :n]


def boot_means(x: np.ndarray, block: float, reps: int = REPS, seed: int = SEED, kind: str = "stationary",
               chunk: int = 2_000) -> np.ndarray:
    """Means of `reps` bootstrap resamples of x, generated in chunks (memory), reproducible from the seed."""
    rng = np.random.default_rng(seed)
    out = np.empty(reps)
    n = len(x)
    for a in range(0, reps, chunk):
        b = min(reps, a + chunk)
        idx = stationary_indices(n, block, b - a, rng) if kind == "stationary" else fixed_block_indices(n, int(block),
                                                                                                        b - a, rng)
        out[a:b] = x[idx].mean(axis=1)
    return out


@dataclass(frozen=True)
class MeanTest:
    n: int
    mean: float
    sd: float
    p: float                    # one-sided, null-centred
    lower: float                # one-sided lower bound at 1 - alpha
    upper90: float              # one-sided upper bound at 90%
    block: float
    kind: str


def mean_test(x, block: float = BLOCK, kind: str = "stationary", alpha: float = ALPHA, reps: int = REPS,
              seed: int = SEED) -> MeanTest:
    x = np.asarray(x, float)
    if len(x) < 2 or not np.all(np.isfinite(x)):
        raise ValueError("need >= 2 finite daily values (unresolved days must be bounded before testing)")
    m = float(x.mean())
    c = boot_means(x - m, block, reps, seed, kind)
    p = (1 + int(np.sum(c >= m))) / (1 + reps)
    lower = m - float(np.quantile(c, 1 - alpha))
    upper90 = m - float(np.quantile(c, 0.10))
    return MeanTest(len(x), m, float(x.std(ddof=1)), p, lower, upper90, block, kind)


# ------------------------------------------------------------------ power
def required_sessions(sigma: float, delta: float, z_alpha: float = Z_ALPHA, z_power: float = Z_POWER,
                      inflation: float = INFLATION) -> int:
    if delta <= 0 or sigma < 0:
        raise ValueError("delta must be > 0")
    return int(math.ceil(inflation * ((z_alpha + z_power) * sigma / delta) ** 2))


def mean_detectable(n: int, sigma: float = 1.0, z_alpha: float = Z_ALPHA, z_power: float = Z_POWER) -> float:
    """The smallest mean (in units of sigma) with 80% power at n independent observations."""
    return (z_alpha + z_power) * sigma / math.sqrt(n)


def max_sessions(years: int = MAX_YEARS) -> int:
    return years * SESSIONS_PER_YEAR


# ------------------------------------------------------------------ stage decisions
@dataclass(frozen=True)
class Decision:
    stage: str
    status: str                 # CONTINUE | PASS | FAIL | INCONCLUSIVE | INFEASIBLE
    reasons: tuple
    stats: dict


def pilot_decision(strict_best, delta: float, n_expected: int, reps: int = REPS, seed: int = SEED) -> Decision:
    """Pilot (60 sessions): futility if the 90% upper bound of the strict series (unresolved at their BEST bound) is
    below zero; otherwise the final length N from the pilot SD, INFEASIBLE if N cannot finish within 5 years."""
    x = np.asarray(strict_best, float)
    if len(x) < n_expected:
        return Decision("pilot", "INCONCLUSIVE", (f"only {len(x)} of {n_expected} pilot sessions",), {})
    t = mean_test(x, reps=reps, seed=seed)
    n_final = required_sessions(t.sd, delta)
    st = {"mean": t.mean, "sd": t.sd, "upper90": t.upper90, "n_final": n_final}
    if t.upper90 < 0:
        return Decision("pilot", "FAIL", ("futility: the 90% upper bound of the mean is below zero",), st)
    if n_final > max_sessions():
        return Decision("pilot", "INFEASIBLE", (f"N = {n_final} sessions exceeds 5 years",), st)
    return Decision("pilot", "CONTINUE", (), st)


def validation_decision(primary_worst, widened_worst, coverage: float, count: int, min_count: int) -> Decision:
    """Validation (60 sessions, frozen rules): total > 0, widened total > 0, coverage >= 95%, enough trades."""
    p, w = float(np.sum(primary_worst)), float(np.sum(widened_worst))
    st = {"total": p, "total_widened": w, "coverage": coverage, "count": count}
    if count < min_count:
        return Decision("validation", "INFEASIBLE", (f"{count} < {min_count} trades/structures",), st)
    bad = [r for r, ok in (("total net <= 0", p > 0), ("widened total <= 0", w > 0),
                           ("coverage < 95%", coverage >= 0.95)) if not ok]
    return Decision("validation", "FAIL" if bad else "CONTINUE", tuple(bad), st)


def _final_pass(x, widened, adverse, delta, alpha, reps, seed) -> tuple[bool, list, dict]:
    reasons, st = [], {}
    t5 = mean_test(x, BLOCK, "stationary", alpha, reps, seed)
    st["stationary5"] = t5.__dict__
    if not t5.p < alpha:
        reasons.append(f"p {t5.p:.4f} >= {alpha} (stationary, block 5)")
    if not t5.lower > 0:
        reasons.append("lower bound <= 0")
    for b in ROBUST_BLOCKS:
        tb = mean_test(x, b, "fixed", alpha, reps, seed)
        st[f"fixed{b}"] = tb.__dict__
        if not tb.p < alpha:
            reasons.append(f"p {tb.p:.4f} >= {alpha} (fixed block {b})")
    if not t5.mean >= delta:
        reasons.append(f"mean {t5.mean:.4g} < practical effect {delta}")
    if not float(np.sum(x)) > 0:
        reasons.append("total <= 0")
    if widened is not None and not float(np.sum(widened)) > 0:
        reasons.append("widened total <= 0")
    if adverse is not None and not float(np.mean(adverse)) > 0:
        reasons.append("adverse-stress mean <= 0")
    return not reasons, reasons, st


def final_decision(worst, best, delta: float, n_required: int, count: int, min_count: int, coverage: float,
                   widened=None, adverse=None, alpha: float = ALPHA, reps: int = REPS, seed: int = SEED,
                   extra_checks: dict | None = None) -> Decision:
    """The one look. Unresolved exposures enter `worst` at their worst bound and `best` at their best: if the two
    disagree, the verdict is INCONCLUSIVE. Short samples or counts are INCONCLUSIVE, never a pass."""
    x = np.asarray(worst, float)
    if len(x) < n_required:
        return Decision("final", "INCONCLUSIVE", (f"{len(x)} of {n_required} final sessions",), {})
    if count < min_count or coverage < 0.95:
        return Decision("final", "INCONCLUSIVE", (f"count {count} (min {min_count}), coverage {coverage:.1%}",), {})
    ok_w, why_w, st = _final_pass(x, widened, adverse, delta, alpha, reps, seed)
    gates = [f"check failed: {k}" for k, v in (extra_checks or {}).items() if not v]
    if gates:                                                      # a validity gate fails whatever the P&L says
        return Decision("final", "FAIL", tuple(gates + why_w), st)
    ok_b, _, _ = _final_pass(np.asarray(best, float), widened, adverse, delta, alpha, reps, seed)
    if ok_w != ok_b:
        return Decision("final", "INCONCLUSIVE", ("unresolved exposure could flip the verdict",), st)
    return Decision("final", "PASS" if ok_w else "FAIL", tuple(why_w), st)
