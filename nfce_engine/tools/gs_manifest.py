"""Build (and, when told to, freeze) the GS-SIP-1 manifest of evidence/gs_sip_1_protocol.md.

  ../nfce_bridge/.venv/bin/python tools/gs_manifest.py                    print the DESIGN manifest with current hashes
  ../nfce_bridge/.venv/bin/python tools/gs_manifest.py --freeze --db ../nfce_bridge/data/gs.db --start 2026-11-02

Freezing is the main session's step, after the adapter is wired: it fills start_session, sets status FROZEN and
writes the manifest into the GS store (a second freeze with different content is refused).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gs import calendar as cal  # noqa: E402
from gs import registry as reg  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CODE = ["nfce_engine/gs/" + f for f in ("__init__.py", "types.py", "calendar.py", "instruments.py", "store.py",
                                         "costs.py", "ledger.py", "risk.py", "execution.py", "budget.py",
                                         "features.py", "alpha_sip.py", "evaluate.py", "registry.py")]
CODE += ["nfce_bridge/bridge/gs_adapter.py", "nfce_bridge/bridge/gs_live.py", "nfce_engine/nfce/costs.py"]
CALENDAR = "nfce_engine/gs/calendar.py"
LIVE_FIELDS = ("code_hashes", "protocol_sha256", "fee_sha256", "dependency_lock_hash", "calendar_sha256")


def build(root: Path = ROOT, start: str | None = None, status: str = "DESIGN") -> dict:
    h = lambda rel: reg.sha256_file(root / rel)  # noqa: E731
    dep = reg.dependency_lock()
    return {
        "id": "GS-SIP-1", "status": status,
        "blueprint_sha256": h("GS_ENGINE_FINAL_BLUEPRINT.md"),
        "protocol_sha256": h("evidence/gs_sip_1_protocol.md"),
        "code_hashes": {c: h(c) for c in CODE},
        "dependency_lock": dep, "dependency_lock_hash": reg.manifest_hash(dep),
        "calendar_sha256": h("nfce_engine/gs/calendar.py"),
        "fee_sha256": reg.manifest_hash({"gs": h("nfce_engine/gs/costs.py"), "frozen": h("nfce_engine/nfce/costs.py")}),
        "start_rule": "first full exchange session after the freeze", "start_session": start,
        "pilot_sessions": 60, "validation_sessions": 60, "final_sessions": 1000, "max_final_duration_years": 5,
        "per_claim_alpha": 0.003125, "power": {"target": 0.8, "z_alpha": 2.734, "z_power": 0.842, "inflation": 1.5,
                                               "delta_bp_per_day": 1.0},
        "primary_series": "all-session net strict-fill portfolio return, bp of E0 = Rs 5 L",
        "bootstrap": {"kind": "stationary", "expected_block": 5, "replicates": 50000, "seed": 20261026},
        "robustness_blocks": [10, 20],
        "fee_model": "per-fill by fill date, Rs 20/order (gs/costs.py)",
        "execution": "gs/execution.py strict-through primary; adverse stress; touch illustration; M diagnostic",
        "minimum_counts_and_effect": {"filled_trades": 500, "distinct_days": 100, "mean_bp_per_day": 1.0},
        "early_efficacy_looks": "none (pilot futility only)", "safety": "gs/risk.py latches in the primary series",
        "invalid_data": "unresolved with bounds; no silent deletion",
        "verdicts": ["PASS", "FAIL", "INCONCLUSIVE", "INFEASIBLE"], "amendment": "new version, new sample",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", action="store_true")
    ap.add_argument("--db", type=Path)
    ap.add_argument("--start")
    x = ap.parse_args()
    if not x.freeze:
        print(json.dumps(build(), indent=1))
        return
    if not (x.db and x.start):
        sys.exit("--freeze needs --db and --start (the first full session after today)")
    start = date.fromisoformat(x.start)
    if not cal.is_session(start) or start <= date.today():
        sys.exit("--start must be a future exchange session")
    from gs import store as gstore
    m = build(start=x.start, status="FROZEN")
    print(reg.freeze(gstore.Store(x.db), m, datetime.now(timezone.utc)))


if __name__ == "__main__":
    main()
