"""The `nfce` control panel (owner, 22 Oct evening): one terminal command that runs, checks, fixes and sets up the
system. These tests cover the parts that must never go wrong: .env editing, secret masking, and the repair plan."""
import pytest

from bridge import panel


ENV = """# comment stays
UPSTOX_API_KEY=abc123secretkey
UPSTOX_API_SECRET=
TELEGRAM_CHAT_ID=1000000001
# ACCOUNTS=2L:200000   (example line, commented)
SCANNER=on
"""


def test_env_is_read_and_secrets_are_masked():
    env = panel.parse_env(ENV)
    assert env == {"UPSTOX_API_KEY": "abc123secretkey", "UPSTOX_API_SECRET": "", "TELEGRAM_CHAT_ID": "1000000001",
                   "SCANNER": "on"}
    assert panel.mask("UPSTOX_API_KEY", "abc123secretkey") == "abc1…ey (15 chars)"
    assert panel.mask("SCANNER", "on") == "on"                          # not a secret: shown
    assert panel.mask("UPSTOX_API_SECRET", "") == "(empty)"


def test_setting_a_value_keeps_comments_and_order_and_adds_new_keys():
    out = panel.set_env_value(ENV, "UPSTOX_API_SECRET", "s3cr3t")
    assert "UPSTOX_API_SECRET=s3cr3t\n" in out and out.startswith("# comment stays\n")
    assert out.count("UPSTOX_API_SECRET") == 1 and "# ACCOUNTS=2L:200000" in out
    out2 = panel.set_env_value(out, "ACCOUNTS", "5L:500000")
    assert out2.endswith("ACCOUNTS=5L:500000\n") and "# ACCOUNTS=2L:200000" in out2
    with pytest.raises(ValueError):
        panel.set_env_value(ENV, "BAD KEY", "x")
    with pytest.raises(ValueError):
        panel.set_env_value(ENV, "SCANNER", "on\nEVIL=1")                 # no injected lines


def test_missing_required_keys():
    assert panel.missing_keys(panel.parse_env(ENV)) == ["UPSTOX_API_SECRET", "UPSTOX_REDIRECT_URI",
                                                        "TELEGRAM_BOT_TOKEN", "TELEGRAM_ADMIN_CHAT_IDS"]


def base_state(**kw):
    s = dict(venv_ok=True, env_missing=[], supervisor=False, maintenance=False, bridge_proc=False, health=None,
             in_market=False, token_ok=True, on_ac=True, db_ok=True, ledger_problems=[], log_mb=5.0, disk_gb=100.0,
             port_other=False, hung=False)
    s.update(kw)
    return s


def test_repair_plan_fixes_what_is_safe_and_only_reports_the_rest():
    assert [x for x in panel.diagnose(base_state()) if x[0] != "info"] == []
    plan = panel.diagnose(base_state(supervisor=False, maintenance=True, log_mb=300))
    assert {a for lvl, _, a in plan if lvl == "fix"} == {"clear_maintenance", "rotate_logs"}
    assert any(lvl == "info" and "nfce supervisor on" in m for lvl, m, _ in plan)   # opt-in only (owner, 22 Oct)
    acts = {a: lvl for lvl, _, a in panel.diagnose(base_state(venv_ok=False, env_missing=["X"], token_ok=False,
                                                                db_ok=False, ledger_problems=["5L off by ₹3"]))}
    assert acts["rebuild_venv"] == "fix" and acts["ask_env"] == "fix" and acts["login"] == "fix"
    assert acts["restore_db"] == "fix"
    assert acts[None] == "report"                                          # ledger: money records are never auto-edited
    assert any(a == "restart_bridge" for _, _, a in panel.diagnose(base_state(bridge_proc=True, hung=True,
                                                                              in_market=True)))
    # a maintenance file while the bridge is down in market hours is a deliberate stop: kept
    assert [x for x in panel.diagnose(base_state(maintenance=True, in_market=True)) if x[0] != "info"] == []


def test_help_lists_every_command(capsys):
    assert panel.main(["help"]) == 0
    out = capsys.readouterr().out
    for c in ("status", "start", "stop", "restart", "login", "check", "fix", "logs", "messages", "accounts",
              "report", "test", "study", "backup", "supervisor", "setup", "env"):
        assert f"  {c}" in out


def test_the_process_pattern_finds_a_real_bridge_process():
    # 23 Oct: "-m bridge.start" was read by pgrep as an option, so `nfce stop` said "already stopped" while the
    # bridge ran (and the supervisor's process check always said "none"). Checked here against a REAL process.
    import subprocess
    import sys
    import time
    assert not panel.bridge_running() or True                    # a real bridge may run on this Mac: no assumption
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "-m", "bridge.start"])
    try:
        time.sleep(0.5)
        assert panel.bridge_running()
        from bridge.offline_bot import OfflineBot
        assert OfflineBot._bridge_process()
    finally:
        p.kill()


def test_new_runbook_commands_are_registered_and_guarded(monkeypatch):
    """27 Oct: morning / evening / jobs / desk / eod / research. evening stops the bridge, so it refuses during market
    hours; morning needs the bridge running first (the owner's sign-in is never automated)."""
    names = [n for n, _, _ in panel.COMMANDS]
    for n in ("morning", "evening", "jobs", "desk", "eod", "research"):
        assert n in names
    called = []
    monkeypatch.setattr(panel, "_ops", lambda *a, **k: called.append(a) or 0)
    monkeypatch.setattr(panel, "in_market", lambda now=None: True)
    assert panel.cmd_evening([]) == 1 and not called
    monkeypatch.setattr(panel, "bridge_running", lambda: False)
    assert panel.cmd_morning([]) == 1 and not called
    monkeypatch.setattr(panel, "in_market", lambda now=None: False)
    assert panel.cmd_evening([]) == 0 and called == [("runbook.py", "evening")]
