"""OVN v3: the overnight NIFTY iron fly centred on the put-call-parity forward (../evidence/overnight_options_v3_protocol.md,
SHA-256 41e4449d…4ff6). A new sample from 28 Oct 2026, alongside v2.

  ../nfce_bridge/.venv/bin/python tools/overnight_v3.py

v2 (`overnight_options.py`, frozen) is imported and left unchanged. `session_v3` and `score_v3` mirror `session_v2` and
`score_v2` line for line; the ONLY difference is rule 7: the reference price is the forward F, not the chain's spot.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import overnight_options as ovn  # noqa: E402
from tools.overnight_options import cal, instruments  # noqa: E402

V3_START = date(2026, 10, 28)


def parity_forward(snap: pd.DataFrame, expiry: str) -> float | None:
    """F = the median of k + mid(call) - mid(put) over the 3 listed strikes nearest the chain spot with valid quotes."""
    x = snap[snap["expiry"] == expiry]
    if x.empty:
        return None
    s = float(x["spot"].iloc[0])
    ks = np.unique(x["strike"].astype(float))
    near = ks[np.lexsort((ks, np.abs(ks - s)))][:3]
    fs = []
    for k in near:
        c, p = ovn.quote(snap, expiry, "CE", k), ovn.quote(snap, expiry, "PE", k)
        if ovn.valid(c) and ovn.valid(p):
            fs.append(k + (c["bid"] + c["ask"]) / 2 - (p["bid"] + p["ask"]) / 2)
    return float(np.median(fs)) if fs else None


def session_v3(d: date, entry_file: Path, later: list[tuple[date, Path]], atr: float, vix_mult: float,
               lot: int) -> dict:
    n = cal.next_session(d)
    ch = ovn.read_chain2(entry_file)
    snaps = ovn.snapshots(ch, ovn.V2_ENTRY, ovn.V2_CANCEL)
    if not snaps:
        return {"status": "no entry snapshot (15:20-15:21)", "covered": False}
    es = snaps[0]
    exp_d = cal.first_expiry_after(es["expiry"].unique(), n)
    if exp_d is None:
        return {"status": "no listed expiry after the next session", "covered": True}
    expiry = exp_d.isoformat()
    fwd = parity_forward(es, expiry)                                   # v3 rule 7
    chain_spot = float(es[es["expiry"] == expiry]["spot"].iloc[0]) if (es["expiry"] == expiry).any() else math.nan
    if fwd is None:
        return {"status": "no forward: not entered", "covered": True, "chain_spot": chain_spot}
    es = es.copy()
    es.loc[es["expiry"] == expiry, "spot"] = fwd
    st = ovn.pick_strikes(es, expiry, atr)
    if st is None:
        return {"status": "strikes not listed", "covered": True}
    legs_q = [((t, k, s), ovn.quote(es, expiry, t, k)) for t, k, s in ovn.v2_legs(st)]
    base = {"entry_ts": es["ts"].iloc[0], "exit_day": n.isoformat(), "expiry": expiry, "spot": st["spot"],
            "forward": fwd, "chain_spot": chain_spot, "atm": st["K"], "atr14": atr, "wing_target": st["target"],
            "Kc": st["Kc"], "Kp": st["Kp"], "Wc": st["Kc"] - st["K"], "Wp": st["K"] - st["Kp"], "covered": True}
    if not all(ovn.valid(q) for _, q in legs_q):
        return base | {"status": "no valid quote on a leg: not entered"}
    credit = sum(-s * ovn.fill2(q, s) for (_, _, s), q in legs_q)
    base["credit_pts"] = credit
    if not (0 < credit < min(base["Wc"], base["Wp"])):
        return base | {"status": "credit outside (0, width): not entered"}
    budget = ovn.BOOK * ovn.BUDGET_PCT * vix_mult
    lots, reserve, ef, xr = ovn.size_lots(legs_q, st, credit, lot, st["spot"], d, n, expiry, budget)
    base |= {"budget": budget, "reserve": reserve, "entry_fees": ef, "exit_fee_reserve": xr}
    if lots == 0:
        return base | {"status": "one lot exceeds the budget or visible size: not entered"}
    qty = lots * lot
    ex = ovn.close_legs(legs_q, later, expiry)
    exw = ovn.close_legs(legs_q, later, expiry, ovn.WIDEN)
    pin = [ovn.fill2(q, s) for (_, _, s), q in legs_q]
    pin_w = [ovn.fill2(q, s, ovn.WIDEN) for (_, _, s), q in legs_q]
    base |= {"lots": lots, "qty": qty, "credit": credit * qty}
    if any(o is None for o in ex):
        return base | {"status": "unresolved (open legs)", "open_legs": [legs_q[i][0] for i, o in enumerate(ex)
                                                                        if o is None],
                       "net": None, "net_worst": -reserve, "net_best": credit * qty - ef - xr}

    def net_of(entry_px, exits, widen):
        gross = sum(s * (o[1] - p) for ((_, _, s), _), p, o in zip(legs_q, entry_px, exits)) * qty
        exit_day = lambda ts: date.fromisoformat(ts[:10])  # noqa: E731
        fx = sum(ovn.gcosts.option_fill_fee(-s, o[1], qty, exit_day(o[0])).total
                 for ((_, _, s), _), o in zip(legs_q, exits))
        return gross, ovn.entry_fees(legs_q, qty, d, widen) + fx

    gross, fees = net_of(pin, ex, 1.0)
    gw, fw = net_of(pin_w, exw, ovn.WIDEN) if all(o is not None for o in exw) else (math.nan, math.nan)
    t_ex = [o[0] for o in ex]
    return base | {"status": "ok", "gross": gross, "fees": fees, "net": gross - fees, "net_widened": gw - fw,
                   "net_worst": gross - fees, "net_best": gross - fees, "exit_first": min(t_ex), "exit_last": max(t_ex),
                   "exit_session_late": date.fromisoformat(max(t_ex)[:10]) != n}


def score_v3(data: Path = ovn.DATA, daily_dir: Path = ovn.DAILY, start: date = V3_START,
             end: date | None = None) -> pd.DataFrame:
    """score_v2's session loop (calendar, blocking, missing data, pending inputs, VIX and event gates), with session_v3."""
    files = {date.fromisoformat(d): f for d, f in ovn.chain_days(data)}
    if end is None:
        end = max(files) if files else start
    if end < start:
        return pd.DataFrame(columns=["day", "status", "units"])
    nifty, vix = ovn.read_daily(daily_dir / "NIFTY_1d.pkl"), ovn.read_daily(daily_dir / "INDIAVIX_1d.pkl")
    rows, blocked_until = [], None
    for d in cal.sessions(start, end):
        row = {"day": d.isoformat(), "units": 0.0}
        n = cal.next_session(d)
        if blocked_until is not None and d < blocked_until:
            rows.append(row | {"status": "blocked (an earlier structure is unresolved)", "covered": True})
            continue
        if d not in files:
            rows.append(row | {"status": "missing data (no chain file)", "covered": False})
            continue
        prev = cal.prev_session(d)
        atr = ovn.atr14_asof(nifty, prev)
        v, rise = ovn.vix_state(vix, prev)
        if atr is None or v is None:
            rows.append(row | {"status": f"pending (daily NIFTY/VIX to {prev} not loaded)", "covered": False,
                               "units": math.nan})
            continue
        row |= {"vix_prev": v, "vix_rise5": rise}
        if v > ovn.VIX_MAX or rise > ovn.VIX_RISE_MAX:
            rows.append(row | {"status": "skip: VIX gate", "covered": True})
            continue
        ev = cal.events_between(d, n)
        if ev:
            rows.append(row | {"status": f"skip: event {ev[0][1]} {ev[0][0]}", "covered": True})
            continue
        later, x = [], n
        for _ in range(5):
            later.append((x, files.get(x)))
            try:
                x = cal.next_session(x)
            except cal.CalendarError:
                break
        r = session_v3(d, files[d], later, atr, 0.5 if v > ovn.VIX_HALF else 1.0, instruments.lot_size("NIFTY", d))
        row |= r
        if r["status"] == "ok":
            row["units"] = r["net"] / (ovn.BOOK * ovn.BUDGET_PCT)
            row["units_widened"] = r["net_widened"] / (ovn.BOOK * ovn.BUDGET_PCT)
            if r["exit_session_late"]:
                blocked_until = date.fromisoformat(r["exit_last"][:10])
        elif r["status"].startswith("unresolved"):
            row["units"] = math.nan
            row["units_worst"] = r["net_worst"] / (ovn.BOOK * ovn.BUDGET_PCT)
            row["units_best"] = r["net_best"] / (ovn.BOOK * ovn.BUDGET_PCT)
            if n <= end:
                blocked_until = date.max
        rows.append(row)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    t = score_v3()
    cols = [c for c in ("day", "status", "chain_spot", "forward", "atm", "Kc", "Kp", "credit_pts", "lots", "units")
            if c in t]
    print(t[cols].to_string(index=False) if len(t) else "no v3 sessions yet (first entry 28 Oct 15:20)")
    print(json.dumps({"sessions": int(len(t)), "entered": int((t.get("status") == "ok").sum()) if len(t) else 0}))
