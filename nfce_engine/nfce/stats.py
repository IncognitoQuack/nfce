"""Costs and statistics.

Two cost models:
  legacy  : the Phase 2-3 approximation (0.03% of entry notional per side + 4 ticks per side). Kept only so the
            v1 numbers can be reproduced exactly (tests/test_stats_parity.py).
  dated   : nfce.costs schedule in force on each trade's date (STT, exchange, SEBI, stamp, GST, Rs 20/order with
            the trade's actual order count amortised over the lots traded) + execution friction in index points.
  current : the same schedule frozen at the current date, applied to every trade ("current-cost stress").

Uncertainty: IID Student-t, plus moving-block bootstrap over trading DAYS and WEEKS (trades on the same day or week
are not independent), Clopper-Pearson interval for the win rate, Holm and Bonferroni family-wise corrections.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date

from . import costs

COMM_SIDE = 0.0003
SLIP_TICKS = 4


# ----------------------------------------------------------------------------- legacy (v1) model
@dataclass
class Summary:
    n: int
    win: float
    avg_r_gross: float
    avg_r_net: float
    t_stat: float
    pf: float
    max_dd: float
    net: float
    gross: float

    def line(self) -> str:
        if self.n == 0:
            return "n=0"
        pf = "inf" if math.isinf(self.pf) else f"{self.pf:.2f}"
        return (f"n={self.n} win={self.win * 100:.0f}% avgR gross {self.avg_r_gross:+.2f} net {self.avg_r_net:+.2f} "
                f"(t={self.t_stat:+.2f}) PF={pf} maxDD={self.max_dd:,.0f} net={self.net:,.0f}/lot")


def net_points(t, mintick: float) -> float:
    return t.pnl - (COMM_SIDE * 2 * t.entry + 2 * SLIP_TICKS * mintick)


def summarize(trades, mintick: float, point_value: float) -> Summary:
    """Legacy v1 summary (kept for exact reproduction of Phases 2-3)."""
    n = len(trades)
    if n == 0:
        return Summary(0, 0, 0, 0, 0, 0, 0, 0, 0)
    eq = peak = dd = gw = gl = gross = 0.0
    wins = 0
    rs, rg = [], []
    for t in trades:
        net = net_points(t, mintick)
        inr = net * point_value
        gross += t.pnl * point_value
        eq += inr
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
        if inr > 0:
            gw += inr
            wins += 1
        else:
            gl -= inr
        rs.append(net / t.R)
        rg.append(t.pnl / t.R)
    mean = sum(rs) / n
    var = sum((x - mean) ** 2 for x in rs) / (n - 1) if n > 1 else 0.0
    t_stat = mean / math.sqrt(var / n) if var > 0 else 0.0
    return Summary(n, wins / n, sum(rg) / n, mean, t_stat, gw / gl if gl > 0 else math.inf, dd, eq, gross)


# ----------------------------------------------------------------------------- v2 cost model
@dataclass(frozen=True)
class CostModel:
    mode: str = "dated"            # "dated" or "current"
    lot_units: int = 65            # NIFTY 65, BANKNIFTY 30 (current lot sizes; costs are per unit, so lot-neutral)
    lots: int = 10                 # lots per trade: 40/30/30 needs >= 10 lots; single-exit systems use 1
    friction_pts_per_side: float = 0.4   # spread + slippage per side in index points (4 ticks of 0.1 on NIFTY)
    brokerage_per_order: float = 20.0

    def points(self, t) -> float:
        when = costs.CURRENT if self.mode == "current" else _trade_date(t)
        avg_exit = t.entry + (t.pnl if t.side in ("L", 1) else -t.pnl)
        side = 1 if t.side in ("L", 1) else -1
        return costs.futures_cost_points(t.entry, avg_exit, side, when, self.lot_units, self.lots,
                                         getattr(t, "orders", 2), self.friction_pts_per_side, self.brokerage_per_order)


def _trade_date(t) -> date:
    et = getattr(t, "entry_time", None)
    if et is None:
        return costs.CURRENT
    return et.date() if hasattr(et, "date") else et


def _t_quantile(df: int, p: float = 0.975) -> float:
    try:
        from scipy.stats import t as student
        return float(student.ppf(p, df))
    except ImportError:          # normal approximation, slightly too narrow for small samples
        return 1.959963984540054


def _t_pvalue(tstat: float, df: int) -> float:
    try:
        from scipy.stats import t as student
        return float(2 * student.sf(abs(tstat), df))
    except ImportError:
        return math.erfc(abs(tstat) / math.sqrt(2))


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    if n == 0:
        return (math.nan, math.nan)
    try:
        from scipy.stats import beta
        lo = 0.0 if k == 0 else float(beta.ppf(alpha / 2, k, n - k + 1))
        hi = 1.0 if k == n else float(beta.ppf(1 - alpha / 2, k + 1, n - k))
        return lo, hi
    except ImportError:
        p = k / n
        h = 1.96 * math.sqrt(p * (1 - p) / n)
        return max(0.0, p - h), min(1.0, p + h)


def block_bootstrap_mean(values: list[float], keys: list, b: int = 5000, seed: int = 7) -> tuple[float, float]:
    """95% interval of the per-trade mean, resampling whole blocks (all trades sharing a key, e.g. a day)."""
    if not values:
        return (math.nan, math.nan)
    blocks: dict = {}
    for v, k in zip(values, keys):
        blocks.setdefault(k, []).append(v)
    groups = list(blocks.values())
    rnd = random.Random(seed)
    means = []
    for _ in range(b):
        s = cnt = 0
        for _ in range(len(groups)):
            g = groups[rnd.randrange(len(groups))]
            s += sum(g)
            cnt += len(g)
        means.append(s / cnt)
    means.sort()
    return means[int(0.025 * b)], means[int(0.975 * b) - 1]


def holm(pvalues: dict[str, float], alpha: float = 0.05) -> dict[str, bool]:
    """Holm step-down: which hypotheses are rejected at family-wise level alpha."""
    order = sorted(pvalues, key=pvalues.get)
    m = len(order)
    out, still = {}, True
    for i, k in enumerate(order):
        still = still and pvalues[k] <= alpha / (m - i)
        out[k] = still
    return out


def report(trades, cm: CostModel, point_value: float | None = None) -> dict:
    """Full v2 summary of a trade list under a cost model. All money figures per lot.
    UNRESOLVED trades (exit "U": the data ended with a position open) are excluded and counted separately."""
    unresolved = sum(1 for t in trades if getattr(t, "exit", "") == "U")
    trades = [t for t in trades if getattr(t, "exit", "") != "U"]
    n = len(trades)
    pv = point_value or cm.lot_units
    if n == 0:
        return {"n": 0, "unresolved": unresolved}
    gross_r = [t.pnl / t.R for t in trades]
    net_pts = [t.pnl - cm.points(t) for t in trades]
    net_r = [p / t.R for p, t in zip(net_pts, trades)]
    mean = sum(net_r) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in net_r) / (n - 1)) if n > 1 else 0.0
    tstat = mean / (sd / math.sqrt(n)) if sd > 0 else 0.0
    q = _t_quantile(max(n - 1, 1))
    eq = peak = dd = gw = gl = 0.0
    for p in net_pts:
        inr = p * pv
        eq += inr
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
        if inr > 0:
            gw += inr
        else:
            gl -= inr
    wins = sum(p > 0 for p in net_pts)
    days = [_trade_date(t) for t in trades]
    weeks = [(d.isocalendar()[0], d.isocalendar()[1]) for d in days]
    return {
        "n": n, "unresolved": unresolved, "days": len(set(days)), "win": wins / n, "win_ci": clopper_pearson(wins, n),
        "gross_r": sum(gross_r) / n, "net_r": mean, "sd_r": sd, "t": tstat, "p": _t_pvalue(tstat, max(n - 1, 1)),
        "ci_t": (mean - q * sd / math.sqrt(n), mean + q * sd / math.sqrt(n)) if n > 1 else (math.nan, math.nan),
        "ci_day": block_bootstrap_mean(net_r, days), "ci_week": block_bootstrap_mean(net_r, weeks),
        "cost_r": (sum(gross_r) - sum(net_r)) / n, "pf": gw / gl if gl > 0 else math.inf,
        "max_dd_closed": dd, "net_inr": eq, "gross_pts": sum(t.pnl for t in trades) / n,
        "net_pts": sum(net_pts) / n,
    }


def mtm_drawdown(equity_points: list[float], point_value: float) -> float:
    """Maximum drawdown of a mark-to-market equity curve (gross points per unit -> rupees per lot)."""
    peak = dd = 0.0
    for e in equity_points:
        peak = max(peak, e)
        dd = max(dd, peak - e)
    return dd * point_value


def fmt(r: dict) -> str:
    if not r or r.get("n", 0) == 0:
        return "n=0"
    pf = "inf" if math.isinf(r["pf"]) else f"{r['pf']:.2f}"
    return (f"n={r['n']} ({r['days']} days) win={r['win'] * 100:.0f}% [{r['win_ci'][0] * 100:.0f}-{r['win_ci'][1] * 100:.0f}] "
            f"grossR {r['gross_r']:+.3f} costR {r['cost_r']:.3f} netR {r['net_r']:+.3f} "
            f"t={r['t']:+.2f} p={r['p']:.3f} CI(t) [{r['ci_t'][0]:+.2f},{r['ci_t'][1]:+.2f}] "
            f"CI(day-block) [{r['ci_day'][0]:+.2f},{r['ci_day'][1]:+.2f}] PF={pf} net ₹{r['net_inr']:,.0f}/lot")


def bootstrap_ci(values, b: int = 5000, seed: int = 7) -> tuple[float, float]:
    """95% IID bootstrap interval of the mean (kept for backward compatibility; prefer block_bootstrap_mean)."""
    return block_bootstrap_mean(list(values), list(range(len(values))), b, seed)
