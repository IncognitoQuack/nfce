"""Evidence cards: every signal carries the measured, out-of-sample record of signals like it, and an honest trust label."""
from datetime import datetime

import pytest

from bridge import costs
from bridge.evidence import (LEAD, NO_EDGE, VALIDATED, assess, cost_bucket, cost_share, drift, load_table, lookup,
                             window_of)
from bridge.providers import IST
from bridge.rules import Signal
from conftest import sig as payload


def sig(**k):
    return Signal.from_payload(payload(**k))

CELL = lambda n, gross, net, lo, hi: {"n": n, "win": 0.5, "gross_r": gross, "net_r": net, "ci": [lo, hi],  # noqa: E731
                                       "days": 10, "thin": n < 30}


def table(**cells):
    base = {"all|all|all": CELL(500, 0.15, -0.28, -0.41, -0.18), "morning|all|all": CELL(124, 0.21, -0.12, -0.36, 0.07),
            "later|all|all": CELL(380, 0.13, -0.34, -0.49, -0.21)}
    base.update({k.replace("__", "|"): v for k, v in cells.items()})
    return {"source": "test", "min_n": 30, "cells": base, "validated_classes": [],
            "tradingview_futures": CELL(94, 0.08, -0.17, -0.39, 0.04)}


def test_window_uses_the_signal_bar_close_time():
    assert window_of(datetime(2026, 10, 21, 11, 15, tzinfo=IST)) == "morning"
    assert window_of(datetime(2026, 10, 21, 11, 20, tzinfo=IST)) == "later"


def test_cost_share_uses_the_dated_fee_schedule_lot_and_friction():
    when = datetime(2026, 10, 21, 10, 0, tzinfo=IST)
    share = cost_share(25000.0, 24960.0, +1, "NIFTY", when)
    expected = costs.futures_cost_points(25000.0, 25000.0, 1, when.date(), 65, 10, 4, 4 * 0.1) / 40.0   # 10 lots, like the paper books
    assert share == pytest.approx(expected)
    assert cost_bucket(0.10) == "low" and cost_bucket(0.2) == "mid" and cost_bucket(0.31) == "high"


def test_thin_cells_fall_back_to_the_pooled_cell_and_say_so():
    t = table(morning__high__index=CELL(5, 0.5, 0.07, -0.9, 0.6), morning__high__all=CELL(55, 0.47, -0.04, -0.35, 0.26))
    key, cell, note = lookup(t, "morning", "high", "index")
    assert key == "morning|high|all" and cell["n"] == 55 and "only 5" in note


def test_trust_labels_follow_the_fixed_rule():
    t = table(morning__high__all=CELL(55, 0.47, -0.04, -0.35, 0.26), later__high__all=CELL(231, 0.21, -0.42, -0.62, -0.24))
    m = datetime(2026, 10, 21, 10, 0, tzinfo=IST)
    a = datetime(2026, 10, 21, 14, 0, tzinfo=IST)
    s = sig(entry=25000.0, sl=24900.0)              # R = 100 pts: costs ~16% of R ("mid"), no mid cell -> window cell
    card = assess(t, s, "NIFTY", m, m)
    assert card.key == "morning|all|all" and card.trust == LEAD         # gross edge, net interval reaches above 0
    assert assess(t, s, "NIFTY", a, a).trust == NO_EDGE                 # net interval entirely below 0
    t["validated_classes"] = ["morning|all|all"]
    assert assess(t, s, "NIFTY", m, m).trust == VALIDATED               # only after a registered experiment PASSES


def test_costs_above_half_the_risk_force_no_edge():
    t = table(morning__high__all=CELL(55, 0.47, -0.04, -0.35, 0.26))
    m = datetime(2026, 10, 21, 10, 0, tzinfo=IST)
    card = assess(t, sig(entry=25000.0, sl=24997.0), "NIFTY", m, m)     # R = 3 points: costs ~ several R
    assert card.trust == NO_EDGE and any("costs" in r for r in card.reasons)


def test_shipped_table_is_valid_and_validates_nothing_yet():
    t = load_table()
    assert t["validated_classes"] == [] and t["cells"]["all|all|all"]["n"] >= 500
    assert t["index_cells"]["tv|all"]["n"] == 94              # index signals: index-futures evidence only (M11)
    m = datetime(2026, 10, 21, 10, 0, tzinfo=IST)
    a = datetime(2026, 10, 21, 14, 0, tzinfo=IST)
    cm = assess(t, sig(entry=25000.0, sl=24960.0), "NIFTY", m, m)
    assert cm.trust == NO_EDGE and cm.key.startswith("index futures|morning")      # no edge even before costs
    ca = assess(t, sig(entry=25000.0, sl=24960.0), "NIFTY", a, a)
    assert ca.trust == NO_EDGE or "not shown profitable" in " ".join(ca.reasons)


def test_drift_flags_live_results_outside_the_tested_band():
    ref = CELL(94, 0.08, -0.17, -0.39, 0.04)
    assert drift(ref, [-0.2] * 5) is None                              # too few live trades to judge
    worse = drift(ref, [-1.0, -0.9, -1.1, -0.8, -1.0] * 5)
    assert worse and "WORSE" in worse
    better = drift(ref, [0.9, 1.0, 1.1, 0.8, 1.0] * 5)
    assert better and "better" in better and "luck" in better
    assert drift(ref, [-0.6, 0.3, -0.2, 0.1, -0.4] * 5) is None        # inside the band
