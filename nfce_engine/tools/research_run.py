"""Multi-year research runner (../evidence/research_protocol.md). Reveals results stage by stage.

  python tools/research_run.py DATA_DIR --stage train
  python tools/research_run.py DATA_DIR --stage validation --configs "O NIFTY 30 opp eod none" ...
  python tools/research_run.py DATA_DIR --stage final --configs ...

DATA_DIR holds Upstox 5m pickles: NIFTY, BANKNIFTY, INDIAVIX and the heavyweights (<SYM>_5m.pkl).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce import Params, prepare, run  # noqa: E402
from nfce import costs  # noqa: E402
from nfce.research import expiry_dates, momentum, orb, vwap_trend  # noqa: E402
from nfce.stats import CostModel, block_bootstrap_mean  # noqa: E402

TZ = "Asia/Kolkata"
SPLITS = {"train": (dt.date(2022, 1, 1), dt.date(2024, 12, 31)), "validation": (dt.date(2025, 1, 1), dt.date(2025, 12, 31)),
          "final": (dt.date(2026, 1, 1), dt.date(2026, 7, 31))}
INDEX = {"NIFTY": (65, 0.1, ["HDFCBANK", "ICICIBANK", "RELIANCE", "INFY", "BHARTIARTL"]),
         "BANKNIFTY": (30, 0.2, ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK"])}
NFCE = {"N0": {}, "N1": dict(last_entry=1115), "N2": dict(last_entry=1115, r1m=2.0, r2m=2.0, r3m=2.0),
        "N3": dict(last_entry=1115, min_risk_pct=0.25), "N4": "score+10", "N5": dict(req_vol=True)}


def load(data: Path, sym: str) -> pd.DataFrame:
    d = pd.read_pickle(data / f"{sym}_5m.pkl")
    d.index = pd.DatetimeIndex(d.index).tz_convert(TZ)
    d = d[["open", "high", "low", "close", "volume"]].astype(float)
    hm = d.index.hour * 60 + d.index.minute
    d = d[(hm >= 9 * 60 + 15) & (hm <= 15 * 60 + 25)]               # regular session only (drops 09:10 pre-open, 15:30+)
    first = d.groupby(d.index.normalize()).apply(lambda g: g.index[0].hour * 60 + g.index[0].minute)
    keep = set(first[first == 9 * 60 + 15].index)                     # drops special sessions (e.g. Muhurat evenings)
    return d[d.index.normalize().isin(keep)]


def r15(x: pd.DataFrame) -> pd.DataFrame:
    g = x.groupby(pd.Grouper(freq="15min", origin=pd.Timestamp("2022-01-03 09:15", tz=TZ)))
    o = g.agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])
    n = g.size().reindex(o.index).fillna(0)
    return o[n == 3]


def configs() -> list[str]:
    out = []
    for ix in INDEX:
        for nid in NFCE:
            for tf in (5, 15):
                out.append(f"{nid} {ix} {tf}m")
        for orm in (15, 30, 60):
            for st in ("opp", "mid"):
                for ex in ("eod", "2R"):
                    for vg in ("none", "volgate"):
                        out.append(f"O {ix} {orm} {st} {ex} {vg}")
        for st in ("1430", "1500"):
            for fl in ("all", "big"):
                out.append(f"M {ix} {st} {fl}")
        for k in ("1.5", "3.0"):
            out.append(f"V {ix} {k}")
    return out


class Lab:
    def __init__(self, data: Path):
        self.data = data
        self.frames = {}
        self.vix = load(data, "INDIAVIX")
        self._prep = {}

    def bars(self, ix):
        if ix not in self.frames:
            b = load(self.data, ix)
            hw = [load(self.data, h) for h in INDEX[ix][2]]
            b["volume"] = sum(h["volume"].reindex(b.index).fillna(0) for h in hw)
            self.frames[ix] = (b, hw)
        return self.frames[ix]

    def trades(self, cfg: str) -> list[dict]:
        p = cfg.split()
        kind, ix = p[0], p[1]
        lot, tick, _ = INDEX[ix]
        b, hw = self.bars(ix)
        if kind.startswith("N"):
            tf = int(p[2][:-1])
            key = (ix, tf)
            sessions = sorted(set(b.index.normalize().date))
            base = Params(instr=ix, expiry_dates=expiry_dates(sessions, ix))
            if key not in self._prep:
                bb, vv, hh = (b, self.vix, hw) if tf == 5 else (r15(b), r15(self.vix), [r15(h) for h in hw])
                self._prep[key] = prepare(bb, tf, base, vix=vv, hw=hh)
            v = NFCE[kind]
            prm = replace(base, min_score_in=(75 if tf == 5 else 70)) if v == "score+10" else replace(base, **v)
            cm = CostModel("dated", lot_units=lot, lots=1, friction_pts_per_side=4 * tick)
            out = []
            for t in run(self._prep[key], prm):
                out.append(dict(day=t.entry_time.tz_convert(TZ).date(), gross=t.pnl, cost=cm.points(t), risk=t.R))
            return out
        if kind == "O":
            raw = orb(b, or_min=int(p[2]), stop=p[3], exit=p[4], volgate=p[5] == "volgate")
        elif kind == "M":
            raw = momentum(b, start_hm=int(p[2][:2]) * 60 + int(p[2][2:]), big_only=p[3] == "big")
        else:
            raw = vwap_trend(b, k=float(p[2]))
        out = []
        for t in raw:
            c = costs.futures_cost_points(t["entry"], t["exit"], t["side"], t["day"], lot, 1, t["orders"], 4 * tick)
            out.append(dict(day=t["day"], gross=t["side"] * (t["exit"] - t["entry"]), cost=c, risk=t["risk"]))
        return out


def stats(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0}
    df = pd.DataFrame(rows)
    df["net_r"] = (df.gross - df.cost) / df.risk
    df["gross_r"] = df.gross / df.risk
    daily = df.groupby("day").net_r.mean()
    t = daily.mean() / (daily.std(ddof=1) / math.sqrt(len(daily))) if len(daily) > 2 and daily.std() > 0 else 0.0
    try:
        from scipy.stats import t as student
        p1 = float(student.sf(t, len(daily) - 1))
    except Exception:
        p1 = 0.5 * math.erfc(t / math.sqrt(2))
    w, l_ = df.net_r[df.net_r > 0].sum(), -df.net_r[df.net_r < 0].sum()
    lo, hi = block_bootstrap_mean(list(df.net_r), [str(d) for d in df.day])
    years = df.groupby(pd.to_datetime(df.day).dt.year).net_r.mean().round(3).to_dict()
    return {"n": len(df), "win": float((df.net_r > 0).mean()), "gross_r": float(df.gross_r.mean()),
            "cost_r": float((df.cost / df.risk).mean()), "net_r": float(df.net_r.mean()), "t_day": float(t),
            "p_one_sided": p1, "pf": float(w / l_) if l_ > 0 else math.inf, "ci": [lo, hi], "years": years}


def main(data: Path, stage: str, cfgs: list[str] | None, out: Path | None) -> None:
    lab = Lab(data)
    a, b = SPLITS[stage]
    res = {}
    for cfg in cfgs or configs():
        rows = [r for r in lab.trades(cfg) if a <= r["day"] <= b]
        s = stats(rows)
        res[cfg] = s
        if s["n"]:
            print(f"{cfg:34s} n={s['n']:4d} win {s['win'] * 100:4.1f}% gross {s['gross_r']:+.3f} cost {s['cost_r']:.3f} "
                  f"net {s['net_r']:+.3f} PF {s['pf']:.2f} p1 {s['p_one_sided']:.3f} years {s['years']}", flush=True)
        else:
            print(f"{cfg:34s} n=0", flush=True)
    if out:
        out.write_text(json.dumps({"stage": stage, "results": res}, indent=1, default=str))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("--stage", choices=list(SPLITS), required=True)
    ap.add_argument("--configs", nargs="*")
    ap.add_argument("--out", type=Path)
    x = ap.parse_args()
    main(x.data, x.stage, x.configs, x.out)
