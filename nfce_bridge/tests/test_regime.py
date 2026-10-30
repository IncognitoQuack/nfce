"""Regime labels: declared thresholds, causal inputs, unknown rather than wrong when an input is missing."""
from bridge import regime as rg

HIST = tuple(float(x) for x in range(10, 30))          # 20 closes: 10 … 29


def test_volatility_label_from_percentile_and_day_jump():
    assert rg.classify(28.0, 0.0, 0.0, 0.5, HIST)["vol"] == "stressed"      # pct 0.95
    assert rg.classify(12.0, 0.0, 0.0, 0.5, HIST)["vol"] == "calm"          # pct 0.15
    assert rg.classify(18.0, 0.0, 0.0, 0.5, HIST)["vol"] == "normal"        # pct 0.45
    assert rg.classify(18.0, 9.0, 0.0, 0.5, HIST)["vol"] == "stressed"      # VIX +9% on the day
    assert rg.classify(None, None, 0.0, 0.5, HIST)["vol"] is None


def test_direction_label_needs_move_and_breadth():
    assert rg.classify(18.0, 0.0, 0.7, 0.65, HIST)["trend"] == "trend up"
    assert rg.classify(18.0, 0.0, 0.7, 0.50, HIST)["trend"] == "mixed"      # index up, breadth does not confirm
    assert rg.classify(18.0, 0.0, -0.9, 0.30, HIST)["trend"] == "trend down"
    assert rg.classify(18.0, 0.0, 0.9, None, HIST)["trend"] == "trend up"   # no breadth: the move alone, ±0.8%
    assert rg.classify(18.0, 0.0, None, 0.7, HIST)["trend"] is None
    assert rg.classify(None, None, None, None, HIST)["text"] == "unknown"
