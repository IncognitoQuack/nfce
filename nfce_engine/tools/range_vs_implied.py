"""Range model vs the option market's implied move: a dry measurement, no trades (../evidence/range_vs_implied_protocol.md).

  python tools/range_vs_implied.py 2026-10-26 [2026-10-27 ...]

For every range forecast (nfce.db.range_forecasts: log of the next hour's high-low over price, at bar closes every
15 minutes) it finds the first recorded chain snapshot at or after the bar close and converts the ATM straddle of
the nearest expiry that does not expire that day into an expected one-hour range:
  straddle_mid ~ S * sigma_total * sqrt(2/pi)                       (expected |S_T - K| at the money)
  sigma_hour   = sigma_total / sqrt(trading hours left to expiry)  (variance spread evenly over trading time)
  E[range_1h]  = sqrt(8/pi) * sigma_hour                           (driftless random walk)
The chain's own IV gives a cross-check (calendar time: sigma_total = iv * sqrt(calendar days / 365)).
Then both are scored against the realized log range. Read-only on every database.
"""
from __future__ import annotations

import math
import sqlite3
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
DATA = ROOT / "nfce_bridge" / "data"
SESSION_H = 6.25
OPEN_T, CLOSE_T = time(9, 15), time(15, 30)
ROOTS = ("NIFTY", "BANKNIFTY")


# Correction (26 Oct 2026, GS phase 0, review A finding 8; evidence/gs_phase0_amendments.md): exchange holidays
# (gs/calendar.py) no longer count as trading hours. False reproduces the weekdays-only count.
HOLIDAY_FIX = True


def _trading_day(d) -> bool:
    if not HOLIDAY_FIX:
        return d.weekday() < 5
    from gs import calendar as cal
    return cal.is_session(d) if cal.COVERED_FROM <= d <= cal.COVERED_UNTIL else d.weekday() < 5


def trading_hours_left(now: datetime, expiry: datetime.date) -> float:
    """Trading hours from `now` to the expiry's 15:30 close: regular sessions of the exchange calendar (weekdays
    outside the calendar's span). Still a mechanical proxy: variance is spread evenly over trading hours, and the
    implied figure is an expected range while q50 is a median of the log range (descriptive only, not a price)."""
    h = 0.0
    d = now.date()
    if OPEN_T <= now.time() < CLOSE_T and _trading_day(d):
        h += (datetime.combine(d, CLOSE_T) - now).total_seconds() / 3600
    elif now.time() < OPEN_T and _trading_day(d):
        h += SESSION_H
    d += timedelta(days=1)
    while d <= expiry:
        if _trading_day(d):
            h += SESSION_H
        d += timedelta(days=1)
    return h


def implied_range(straddle: float, spot: float, hours_left: float) -> float:
    """Expected next-hour high-low range as a fraction of price, from an ATM straddle mid."""
    sigma_total = straddle / (spot * math.sqrt(2 / math.pi))
    return math.sqrt(8 / math.pi) * sigma_total / math.sqrt(hours_left)


def iv_range(iv_pct: float, now: datetime, expiry, hours_left: float) -> float:
    cal_days = (datetime.combine(expiry, CLOSE_T) - now).total_seconds() / 86400
    sigma_total = iv_pct / 100 * math.sqrt(cal_days / 365)
    return math.sqrt(8 / math.pi) * sigma_total / math.sqrt(hours_left)


def read(day: str, data: Path = DATA) -> tuple[pd.DataFrame, pd.DataFrame]:
    f = data / f"study_chain_{day.replace('-', '')}.db"
    con = sqlite3.connect(f"file:{f}?mode=ro", uri=True)
    ch = pd.read_sql_query("select ts, underlying, expiry, spot, strike, typ, bid, ask, iv from chain "
                           "where underlying in ('NIFTY', 'BANKNIFTY')", con)
    con.close()
    con = sqlite3.connect(f"file:{data / 'nfce.db'}?mode=ro", uri=True)
    fc = pd.read_sql_query("select root, bar_close, model, price, q10, q50, q90, realized from range_forecasts "
                           "where substr(bar_close, 1, 10) = ?", con, params=(day,))
    con.close()
    return ch, fc


def measure(day: str, data: Path = DATA) -> pd.DataFrame:
    ch, fc = read(day, data)
    ch["t"] = pd.to_datetime(ch["ts"])
    ch["exp"] = pd.to_datetime(ch["expiry"].str[:10]).dt.date
    out = []
    for r in fc.itertuples():
        bc = datetime.fromisoformat(r.bar_close).replace(tzinfo=None)
        x = ch[(ch["underlying"] == r.root) & (ch["t"] >= bc) & (ch["t"] <= bc + timedelta(minutes=3))]
        x = x[x["exp"] > bc.date()]
        if x.empty:
            continue
        x = x[x["t"] == x["t"].min()]
        exp = min(x["exp"])
        x = x[x["exp"] == exp]
        spot = float(x["spot"].iloc[0])
        k = float(x["strike"].iloc[np.argmin(np.abs(x["strike"] - spot))])
        a = x[x["strike"] == k].set_index("typ")
        if not {"CE", "PE"} <= set(a.index) or (a[["bid", "ask"]] <= 0).any().any():
            continue
        straddle = float(((a["bid"] + a["ask"]) / 2).sum())
        hl = trading_hours_left(bc, exp)
        imp = implied_range(straddle, spot, hl)
        ivr = iv_range(float(a["iv"].mean()), bc, exp, hl)
        out.append({"root": r.root, "bar_close": r.bar_close[:16], "model": r.model, "expiry": str(exp), "hours_left": hl,
                    "straddle": straddle, "spot": spot, "q10": r.q10, "q50": r.q50, "q90": r.q90,
                    "log_implied": math.log(imp), "log_iv_implied": math.log(ivr), "realized": r.realized})
    return pd.DataFrame(out)


def summarize(m: pd.DataFrame) -> pd.DataFrame:
    """Per model and index: log-error bias and MAE of the model (q50) and of the implied move vs the realized range,
    80%-band coverage, and the mean model/implied ratio (exp of the log difference)."""
    rows = []
    done = m[m["realized"].notna()]
    for (model, root), g in done.groupby(["model", "root"]):
        rows.append({"model": model, "root": root, "n": len(g),
                     "model_bias": float((g["q50"] - g["realized"]).mean()),
                     "model_mae": float((g["q50"] - g["realized"]).abs().mean()),
                     "implied_bias": float((g["log_implied"] - g["realized"]).mean()),
                     "implied_mae": float((g["log_implied"] - g["realized"]).abs().mean()),
                     "iv_implied_mae": float((g["log_iv_implied"] - g["realized"]).abs().mean()),
                     "band80": float(((g["realized"] >= g["q10"]) & (g["realized"] <= g["q90"])).mean()),
                     "model_over_implied": float(np.exp(g["q50"] - g["log_implied"]).mean()),
                     "corr_model": float(g["q50"].corr(g["realized"])) if len(g) > 2 else math.nan,
                     "corr_implied": float(g["log_implied"].corr(g["realized"])) if len(g) > 2 else math.nan})
    return pd.DataFrame(rows)


def main() -> None:
    days = sys.argv[1:]
    m = pd.concat([measure(d) for d in days], ignore_index=True)
    pd.set_option("display.width", 220)
    print(m[m["model"] == "M1"].to_string(index=False))
    print(summarize(m).round(3).to_string(index=False))


if __name__ == "__main__":
    main()
