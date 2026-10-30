"""Hashed manifests and the one-look lock (A sections 5 and 16).

A manifest is a dict with A's required fields. It is DESIGN until every implementation-freeze field is filled
(code hashes, dependency lock, calendar/fee snapshot hashes); only then can it be frozen into the store. Stage
decisions are recorded once each (`<id>:pilot`, `<id>:validation`, `<id>:final`), in order, and only on complete
stage samples: there is no early look, no second look, and no look under a manifest that changed after the freeze.
"""
from __future__ import annotations

import hashlib
import importlib.metadata as md
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from . import evaluate as ev
from .types import canonical_json

REQUIRED = ("id", "status", "blueprint_sha256", "protocol_sha256", "pilot_sessions", "validation_sessions",
            "final_sessions", "max_final_duration_years", "per_claim_alpha", "power", "primary_series", "bootstrap",
            "robustness_blocks", "fee_model", "execution", "minimum_counts_and_effect", "early_efficacy_looks",
            "safety", "invalid_data", "verdicts", "amendment", "start_rule")
FREEZE_FIELDS = ("code_hashes", "dependency_lock_hash", "calendar_sha256", "fee_sha256", "start_session")
STAGES = ("pilot", "validation", "final")


class RegistryError(RuntimeError):
    pass


def sha256_file(p: str | Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def file_hashes(paths, root: str | Path) -> dict:
    root = Path(root)
    return {str(Path(p).resolve().relative_to(root.resolve())): sha256_file(p) for p in sorted(map(str, paths))}


def dependency_lock(packages=("numpy", "pandas", "scikit-learn")) -> dict:
    import sys
    out = {"python": sys.version.split()[0]}
    for p in packages:
        try:
            out[p] = md.version(p)
        except md.PackageNotFoundError:
            out[p] = None
    return out


def manifest_hash(m: dict) -> str:
    return hashlib.sha256(canonical_json(m).encode()).hexdigest()


def missing(m: dict) -> list[str]:
    return [k for k in REQUIRED if m.get(k) in (None, "")]


def is_freezable(m: dict) -> tuple[bool, list[str]]:
    gaps = missing(m) + [k for k in FREEZE_FIELDS if not m.get(k)]
    return not gaps, gaps


def freeze(store, m: dict, now: datetime) -> str:
    """Freeze an executable manifest: all fields present, status FROZEN. Returns its hash. Idempotent for the same
    content; a different manifest under the same id raises (an amendment needs a new version id)."""
    ok, gaps = is_freezable(m)
    if not ok:
        raise RegistryError(f"manifest {m.get('id')} is not freezable; missing {gaps}")
    if m["status"] != "FROZEN":
        raise RegistryError("set status = FROZEN to freeze (DESIGN manifests cannot start a test)")
    h = manifest_hash(m)
    old = store.protocol(m["id"])
    if old is not None and old["sha256"] != h:
        raise RegistryError(f"{m['id']} is already frozen with a different hash: amend as a new version")
    store.freeze_protocol(m["id"], h, now, m)
    return h


def _frozen(store, pid: str, m: dict) -> dict:
    rec = store.protocol(pid)
    if rec is None:
        raise RegistryError(f"{pid} is not frozen")
    if rec["sha256"] != manifest_hash(m):
        raise RegistryError(f"{pid}: the manifest changed after the freeze")
    return rec


def record_stage(store, m: dict, stage: str, decision: ev.Decision, now: datetime) -> dict:
    """Record one stage decision, once, in order, under the frozen manifest."""
    pid = m["id"]
    _frozen(store, pid, m)
    if stage not in STAGES:
        raise RegistryError(stage)
    i = STAGES.index(stage)
    if i > 0:
        prev = store.verdict(f"{pid}:{STAGES[i - 1]}")
        if prev is None:
            raise RegistryError(f"{stage} before {STAGES[i - 1]}")
        if prev["status"] != "CONTINUE":
            raise RegistryError(f"{pid} stopped at {STAGES[i - 1]} ({prev['status']})")
    body = {"stage": stage, "status": decision.status, "reasons": list(decision.reasons),
            "stats": decision.stats, "manifest_sha256": manifest_hash(m)}
    store.record_verdict(f"{pid}:{stage}", now, body)          # raises on a second look
    return body


def run_final(store, m: dict, now: datetime, **final_inputs) -> dict:
    """The one locked final look: requires a CONTINUE validation, the fixed N, and records exactly once."""
    pid = m["id"]
    _frozen(store, pid, m)
    if store.verdict(f"{pid}:final") is not None:
        raise RegistryError(f"{pid} final already evaluated: one look only")
    pil = store.verdict(f"{pid}:pilot")
    n_req = int(final_inputs.pop("n_required", 0) or (pil or {}).get("stats", {}).get("n_final", 0) or
                m["final_sessions"])
    d = ev.final_decision(n_required=n_req, **final_inputs)
    return record_stage(store, m, "final", d, now)


def decision_dict(d: ev.Decision) -> dict:
    return asdict(d)


def register_calendar_extension(store, protocol_id: str, new_calendar_sha: str, covered_until: str, now: datetime,
                                note: str) -> bool:
    """A calendar data extension after the freeze (e.g. NSE's 2027 holidays, published in December): recorded as its
    own append-only record. The live freeze check accepts the new calendar hash only if such a record exists. The
    caller must have verified that no session on or before the freeze date changed (tests/test_gs_calendar.py)."""
    return store.freeze_protocol(f"{protocol_id}:calendar:{new_calendar_sha}", new_calendar_sha, now,
                                 {"covered_until": covered_until, "note": note})
