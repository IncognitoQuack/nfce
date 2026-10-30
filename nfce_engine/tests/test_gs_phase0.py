"""GS phase 0: review A's findings that are diagnostics, not scorer fixes (tools/gs_phase0_checks.py). Synthetic data."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import gs_phase0_checks as g  # noqa: E402

TZ = "Asia/Kolkata"


def bars(day, n):
    idx = pd.date_range(f"{day} 09:15", periods=n, freq="3min", tz=TZ)
    v = np.full(n, 100.0)
    return pd.DataFrame({"open": v, "high": v, "low": v, "close": v, "volume": v}, index=idx)


def test_frame_exclusions_finds_days_dropped_by_the_whole_session_count():
    b = pd.concat([bars("2025-01-02", 125), bars("2025-01-03", 40), bars("2024-03-02", 30)])
    r = g.frame_exclusions(b, 3)
    # 3 Jan (a regular session cut short after 40 bars) had its opening range at 09:21: a live system could trade it
    assert r["days"] == 3 and r["dropped"] == 2 and r["dropped_with_opening_range"] == 2
    assert r["dropped_regular_with_opening_range"] == 1 and r["examples"] == ["2025-01-03"]   # 2 Mar 2024 = DR drill
