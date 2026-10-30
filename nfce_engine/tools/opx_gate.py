"""OPX-1: the range-gated overnight NIFTY iron fly (../evidence/opx_1_protocol.md, SHA-256 93c3dd74…8386;
amendment 1 `opx_1_amendment_1.md`: the gate is n/a when OVN v2 forms no structure).

  ../nfce_bridge/.venv/bin/python tools/opx_gate.py            # session table + pilot report so far

OPX-1 = OVN v2 (`overnight_options.py score2`, unchanged and only imported here) taken only on nights when the implied
volatility of its ATM straddle is at least 1.50 × the range model's forecast volatility for that session.
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import overnight_options as ovn  # noqa: E402

START = date(2026, 10, 27)
THRESHOLD = 1.50
PILOT_SESSIONS = 60
RANGE_PER_SIGMA = math.sqrt(8 / math.pi)                # 1.596: E[high - low] of a Brownian path per sigma*sqrt(T)
ANNUAL = math.sqrt(252 * 6.25)                          # trading hours in a year, square-rooted
NFCE_DB = ovn.ROOT / "nfce_bridge" / "data" / "nfce.db"


def forecast_vol(con: sqlite3.Connection, d: date, model: str = "ENS", root: str = "NIFTY") -> tuple | None:
    """(F, sigma_ann%): F = the mean of exp(q50) over d's forecasts (all made by 14:15, before the 15:20 entry)."""
    rows = [r[0] for r in con.execute("SELECT q50 FROM range_forecasts WHERE root=? AND model=? AND bar_close LIKE ?",
                                      (root, model, f"{d.isoformat()}%")) if r[0] is not None]
    if not rows:
        return None
    f = float(np.mean(np.exp(rows)))
    return f, f / RANGE_PER_SIGMA * ANNUAL * 100


def entry_iv(chain: pd.DataFrame, expiry: str, k: float) -> float | None:
    """Mean IV of the K call and K put in the OVN v2 entry snapshot (the first in [15:20:00, 15:21:00))."""
    snaps = ovn.snapshots(chain, ovn.V2_ENTRY, ovn.V2_CANCEL)
    if not snaps:
        return None
    s = snaps[0]
    legs = s[(s["expiry"] == expiry) & (s["strike"] == k)]
    ivs = [float(x) for x in legs["iv"] if x is not None and not pd.isna(x) and x > 0]
    return float(np.mean(ivs)) if len(ivs) == 2 else None


def gate(fv: tuple | None, iv: float | None, threshold: float = THRESHOLD) -> dict:
    if fv is None or iv is None:
        return {"gate": "unknown", "ratio": None}
    ratio = iv / fv[1]
    return {"gate": "on" if ratio >= threshold else "off", "ratio": ratio, "iv": iv, "forecast_range": fv[0],
            "forecast_vol": fv[1]}


def gated_units(row: dict, g: dict) -> dict:
    """u_opx and its widened twin for one session (protocol 'Series')."""
    out = {"u_opx": 0.0, "u_opx_widened": 0.0}
    if g["gate"] != "on":
        return out
    if row.get("status") == "ok":
        out["u_opx"], out["u_opx_widened"] = row.get("units", 0.0), row.get("units_widened", 0.0)
    elif str(row.get("status", "")).startswith("unresolved"):
        out |= {"u_opx": math.nan, "u_opx_worst": row.get("units_worst"), "u_opx_best": row.get("units_best")}
    return out


def score_opx(data: Path = ovn.DATA, db: Path = NFCE_DB, start: date = START) -> pd.DataFrame:
    v2 = ovn.score_v2(data, start=start)
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = []
    for r in v2.to_dict("records"):
        d = date.fromisoformat(r["day"])
        f = data / f"study_chain_{d:%Y%m%d}.db"
        has_structure = r.get("atm") is not None and not pd.isna(r.get("atm")) and bool(r.get("expiry"))
        if not has_structure:                    # amendment 1: OVN v2 formed no structure, so the gate is n/a
            g = {"gate": "n/a", "ratio": None}
        elif not f.exists():
            g = {"gate": "unknown", "ratio": None}
        else:
            g = gate(forecast_vol(con, d), entry_iv(ovn.read_chain2(f), r["expiry"], float(r["atm"])))
        rows.append(r | g | gated_units(r, g))
    con.close()
    return pd.DataFrame(rows)


def pilot_report(t: pd.DataFrame) -> dict:
    entered = t[t["status"] == "ok"]
    on, off = entered[entered["gate"] == "on"], entered[entered["gate"] == "off"]
    rep = {"sessions": int(len(t)), "gate_on": int((t["gate"] == "on").sum()), "gate_off": int((t["gate"] == "off").sum()),
           "gate_unknown": int((t["gate"] == "unknown").sum()), "gate_na_no_structure": int((t["gate"] == "n/a").sum()),
           "ovn_entered": int(len(entered)),
           "opx_entered": int(len(on)), "net_opx_rs": float((on["units"] * ovn.BOOK * ovn.BUDGET_PCT).sum()),
           "net_ovn_rs": float((entered["units"] * ovn.BOOK * ovn.BUDGET_PCT).sum()),
           "mean_u_gate_on": float(on["units"].mean()) if len(on) else None,
           "mean_u_gate_off": float(off["units"].mean()) if len(off) else None}
    if len(t) >= PILOT_SESSIONS:
        from gs import evaluate
        best = t["u_opx"].where(t["u_opx"].notna(), t.get("u_opx_best", pd.Series(0.0, index=t.index))).fillna(0.0)
        dec = evaluate.pilot_decision(best.iloc[:PILOT_SESSIONS].to_numpy(), delta=0.05, n_expected=PILOT_SESSIONS)
        rep["pilot_decision"] = {"status": dec.status, "reasons": list(dec.reasons), "stats": dec.stats}
    return rep


if __name__ == "__main__":
    t = score_opx()
    cols = [c for c in ("day", "status", "atm", "expiry", "iv", "forecast_vol", "ratio", "gate", "units", "u_opx") if c in t]
    print(t[cols].to_string(index=False))
    print(json.dumps(pilot_report(t), indent=1, default=str))
