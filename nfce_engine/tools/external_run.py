"""Test the ChatGPT/Gemini report candidates (../evidence/external_protocol.md), stage by stage, at CURRENT costs.

  python tools/external_run.py DATA_DIR --stage train
  python tools/external_run.py DATA_DIR --stage validation --configs "S1 BANKNIFTY" ...
  python tools/external_run.py DATA_DIR --stage final --configs ... --i-accept-one-shot
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce import costs  # noqa: E402
from nfce import research2 as R  # noqa: E402
from tools.research_run import INDEX, SPLITS, Lab, load, stats  # noqa: E402

RULES = {
    "S1": lambda b, v, t: R.sigma_momentum(b),
    "S2": lambda b, v, t: R.noise_area(b),
    "S2L": lambda b, v, t: R.noise_area(b, long_only=True),
    "S3": lambda b, v, t: R.williams_pd(b),
    "S4": lambda b, v, t: R.williams_dsr(b),
    "S5": lambda b, v, t: R.nr7(b),
    "S5c": lambda b, v, t: R.nr7(b, include_idnr4=True, atr_floor=0.35),
    "S6": lambda b, v, t: R.oops(b, v, tick=t),
    "S7": lambda b, v, t: R.weekend_holiday_orb(b),
    "S8": lambda b, v, t: R.morning_move(b),
    "S9": lambda b, v, t: R.late_momentum(b),
}


def configs() -> list[str]:
    return [f"{r} {ix}" for r in RULES for ix in INDEX]


def trades(lab: Lab, cfg: str) -> list[dict]:
    rule, ix = cfg.split()
    lot, tick, _ = INDEX[ix]
    b, _ = lab.bars(ix)
    vix = lab.vix.close
    out = []
    for t in RULES[rule](b, vix, tick):
        c = costs.futures_cost_points(t["entry"], t["exit"], t["side"], costs.CURRENT, lot, 1, t["orders"], 4 * tick)
        out.append(dict(day=t["day"], gross=t["side"] * (t["exit"] - t["entry"]), cost=c, risk=t["risk"]))
    return out


def main(data: Path, stage: str, cfgs: list[str] | None, out: Path | None, one_shot: bool) -> None:
    if stage == "final" and not one_shot:
        sys.exit("final stage is one-shot: pass --i-accept-one-shot")
    lab = Lab(data)
    a, b = SPLITS[stage]
    res = {}
    for cfg in cfgs or configs():
        rows = [r for r in trades(lab, cfg) if a <= r["day"] <= b]
        s = stats(rows)
        if s["n"]:
            pts = sum(r["gross"] - r["cost"] for r in rows) / len(rows)
            s["net_pts"] = pts
            print(f"{cfg:16s} n={s['n']:4d} win {s['win'] * 100:4.1f}% gross {s['gross_r']:+.3f} cost {s['cost_r']:.3f} "
                  f"net {s['net_r']:+.3f}R ({pts:+.1f} pts) PF {s['pf']:.2f} p1 {s['p_one_sided']:.3f} "
                  f"CI {s['ci'][0]:+.2f}..{s['ci'][1]:+.2f} years {s['years']}", flush=True)
        else:
            print(f"{cfg:16s} n=0", flush=True)
        res[cfg] = s
    if out:
        out.write_text(json.dumps({"stage": stage, "costs": "current (18 Oct 2026)", "results": res}, indent=1, default=str))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("--stage", choices=list(SPLITS), required=True)
    ap.add_argument("--configs", nargs="*")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--i-accept-one-shot", action="store_true")
    x = ap.parse_args()
    main(x.data, x.stage, x.configs, x.out, x.i_accept_one_shot)
