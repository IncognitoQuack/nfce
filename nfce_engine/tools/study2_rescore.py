"""H1-H3 of study engine v2 re-scored with the corrected open-entry cost (GS phase 0; review A finding 1).

A diagnostic correction, not a new test: the registered run (`study2.py dev`, cached in study_engine2/dev.pkl) charged
ORB entries before 09:30 the normal slippage. This re-runs the dev stage (2022-24) for H1-H3 only, with
`study2.ORB_OPEN_COST_FIX = True`, into study_engine2/dev_corrected.pkl, and compares it with the cached run. The
final (2025-26) was never run for H1-H3 (they failed the gate), and it is not run here.

  nice -n 15 ../nfce_bridge/.venv/bin/python tools/study2_rescore.py [--workers 3]
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import study2 as s2  # noqa: E402


def compare(old: dict, new: dict, hyps=("H1", "H2", "H3")) -> dict:
    so, sn = s2.summarize(old), s2.summarize(new)
    out = {}
    for h in hyps:
        t = new["trades"][h]
        out[h] = {"n_old": so[h].get("n"), "n_new": sn[h].get("n"),
                  "net_r_old": so[h].get("net_r"), "net_r_new": sn[h].get("net_r"),
                  "net_bp_old": so[h].get("net_bp"), "net_bp_new": sn[h].get("net_bp"),
                  "gross_bp": sn[h].get("gross_bp"), "cost_bp_old": so[h].get("cost_bp"),
                  "cost_bp_new": sn[h].get("cost_bp"), "ci_new": sn[h].get("ci"), "p_day_new": sn[h].get("p_day"),
                  "share_open_entry": float(np.mean(t["open_entry"])) if len(t) else None,
                  "gate_old": s2.gate(so[h]), "gate_new": s2.gate(sn[h])}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    x = ap.parse_args()
    old = s2._load("dev")
    if old is None:
        sys.exit("the registered dev run (study_engine2/dev.pkl) is missing")
    s2.ORB_OPEN_COST_FIX = True
    new = s2.run_stage("dev", x.workers, ("H1", "H2", "H3"))
    (s2.WORK / "dev_corrected.pkl").write_bytes(pickle.dumps(new))
    print(json.dumps(compare(old, new), indent=1, default=float))


if __name__ == "__main__":
    main()
