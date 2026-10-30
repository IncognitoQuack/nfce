import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce.simple import momentum, orb, stats  # noqa: E402

HOURS = ["09:15", "10:15", "11:15", "12:15", "13:15", "14:15", "15:15"]


def day(date, bars):
    """bars: list of (open, high, low, close) for the 7 hourly bars."""
    idx = [pd.Timestamp(f"{date} {h}", tz="Asia/Kolkata") for h in HOURS]
    return pd.DataFrame(bars, columns=["open", "high", "low", "close"], index=idx)


def test_orb_long_to_eod():
    d = day("2026-10-12", [(100, 110, 95, 105), (105, 112, 104, 111), (111, 115, 109, 114),
                           (114, 116, 112, 115), (115, 117, 113, 116), (116, 118, 114, 117), (117, 120, 116, 119)])
    (t,) = orb(d)
    assert t.side == 1 and t.entry == 111 and t.exit == 119 and t.reason == "eod" and t.risk == 16


def test_orb_stop_with_gap_fill_and_mid_variant():
    d = day("2026-10-13", [(100, 110, 90, 100), (100, 101, 85, 88), (80, 82, 78, 79), (79, 80, 70, 72),
                           (72, 75, 70, 74), (74, 76, 73, 75), (75, 76, 74, 75)])
    (t,) = orb(d)                                         # short at 88, stop at range high 110
    assert t.side == -1 and t.entry == 88 and t.reason == "eod" and t.exit == 75
    d2 = day("2026-10-14", [(100, 110, 90, 100), (100, 101, 85, 88), (99, 102, 97, 101), (101, 103, 99, 100),
                            (100, 101, 99, 100), (100, 101, 99, 100), (100, 101, 99, 100)])
    (t2,) = orb(d2, stop="mid")                           # stop at midpoint 100; next bar opens 99 then trades 102
    assert t2.reason == "stop" and t2.exit == 100
    d3 = day("2026-10-15", [(100, 110, 90, 100), (100, 101, 85, 88), (104, 106, 103, 105), (105, 106, 104, 105),
                            (105, 106, 104, 105), (105, 106, 104, 105), (105, 106, 104, 105)])
    (t3,) = orb(d3, stop="mid")                           # gap above the stop -> filled at the open (104), not 100
    assert t3.exit == 104


def test_orb_no_trade_inside_range_or_late():
    flat = [(100, 110, 90, 100)] + [(100, 105, 95, 100)] * 4 + [(100, 120, 99, 115), (115, 116, 114, 115)]
    assert orb(day("2026-10-16", flat)) == []             # breakout only on the 14:15 bar = too late


def test_momentum_direction_and_big_filter():
    days = []
    for k, dt in enumerate(pd.bdate_range("2026-01-01", periods=70)):
        up = k % 2 == 0
        first_close = 101 if up else 99
        days.append(day(dt.date(), [(100, 102, 98, first_close)] + [(100, 101, 99, 100)] * 4
                        + [(100, 101, 99, 100), (100, 103, 99, 102 if up else 98)]))
    trades = momentum(pd.concat(days))
    assert len(trades) == 69                              # first day has no previous close
    assert all(t.pnl == 2 for t in trades)                # direction always right in this construction
    assert len(momentum(pd.concat(days), "big")) < len(trades)


def test_missing_close_bar_is_not_dropped_after_the_fact():
    """Review: dropping a day because its 15:15 bar is missing uses information from the future."""
    bars = [(100, 110, 95, 105), (105, 112, 104, 111), (111, 115, 109, 114), (114, 116, 112, 115)]
    d = day("2026-10-12", bars + [(115, 117, 113, 116), (116, 118, 114, 117), (117, 120, 116, 119)]).iloc[:5]
    (t,) = orb(d)
    assert t.reason == "eod_incomplete" and t.exit == 116 and stats([t], 65, 0.1)["incomplete"] == 1


def test_momentum_needs_a_complete_previous_session():
    full = [(100, 102, 98, 101)] + [(100, 101, 99, 100)] * 5 + [(100, 103, 99, 102)]
    d1 = day("2026-01-05", full).iloc[:-1]                      # previous session missing its 15:15 bar
    d2 = day("2026-01-06", full)
    assert momentum(pd.concat([d1, d2])) == []


def _ha_days(n=25, rng_pts=80.0, vol=1000.0, last_vol=3000.0, break_px=None):
    out = []
    for k, dt in enumerate(pd.bdate_range("2026-01-01", periods=n)):
        base = 25000.0
        idx = [pd.Timestamp(f"{dt.date()} {h:02d}:{m:02d}", tz="Asia/Kolkata")
               for h in range(9, 16) for m in (0, 15, 30, 45) if (9, 15) <= (h, m) <= (15, 15)]
        rows = []
        for t in idx:
            hhmm = t.strftime("%H:%M")
            if hhmm == "09:15":
                rows.append((base, base + rng_pts / 2, base - rng_pts / 2, base, last_vol if k == n - 1 else vol))
            elif hhmm == "09:30" and k == n - 1 and break_px:
                rows.append((base, break_px + 5, base - 5, break_px, vol))
            else:
                rows.append((base, base + 300 if k < n - 1 else base + 10, base - 300 if k < n - 1 else base - 10, base, vol))
        out.append(pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx))
    return pd.concat(out)


def test_ha_rules_gate_entry_stop_and_target():
    from nfce.simple import orb15_ha
    # daily ATR ~ 600 (high-low of each history day); 0.25*600=150 <= range <= 360 required: 80 is too narrow
    assert orb15_ha(_ha_days(rng_pts=80, break_px=25100)) == []
    t = orb15_ha(_ha_days(rng_pts=200, break_px=25150))
    assert len(t) == 1 and t[0].side == 1 and t[0].risk == pytest.approx(25150 - 24900)
    assert orb15_ha(_ha_days(rng_pts=200, break_px=25150, last_vol=1000)) == []   # volume gate: needs 1.5x median


def test_ha_volume_gate_cannot_pass_vacuously_on_bars_without_volume():
    """0 >= 1.5 x median(0) was True: on spot index bars (no volume) the pre-registered gate silently vanished."""
    from nfce.simple import orb15_ha
    with pytest.raises(ValueError, match="volume"):
        orb15_ha(_ha_days(rng_pts=200, break_px=25150, vol=0.0, last_vol=0.0))
    d = _ha_days(rng_pts=200, break_px=25150)
    d.iloc[: 25 * 21, d.columns.get_loc("volume")] = 0.0        # 21 sessions (25 bars each) without volume, then data
    assert orb15_ha(d) == []                                     # median of the last 20 is 0: the gate is not met


def test_stats_costs():
    d = day("2026-10-12", [(100, 110, 95, 105), (105, 112, 104, 111), (111, 115, 109, 114),
                           (114, 116, 112, 115), (115, 117, 113, 116), (116, 118, 114, 117), (117, 120, 116, 119)])
    s = stats(orb(d), point_value=65, mintick=0.05)
    assert s["n"] == 1 and s["gross_pts"] == 8
    assert s["cost_pts"] == pytest.approx(0.0003 * 2 * 111 + 8 * 0.05)
