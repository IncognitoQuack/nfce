"""Evidence cards: what is actually known about signals like this one.

Every signal gets the measured, OUT-OF-SAMPLE record of its class (evidence_table.json, built by
nfce_engine/tools/build_evidence.py), the live cost share of its risk, and a trust label from a rule fixed in advance.
Index signals (NIFTY, BANKNIFTY) use index-futures evidence only: the TradingView v2 runs at current costs, by entry
window. Stock signals use the 504-trade hold-out simulation cells. Trust labels:

  VALIDATED        the class passed a registered experiment (REGISTRY.md). Listed in validated_classes; empty until then.
  LEAD (unproven)  the class has a real edge BEFORE costs (gross >= +0.10R, >= 30 trades) and its after-cost interval
                   still reaches above zero. Worth paper-testing; not shown to make money.
  NO EDGE          everything else, and any signal whose costs eat half or more of its risk.

The label is about evidence, not about the chain check (PASS/VETO) and not a recommendation.
"""
from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .costs import futures_cost_points
from .paper import LOT, PAPER_LOTS, TICK, THEO_FRICTION_TICKS
from .providers import IST

TABLE = Path(__file__).with_name("evidence_table.json")
VALIDATED, LEAD, NO_EDGE = "VALIDATED", "LEAD (unproven)", "NO EDGE"
EMOJI = {VALIDATED: "🟢", LEAD: "🟠", NO_EDGE: "🔴"}
LEAD_MIN_GROSS = 0.10
MAX_COST_SHARE = 0.5
MORNING_END = 11 * 60 + 15


def load_table(path: Path = TABLE) -> dict:
    return json.loads(path.read_text())


def window_of(bar_close: datetime) -> str:
    t = bar_close.astimezone(IST)
    return "morning" if t.hour * 60 + t.minute <= MORNING_END else "later"


def cost_bucket(share: float) -> str:
    return "low" if share < 0.15 else "mid" if share <= 0.30 else "high"


def cost_share(entry: float, sl: float, side: int, root: str, when: datetime, lots: int = PAPER_LOTS) -> float:
    """Round-trip fees + friction of the paper position (whole lots, 40/30/30 = 4 orders), as a share of the risk R."""
    r = abs(entry - sl)
    if r <= 0:
        return math.inf
    pts = futures_cost_points(entry, entry, side, when.astimezone(IST).date(), LOT.get(root, 1), lots, 4,
                              THEO_FRICTION_TICKS * TICK.get(root, 0.1))
    return pts / r


def lookup(table: dict, window: str, cost: str, kind: str) -> tuple[str, dict, str]:
    """Most specific cell with enough trades; says when it had to fall back."""
    cells, note = table["cells"], ""
    for key in (f"{window}|{cost}|{kind}", f"{window}|{cost}|all", f"{window}|all|all", "all|all|all"):
        c = cells.get(key)
        if c and c.get("n", 0) and not c.get("thin"):
            return key, c, note
        if c and c.get("n", 0) and not note:
            note = f"only {c['n']} trades like this exactly ({key}); using the broader class"
    return "all|all|all", cells["all|all|all"], note


@dataclass
class Card:
    trust: str
    key: str
    cell: dict
    cost_share: float
    window: str
    note: str = ""
    reasons: list[str] = field(default_factory=list)

    def headline(self) -> str:
        return f"{EMOJI[self.trust]} {self.trust}"

    def lines(self, tv: dict | None = None) -> list[str]:
        c = self.cell
        ci = c.get("ci") or [math.nan, math.nan]
        out = [f"Evidence ({self.key.replace('|', ' / ')}, unseen sessions): n={c['n']} trades, "
               f"{c['win'] * 100:.0f}% winners, before costs {c['gross_r']:+.2f}R, after costs {c['net_r']:+.2f}R "
               f"[95% {ci[0]:+.2f}..{ci[1]:+.2f}]",
               f"Costs for this signal: {self.cost_share * 100:.0f}% of its risk ({self.window} entry)"]
        if self.note:
            out.append(f"Note: {self.note}")
        if tv and not self.key.startswith("index futures"):
            out.append(f"TradingView futures record: n={tv['n']}, after costs {tv['net_r']:+.2f}R per trade")
        out += [f"Why {self.trust}: {r}" for r in self.reasons]
        return out


def lookup_index(table: dict, window: str) -> tuple[str, dict, str]:
    """FIX (review round 3, M11): index signals are judged on index-FUTURES evidence only (TradingView v2 runs, current
    costs). Stock trades never stand in for an index; the hold-out's few index trades are reported, not pooled."""
    ic = table.get("index_cells") or {}
    n_hold = sum(c.get("n", 0) for k, c in table["cells"].items() if k.endswith("|index"))
    note = f"index futures only; the hold-out simulation had just {n_hold} index trades, so it is not used"
    c = ic.get(f"tv|{window}")
    if c and c.get("n") and not c.get("thin"):
        return f"index futures|{window}|current costs", c, note
    if ic.get("tv|all"):
        return "index futures|all|current costs", ic["tv|all"], note
    return "all|all|all", table["cells"]["all|all|all"], "no index-only evidence in this table; pooled class used"


def assess(table: dict, sig, root: str, bar_close: datetime, when: datetime) -> Card:
    side = 1 if sig.side == "BUY" else -1
    share = cost_share(sig.entry, sig.sl, side, root, when)
    window = window_of(bar_close)
    kind = "index" if root in LOT else "stock"
    if kind == "index" and table.get("index_cells"):
        key, cell, note = lookup_index(table, window)
        if root not in ("NIFTY", "BANKNIFTY"):
            note = (f"no {root} trades have been tested; this is the NIFTY/BANKNIFTY futures record, the closest evidence"
                    f" (untested on {root})")
    else:
        key, cell, note = lookup(table, window, cost_bucket(share), kind)
    ci = cell.get("ci")
    reasons = []
    if key in table.get("validated_classes", []):
        trust = VALIDATED
        reasons.append("this class passed a registered live experiment")
    elif cell["gross_r"] >= LEAD_MIN_GROSS and ci is not None and ci[1] > 0:
        trust = LEAD
        reasons.append(f"signals like this had an edge before costs ({cell['gross_r']:+.2f}R) but are not shown "
                       f"profitable after costs")
    else:
        trust = NO_EDGE
        reasons.append("after costs, signals like this lost money on unseen data"
                       if ci is not None and ci[1] < 0 else "no meaningful edge even before costs")
    if share >= MAX_COST_SHARE:
        trust = NO_EDGE
        reasons.append(f"and for THIS signal costs eat {share * 100:.0f}% of the risk: the stop is too tight for "
                       f"futures costs")
    return Card(trust, key, cell, share, window, note, reasons)


def drift(ref: dict, live_r: list[float], min_n: int = 20) -> str | None:
    """Compare live (paper) results with the tested reference; None when too few trades or inside the band."""
    n = len(live_r)
    if n < min_n:
        return None
    m, sd = statistics.fmean(live_r), statistics.stdev(live_r)
    half = 1.96 * sd / math.sqrt(n)
    if m + half < ref["net_r"]:
        return (f"⚠️ Live results are WORSE than tested: {m:+.2f}R per trade over {n} trades "
                f"[95% {m - half:+.2f}..{m + half:+.2f}] vs {ref['net_r']:+.2f}R in testing. Check data, fills and costs.")
    if m - half > ref["net_r"]:
        return (f"Live results are better than tested: {m:+.2f}R per trade over {n} trades vs {ref['net_r']:+.2f}R. "
                f"This could be luck; judge only by the registered experiments.")
    return None
