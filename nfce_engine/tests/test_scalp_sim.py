"""SCALP-1 simulator: every rule of the protocol on small synthetic tick sequences."""
import json

import pandas as pd
import pytest

from tools import scalp_sim as ss

BUY_BOOK = [(999.9, 9000, 1000.0, 1000), (999.8, 5000, 1000.1, 1000), (999.7, 5000, 1000.2, 1000),
            (999.6, 5000, 1000.3, 1000), (999.5, 5000, 1000.4, 1000)]          # I1 = 0.8, I25 = 0.67: a long signal
FLAT_BOOK = [(999.9, 1000, 1000.0, 1000)] * 5


def ticks(rows):
    """rows: (HH:MM:SS, key, ltp, bid, ask, depth)."""
    out = [{"recv_ts": f"2026-10-28T{t}.000+05:30", "key": k, "ltp": ltp, "bid1": b, "bidq1": d[0][1], "ask1": a,
            "askq1": d[0][3], "depth": json.dumps(d), "vtt": 1e6} for t, k, ltp, b, a, d in rows]
    f = pd.DataFrame(out)
    f["t"] = pd.to_datetime(f["recv_ts"], format="ISO8601")
    f["hms"] = f["t"].dt.strftime("%H:%M:%S")
    return f


def test_imbalance_levels():
    i1, i25 = ss.imbalance(BUY_BOOK)
    assert i1 == pytest.approx(0.8) and i25 == pytest.approx(4 / 6)
    import math
    assert all(math.isnan(x) for x in ss.imbalance([]))


def test_passive_entry_needs_a_strict_trade_through_then_target():
    t = ticks([("10:00:00", "A", 1000.0, 999.9, 1000.0, BUY_BOOK),       # signal: bid 999.9
               ("10:00:05", "A", 999.9, 999.9, 1000.0, FLAT_BOOK),         # trades AT the limit: not filled
               ("10:00:10", "A", 999.85, 999.8, 999.9, FLAT_BOOK),         # strictly below: filled at 999.9
               ("10:01:00", "A", 1001.2, 1001.1, 1001.2, FLAT_BOOK)])      # > 999.9 * 1.0012 = 1001.10: target
    tr, s = ss.simulate(t, ["A"])
    assert len(tr) == 1 and tr.iloc[0]["reason"] == "target"
    assert tr.iloc[0]["entry"] == 999.9 and tr.iloc[0]["exit"] == pytest.approx(999.9 * 1.0012)
    assert tr.iloc[0]["qty"] == int(500000 // 999.9) and tr.iloc[0]["fees"] > 0
    assert tr.iloc[0]["net"] == pytest.approx(tr.iloc[0]["gross"] - tr.iloc[0]["fees"])


def test_unfilled_order_is_cancelled_after_30s_at_no_cost():
    t = ticks([("10:00:00", "A", 1000.0, 999.9, 1000.0, BUY_BOOK),
               ("10:00:31", "A", 999.0, 998.9, 999.0, FLAT_BOOK)])          # 31 s later: expired before this tick
    tr, s = ss.simulate(t, ["A"])
    assert len(tr) == 0 and s["cancelled"] == 1 and s["fills"] == 0


def test_stop_exits_marketable_at_the_touch_before_any_target_check():
    t = ticks([("10:00:00", "A", 1000.0, 999.9, 1000.0, BUY_BOOK),
               ("10:00:05", "A", 999.8, 999.8, 999.9, FLAT_BOOK),          # filled at 999.9
               ("10:00:20", "A", 999.0, 999.0, 999.1, FLAT_BOOK)])          # bid <= 999.9 * (1 - 0.0008) = 999.10
    tr, _ = ss.simulate(t, ["A"])
    assert tr.iloc[0]["reason"] == "stop" and tr.iloc[0]["exit"] == 999.0 and tr.iloc[0]["net"] < 0


def test_time_stop_and_strict_target_variant():
    rows = [("10:00:00", "A", 1000.0, 999.9, 1000.0, BUY_BOOK),
            ("10:00:05", "A", 999.8, 999.8, 999.9, FLAT_BOOK),
            ("10:01:00", "A", 1001.12, 1001.1, 1001.15, FLAT_BOOK),         # through the target by less than a tick
            ("10:03:10", "A", 1000.2, 1000.1, 1000.2, FLAT_BOOK)]
    tr, _ = ss.simulate(ticks(rows), ["A"])
    assert tr.iloc[0]["reason"] == "target"
    tr2, _ = ss.simulate(ticks(rows), ["A"], ss.Params(strict=True))
    assert tr2.iloc[0]["reason"] == "time" and tr2.iloc[0]["exit"] == 1000.1    # 185 s after the fill, at the bid


def test_limits_max_open_cooldown_and_flat_time():
    rows = []
    for k in "ABC":                                                         # three signals at once: only 2 orders
        rows.append(("10:00:00", k, 1000.0, 999.9, 1000.0, BUY_BOOK))
    tr, s = ss.simulate(ticks(rows), list("ABC"))
    assert s["orders"] == 2
    late = ticks([("15:00:30", "A", 1000.0, 999.9, 1000.0, BUY_BOOK)])      # after 15:00: no entry
    assert ss.simulate(late, ["A"])[1]["orders"] == 0
    eod = ticks([("14:59:00", "A", 1000.0, 999.9, 1000.0, BUY_BOOK),
                 ("14:59:05", "A", 999.8, 999.8, 999.9, FLAT_BOOK),
                 ("15:10:00", "A", 999.95, 999.9, 1000.0, FLAT_BOOK)])
    assert ss.simulate(eod, ["A"])[0].iloc[0]["reason"] == "15:10 flat"


def test_universe_takes_tight_spreads_ranked_by_value():
    rows = [("09:20:00", "TIGHT", 1000.0, 999.9, 1000.1, FLAT_BOOK),        # 2 bp spread
            ("09:20:00", "WIDE", 1000.0, 999.0, 1001.0, FLAT_BOOK)]         # 20 bp spread: excluded
    assert ss.universe(ticks(rows)) == ["TIGHT"]
