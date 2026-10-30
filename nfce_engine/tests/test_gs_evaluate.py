"""gs/evaluate.py and gs/registry.py on synthetic null, positive and dependent data, the power formula, the stage
rules and the one-look lock."""
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gs import evaluate as ev  # noqa: E402
from gs import registry as reg  # noqa: E402
from gs import store as gstore  # noqa: E402

NOW = datetime(2027, 1, 1, tzinfo=timezone.utc)


def ar1(n, phi, rng, mu=0.0):
    e = rng.normal(size=n + 100)
    x = np.empty_like(e)
    x[0] = e[0]
    for t in range(1, len(e)):
        x[t] = phi * x[t - 1] + e[t]
    return x[100:] * math.sqrt(1 - phi ** 2) + mu        # unit marginal variance


# ---------------------------------------------------------------- resampling
def test_stationary_blocks_have_the_expected_mean_length_and_wrap():
    idx = ev.stationary_indices(1000, 5.0, 200, np.random.default_rng(1))
    assert idx.shape == (200, 1000) and idx.min() >= 0 and idx.max() < 1000
    breaks = (np.diff(idx, axis=1) != 1) & ~((idx[:, :-1] == 999) & (idx[:, 1:] == 0))
    assert 4.5 < 999 / breaks.sum(axis=1).mean() < 5.5
    f = ev.fixed_block_indices(25, 10, 3, np.random.default_rng(2))
    assert f.shape == (3, 25) and all(((f[:, 1:10] - f[:, :9]) % 25 == 1).all(axis=1))


def test_bootstrap_is_reproducible_from_the_seed_and_runs_50000_reps():
    x = np.random.default_rng(3).normal(0.1, 1, 300)
    a, b = ev.mean_test(x), ev.mean_test(x)
    assert a == b and a.n == 300 and a.kind == "stationary"
    assert ev.mean_test(x, seed=1).p != a.p
    with pytest.raises(ValueError):
        ev.mean_test([1.0, float("nan"), 2.0])


# ---------------------------------------------------------------- calibration on synthetic data
def rejection_rate(gen, n_series, alpha, block, kind="stationary", reps=1000):
    rng = np.random.default_rng(11)
    hits = 0
    for i in range(n_series):
        x = gen(rng)
        hits += ev.mean_test(x, block, kind, alpha, reps, seed=100 + i).p < alpha
    return hits / n_series


def test_null_iid_rejects_at_about_the_nominal_rate():
    r = rejection_rate(lambda g: g.normal(0, 1, 400), 300, 0.05, 5)
    assert 0.02 <= r <= 0.09


def test_dependent_null_block_bootstrap_beats_iid():
    gen = lambda g: ar1(400, 0.6, g)                     # noqa: E731
    iid = rejection_rate(gen, 200, 0.05, 1, "fixed")
    blk = rejection_rate(gen, 200, 0.05, 20, "fixed")
    assert iid > 0.12 and blk < iid and blk <= 0.10      # ignoring dependence over-rejects; blocks fix most of it


def test_positive_effect_is_detected_and_a_null_rarely_passes_the_strict_alpha():
    pos = rejection_rate(lambda g: g.normal(0.3, 1, 1000), 20, ev.ALPHA, 5, reps=4000)
    assert pos >= 0.9
    null = rejection_rate(lambda g: g.normal(0.0, 1, 1000), 60, ev.ALPHA, 5, reps=4000)
    assert null <= 0.05


# ---------------------------------------------------------------- power
def test_power_formula_matches_a_and_the_protocol_constants():
    assert abs(NormalDist().inv_cdf(1 - 0.003125) - ev.Z_ALPHA) < 1e-3 and abs(NormalDist().inv_cdf(0.8) - ev.Z_POWER) < 1e-3
    assert ev.required_sessions(7, 1) == 940 and ev.required_sessions(0.30, 0.05) == 691      # A: 940 / 691
    assert ev.required_sessions(6, 1) == 691
    assert ev.mean_detectable(40) == pytest.approx(0.565, abs=1e-3)                            # A's 0.565 SD
    with pytest.raises(ValueError):
        ev.required_sessions(1, 0)


# ---------------------------------------------------------------- stage rules
def test_pilot_futility_and_infeasible():
    rng = np.random.default_rng(5)
    bad = ev.pilot_decision(rng.normal(-0.5, 1, 60), 0.05, 60, reps=4000)
    assert bad.status == "FAIL" and "futility" in bad.reasons[0]
    noisy = ev.pilot_decision(np.tile([1.05, -0.95], 30), 0.05, 60, reps=4000)   # SD 1: N ~ 7,700 sessions
    assert noisy.status == "INFEASIBLE" and noisy.stats["n_final"] > ev.max_sessions()
    ok = ev.pilot_decision(rng.normal(0.05, 0.3, 60), 0.05, 60, reps=4000)
    assert ok.status in ("CONTINUE", "FAIL") and ok.stats["n_final"] > 0
    assert ev.pilot_decision([0.1] * 30, 0.05, 60).status == "INCONCLUSIVE"


def test_validation_gate():
    assert ev.validation_decision([1, 2], [1, 1], 0.97, 120, 100).status == "CONTINUE"
    assert ev.validation_decision([1, -2], [1, 1], 0.97, 120, 100).status == "FAIL"
    assert ev.validation_decision([1, 2], [-1, -2], 0.97, 120, 100).status == "FAIL"
    assert ev.validation_decision([1, 2], [1, 1], 0.90, 120, 100).status == "FAIL"
    assert ev.validation_decision([1, 2], [1, 1], 0.99, 15, 20).status == "INFEASIBLE"


def test_final_verdicts_pass_fail_inconclusive():
    rng = np.random.default_rng(9)
    x = rng.normal(0.3, 1, 1000)
    kw = dict(delta=0.05, n_required=1000, count=600, min_count=500, coverage=0.99, reps=4000)
    assert ev.final_decision(x, x, widened=x - 0.01, **kw).status == "PASS"
    assert ev.final_decision(x, x, widened=x - 1.0, **kw).status == "FAIL"                   # spread stress
    assert ev.final_decision(x, x, adverse=x - 1.0, **kw).status == "FAIL"                   # adverse selection
    assert ev.final_decision(x, x, extra_checks={"no unresolved validity gate": False}, **kw).status == "FAIL"
    worst = x.copy()
    worst[:400] -= 3.0                                                                         # unresolved could flip
    assert ev.final_decision(worst, x, **kw).status == "INCONCLUSIVE"
    assert ev.final_decision(x[:900], x[:900], **kw).status == "INCONCLUSIVE"                # no early look
    assert ev.final_decision(x, x, **{**kw, "count": 400}).status == "INCONCLUSIVE"
    null = rng.normal(0, 1, 1000)
    assert ev.final_decision(null, null, **kw).status == "FAIL"
    dep = ar1(1000, 0.7, rng, mu=0.12)                                                       # dependent, small mean
    d = ev.final_decision(dep, dep, **kw)
    assert d.status == "FAIL" and any("fixed block" in r or "p " in r for r in d.reasons)


# ---------------------------------------------------------------- registry
def manifest(**kw):
    m = {k: "x" for k in reg.REQUIRED}
    m.update(id="GS-TEST-1", status="FROZEN", pilot_sessions=60, validation_sessions=60, final_sessions=1000,
             code_hashes={"gs/alpha_sip.py": "abc"}, dependency_lock_hash="d", calendar_sha256="c", fee_sha256="f",
             start_session="2026-11-02")
    m.update(kw)
    return m


def test_design_manifests_cannot_be_frozen(tmp_path):
    s = gstore.Store(tmp_path / "gs.db")
    with pytest.raises(reg.RegistryError):
        reg.freeze(s, manifest(code_hashes=None), NOW)
    with pytest.raises(reg.RegistryError):
        reg.freeze(s, manifest(status="DESIGN"), NOW)
    m = manifest()
    h = reg.freeze(s, m, NOW)
    assert reg.freeze(s, m, NOW) == h                                          # idempotent
    with pytest.raises(reg.RegistryError):
        reg.freeze(s, manifest(final_sessions=900), NOW)                      # same id, new content
    assert len(reg.dependency_lock()["numpy"]) > 0


def test_stages_in_order_once_each_and_never_after_a_change(tmp_path):
    s = gstore.Store(tmp_path / "gs.db")
    m = manifest()
    reg.freeze(s, m, NOW)
    cont = ev.Decision("pilot", "CONTINUE", (), {"n_final": 1000})
    with pytest.raises(reg.RegistryError):
        reg.record_stage(s, m, "validation", cont, NOW)                       # pilot first
    reg.record_stage(s, m, "pilot", cont, NOW)
    with pytest.raises(gstore.AppendOnlyError):
        reg.record_stage(s, m, "pilot", cont, NOW)                            # no second look
    with pytest.raises(reg.RegistryError):
        reg.record_stage(s, manifest(per_claim_alpha="0.01"), "validation", cont, NOW)   # changed manifest
    reg.record_stage(s, m, "validation", ev.Decision("validation", "CONTINUE", (), {}), NOW)
    x = np.random.default_rng(4).normal(0.3, 1, 1000)
    out = reg.run_final(s, m, NOW, worst=x, best=x, delta=0.05, count=600, min_count=500, coverage=0.99, reps=2000)
    assert out["status"] == "PASS"
    with pytest.raises(reg.RegistryError):
        reg.run_final(s, m, NOW, worst=x, best=x, delta=0.05, count=600, min_count=500, coverage=0.99, reps=2000)


def test_a_failed_stage_stops_the_test(tmp_path):
    s = gstore.Store(tmp_path / "gs.db")
    m = manifest()
    reg.freeze(s, m, NOW)
    reg.record_stage(s, m, "pilot", ev.Decision("pilot", "FAIL", ("futility",), {}), NOW)
    with pytest.raises(reg.RegistryError):
        reg.record_stage(s, m, "validation", ev.Decision("validation", "CONTINUE", (), {}), NOW)


def test_the_sip_manifest_is_design_until_frozen_and_hashes_its_files(tmp_path):
    from tools import gs_manifest as gm
    for rel in gm.CODE + ["GS_ENGINE_FINAL_BLUEPRINT.md", "evidence/gs_sip_1_protocol.md"]:
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(rel)
    m = gm.build(tmp_path)
    assert m["status"] == "DESIGN" and not reg.is_freezable(m)[0] and reg.missing(m) == []
    s = gstore.Store(tmp_path / "gs.db")
    with pytest.raises(reg.RegistryError):
        reg.freeze(s, m, NOW)
    f = gm.build(tmp_path, start="2026-11-02", status="FROZEN")
    assert reg.freeze(s, f, NOW) == reg.manifest_hash(f)
    (tmp_path / "nfce_engine/gs/alpha_sip.py").write_text("changed")
    assert gm.build(tmp_path, start="2026-11-02", status="FROZEN") != f      # any code change changes the manifest
