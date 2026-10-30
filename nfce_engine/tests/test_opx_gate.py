"""OPX-1 gate: causal forecast volatility, entry-snapshot IV, the 1.50 threshold, and the gated series."""
import math
import sqlite3
from datetime import date

import numpy as np
import pandas as pd
import pytest

from tools import opx_gate as og


def _db(tmp_path, q50s, day="2026-10-27"):
    con = sqlite3.connect(tmp_path / "f.db")
    con.execute("CREATE TABLE range_forecasts (root TEXT, bar_close TEXT, model TEXT, ts TEXT, price REAL, q10 REAL, "
                "q50 REAL, q90 REAL, realized REAL)")
    for i, q in enumerate(q50s):
        con.execute("INSERT INTO range_forecasts VALUES ('NIFTY', ?, 'ENS', '', 0, 0, ?, 0, 0)",
                    (f"{day}T{9 + i // 4:02d}:{(i % 4) * 15:02d}:00+05:30", q))
        con.execute("INSERT INTO range_forecasts VALUES ('NIFTY', ?, 'M1', '', 0, 0, -1.0, 0, 0)",   # other models ignored
                    (f"{day}T{9 + i // 4:02d}:{(i % 4) * 15:02d}:00+05:30",))
    con.commit()
    return con


def test_forecast_vol_uses_only_ens_rows_of_that_day(tmp_path):
    con = _db(tmp_path, [math.log(0.0045)] * 4)
    f, sig = og.forecast_vol(con, date(2026, 10, 27))
    assert f == pytest.approx(0.0045)
    assert sig == pytest.approx(0.0045 / math.sqrt(8 / math.pi) * math.sqrt(252 * 6.25) * 100)   # ~11.2%
    assert og.forecast_vol(con, date(2026, 10, 28)) is None


def _chain(iv_c=16.0, iv_p=17.0, t="15:20:30"):
    rows = []
    for k in (22700.0, 22750.0, 22800.0):
        for typ, iv in (("CE", iv_c), ("PE", iv_p)):
            rows.append({"ts": f"2026-10-27T{t}", "time": t, "expiry": "2026-11-03", "strike": k, "typ": typ, "iv": iv})
    return pd.DataFrame(rows)


def test_entry_iv_from_the_entry_snapshot_only():
    assert og.entry_iv(_chain(), "2026-11-03", 22750.0) == 16.5
    assert og.entry_iv(_chain(t="15:22:00"), "2026-11-03", 22750.0) is None          # outside [15:20, 15:21)
    assert og.entry_iv(_chain(iv_p=0.0), "2026-11-03", 22750.0) is None              # a missing leg IV


def test_gate_threshold_and_unknown():
    fv = (0.0045, 11.0)
    assert og.gate(fv, 16.5)["gate"] == "on" and og.gate(fv, 16.4)["gate"] == "off"   # 16.5 / 11 = 1.50 exactly
    assert og.gate(None, 16.5)["gate"] == "unknown" and og.gate(fv, None)["gate"] == "unknown"


def test_gated_units_follow_ovn_only_when_on():
    ok = {"status": "ok", "units": -0.4, "units_widened": -0.5}
    assert og.gated_units(ok, {"gate": "on"}) == {"u_opx": -0.4, "u_opx_widened": -0.5}
    assert og.gated_units(ok, {"gate": "off"}) == {"u_opx": 0.0, "u_opx_widened": 0.0}
    un = og.gated_units({"status": "unresolved (open legs)", "units_worst": -1.0, "units_best": 0.3}, {"gate": "on"})
    assert math.isnan(un["u_opx"]) and un["u_opx_worst"] == -1.0 and un["u_opx_best"] == 0.3
    skip = og.gated_units({"status": "skip: VIX gate"}, {"gate": "on"})
    assert skip["u_opx"] == 0.0


def test_gate_is_na_when_ovn_forms_no_structure_and_unknown_when_data_is_missing(tmp_path, monkeypatch):
    rows = pd.DataFrame([{"day": "2026-10-27", "status": "skip: VIX gate", "units": 0.0, "covered": True},
                         {"day": "2026-10-28", "status": "ok", "units": 0.2, "atm": 22750.0, "expiry": "2026-11-03",
                          "covered": True}])
    monkeypatch.setattr(og.ovn, "score_v2", lambda *a, **k: rows)
    _db(tmp_path, [math.log(0.0045)] * 4, day="2026-10-28").close()
    t = og.score_opx(data=tmp_path, db=tmp_path / "f.db")
    assert t.loc[0, "gate"] == "n/a" and t.loc[0, "u_opx"] == 0.0            # amendment 1
    assert t.loc[1, "gate"] == "unknown" and t.loc[1, "u_opx"] == 0.0        # structure formed, chain file missing
    assert og.pilot_report(t)["gate_na_no_structure"] == 1


def test_pilot_report_counts_and_decision_after_60():
    t = pd.DataFrame({"status": ["ok"] * 60, "gate": ["on", "off"] * 30, "units": np.r_[[0.1] * 60],
                      "u_opx": [0.1, 0.0] * 30})
    rep = og.pilot_report(t)
    assert rep["opx_entered"] == 30 and rep["ovn_entered"] == 60 and rep["net_opx_rs"] == pytest.approx(30 * 500)
    assert rep["pilot_decision"]["status"] in ("CONTINUE", "INFEASIBLE")
