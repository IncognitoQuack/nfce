"""Pass/fail rules of the three pre-registered experiments (REGISTRY.md). Pure functions; constants are frozen.

Changing anything in this file after data collection starts invalidates the registration: REGISTRY.md records
this file's SHA-256. Every verdict is PASS, FAIL or INCONCLUSIVE (not enough clean data). INCONCLUSIVE is never
read as "almost passed".

Family-wise error (re-registered 20 Oct 2026, before any live data; review round 3, M05): the four confirmatory
experiments R1-R4 share ONE family alpha = 0.05, Bonferroni, one-sided -> 0.05 / 4 = 0.0125 each (R2: half per index).
R5 is closed and was never part of this family.

Inference (M05): trades on the same day are not independent. Every test runs on DAY MEANS (one value per session,
or per session and group), so clustered intraday trades cannot inflate t. Each verdict is computed ONCE, the first time
its minimum sample is reached; no re-looks, no extensions after seeing results.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

ALPHA_FAMILY = 0.05
N_CONFIRMATORY = 4                                       # R1, R2, R3, R4
ALPHA_EXPERIMENT = ALPHA_FAMILY / N_CONFIRMATORY         # one-sided, per experiment

# R1: Nifty H1 ORB (stop = mid) executed through a 1-ITM option vs the same signals in futures
R1_MIN_TRADES = 200
R1_MAX_SKIPPED_SHARE = 0.10                              # more skips than this = the sample may be selected by data gaps
R1_MIN_NET_R = 0.10                                      # option leg, in units of the underlying risk (R pts x lot)
R1_MIN_SESSIONS = 100                                    # distinct sessions with at least one paired trade

# R2: H-A volatility-gated 15m ORB, single exit, futures, both indices
R2_MIN_TRADES = 250                                      # per index
R2_MIN_NET_R = 0.12
R2_MIN_PF = 1.20
R2_MIN_POSITIVE_YEARS = 3                                # calendar years with >= R2_YEAR_MIN_TRADES trades
R2_YEAR_MIN_TRADES = 30
R2_FRICTION_RT_PTS = {"NIFTY": 1.5, "BANKNIFTY": 4.0}    # round-trip spread + slippage on top of fees

# R3: option-chain veto, prospective shadow test in the bridge's executable paper book
R3_MIN_SIGNALS = 200
R3_MIN_VETOES = 40
R3_MIN_DIFF_R = 0.20
R3_MIN_PASSES = 40                                       # FIX (M04): both groups need a minimum size


def _t_sf(t: float, df: int) -> float:
    """One-sided upper-tail p-value of Student's t."""
    try:
        from scipy.stats import t as student
        return float(student.sf(t, df))
    except ImportError:
        return 0.5 * math.erfc(t / math.sqrt(2))


def one_sample(xs: list[float]) -> tuple[float, float, float]:
    """mean, t, one-sided p (H1: mean > 0)."""
    n = len(xs)
    if n < 2:
        return (xs[0] if xs else math.nan), math.nan, math.nan
    m, sd = statistics.fmean(xs), statistics.stdev(xs)
    if sd == 0:
        return m, (math.inf if m > 0 else -math.inf if m < 0 else 0.0), (0.0 if m > 0 else 1.0)
    t = m / (sd / math.sqrt(n))
    return m, t, _t_sf(t, n - 1)


def welch(a: list[float], b: list[float]) -> tuple[float, float, float]:
    """mean(a) - mean(b), Welch t, one-sided p (H1: a > b)."""
    va, vb = statistics.variance(a) / len(a), statistics.variance(b) / len(b)
    d = statistics.fmean(a) - statistics.fmean(b)
    se = math.sqrt(va + vb)
    if se == 0:
        return d, math.nan, math.nan
    df = (va + vb) ** 2 / (va ** 2 / (len(a) - 1) + vb ** 2 / (len(b) - 1))
    t = d / se
    return d, t, _t_sf(t, max(int(df), 1))


def day_means(xs: list[float], days: list | None) -> list[float]:
    """One value per session (mean of that session's trades). days=None: every trade is its own cluster."""
    if days is None:
        return list(xs)
    assert len(days) == len(xs), "one day per trade"
    g: dict = {}
    for d, x in zip(days, xs):
        g.setdefault(d, []).append(x)
    return [statistics.fmean(g[d]) for d in sorted(g)]


@dataclass
class Verdict:
    experiment: str
    result: str                                   # PASS / FAIL / INCONCLUSIVE
    checks: dict = field(default_factory=dict)    # name -> (value, required, ok)
    note: str = ""

    def text(self) -> str:
        lines = [f"{self.experiment}: {self.result}" + (f" ({self.note})" if self.note else "")]
        for k, (v, req, ok) in self.checks.items():
            lines.append(f"  {'ok ' if ok else 'NO '} {k}: {v} (required {req})")
        return "\n".join(lines)


def _fmt(x) -> str:
    return f"{x:+.3f}" if isinstance(x, float) else str(x)


def judge_r1(option_r: list[float], futures_r: list[float], skipped: int, days: list | None = None,
             stress_r: list[float] | None = None, net_inr: list[float] | None = None) -> Verdict:
    """option_r / futures_r: net results of the SAME executed signals, in R; skipped: signals without quotes.
    days: session of each trade (tests run on day means). stress_r: option net R with every spread widened 1.5x.
    net_inr: option net rupees per trade (the absolute result must be positive too)."""
    n = len(option_r)
    assert n == len(futures_r), "R1 is a paired test: one futures result per option result"
    total = n + skipped
    v = Verdict("R1 ITM-option execution of Nifty ORB-mid", "INCONCLUSIVE")
    if n < R1_MIN_TRADES:
        v.note = f"{n} executed trades, {R1_MIN_TRADES} required"
        return v
    if days is not None and len(set(days)) < R1_MIN_SESSIONS:
        v.note = f"{len(set(days))} sessions, {R1_MIN_SESSIONS} required"
        return v
    if total and skipped / total > R1_MAX_SKIPPED_SHARE:
        v.note = f"{skipped} of {total} signals skipped for missing quotes (max {R1_MAX_SKIPPED_SHARE:.0%})"
        return v
    m = statistics.fmean(option_r)
    _, t, p = one_sample(day_means(option_r, days))
    dm = statistics.fmean([a - b for a, b in zip(option_r, futures_r)])
    _, dt, dp = one_sample(day_means([a - b for a, b in zip(option_r, futures_r)], days))
    v.checks = {
        "option net R per trade": (_fmt(m), f">= +{R1_MIN_NET_R}", m >= R1_MIN_NET_R),
        "option net R > 0, one-sided p": (f"{p:.4f} (t={t:+.2f})", f"< {ALPHA_EXPERIMENT:.4f}", p < ALPHA_EXPERIMENT),
        "option minus futures (paired), one-sided p": (f"{dp:.4f} (diff {dm:+.3f}R, t={dt:+.2f})",
                                                       f"< {ALPHA_EXPERIMENT:.4f}", dp < ALPHA_EXPERIMENT),
    }
    if stress_r is not None:
        ms = statistics.fmean(stress_r)
        v.checks["option net R with spreads x1.5"] = (_fmt(ms), "> 0", ms > 0)
    if net_inr is not None:
        tot = float(sum(net_inr))
        v.checks["option net rupees (total)"] = (f"{tot:+,.0f}", "> 0", tot > 0)
    v.result = "PASS" if all(c[2] for c in v.checks.values()) else "FAIL"
    return v


def judge_r2(per_index: dict[str, list[tuple[int, float, float]]]) -> Verdict:
    """per_index: index -> [(calendar year, net R, net rupees)] under CURRENT costs + R2 friction.
    R2 trades at most once a day, so trades are already day clusters."""
    v = Verdict("R2 H-A volatility-gated 15m ORB (futures)", "INCONCLUSIVE")
    alpha = ALPHA_EXPERIMENT / 2
    short = [f"{k} {len(x)}" for k, x in per_index.items() if len(x) < R2_MIN_TRADES]
    if len(per_index) < 2 or short:
        v.note = f"needs both indices with >= {R2_MIN_TRADES} trades each" + (f"; have {', '.join(short)}" if short else "")
        return v
    for k, rows in per_index.items():
        rs = [r for _, r, _ in rows]
        m, t, p = one_sample(rs)
        gw = sum(x for _, _, x in rows if x > 0)
        gl = -sum(x for _, _, x in rows if x < 0)
        pf = gw / gl if gl > 0 else math.inf
        years: dict = {}
        for y, r, _ in rows:
            years.setdefault(y, []).append(r)
        good = sum(1 for xs in years.values() if len(xs) >= R2_YEAR_MIN_TRADES and statistics.fmean(xs) > 0)
        v.checks[f"{k} net R per trade"] = (_fmt(m), f">= +{R2_MIN_NET_R}", m >= R2_MIN_NET_R)
        v.checks[f"{k} one-sided p"] = (f"{p:.4f} (t={t:+.2f})", f"< {alpha:.4f}", p < alpha)
        v.checks[f"{k} profit factor"] = (f"{pf:.2f}", f">= {R2_MIN_PF}", pf >= R2_MIN_PF)
        v.checks[f"{k} positive years"] = (good, f">= {R2_MIN_POSITIVE_YEARS}", good >= R2_MIN_POSITIVE_YEARS)
    v.result = "PASS" if all(c[2] for c in v.checks.values()) else "FAIL"
    return v


def judge_r3(pass_r: list[float], veto_r: list[float], pass_days: list | None = None,
             veto_days: list | None = None) -> Verdict:
    """Closed executable-book trades: signals the rule passed vs signals it vetoed (shadow), net R.
    Welch's test runs on day means of each group."""
    v = Verdict("R3 option-chain veto (prospective shadow test)", "INCONCLUSIVE")
    n = len(pass_r) + len(veto_r)
    if n < R3_MIN_SIGNALS or len(veto_r) < R3_MIN_VETOES or len(pass_r) < R3_MIN_PASSES:
        v.note = (f"{n} closed signals ({len(pass_r)} passed, {len(veto_r)} vetoed); {R3_MIN_SIGNALS} incl. "
                  f">= {R3_MIN_PASSES} passed and >= {R3_MIN_VETOES} vetoed required")
        return v
    a, b = day_means(pass_r, pass_days), day_means(veto_r, veto_days)
    if len(a) < 2 or len(b) < 2:
        v.note = "each group needs trades on at least two sessions"
        return v
    _, t, p = welch(a, b)
    d = statistics.fmean(pass_r) - statistics.fmean(veto_r)
    mp = statistics.fmean(pass_r)
    v.checks = {
        "PASS minus VETO net R": (_fmt(d), f">= +{R3_MIN_DIFF_R}", d >= R3_MIN_DIFF_R),
        "Welch one-sided p": (f"{p:.4f} (t={t:+.2f})", f"< {ALPHA_EXPERIMENT:.4f}", p < ALPHA_EXPERIMENT),
        "PASS signals net R > 0": (_fmt(mp), "> 0", mp > 0),
    }
    v.result = "PASS" if all(c[2] for c in v.checks.values()) else "FAIL"
    v.note = "" if v.result == "PASS" else "delete the veto rule"
    return v
