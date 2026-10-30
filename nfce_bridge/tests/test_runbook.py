"""Runbook: the right jobs for the day, and nothing is ever started twice (no processes are started here)."""
from datetime import date

from ops import runbook as rb


def test_jobs_for_a_day_use_that_days_files():
    j = {x["name"]: x for x in rb.jobs(date(2026, 10, 28))}
    assert set(j) == {"chain", "quotes", "news", "track", "stream", "desk"}
    assert j["chain"]["cmd"][-2:] == ["data/study_chain_20261028.db", "15:31"]
    assert j["stream"]["cmd"][-2:] == ["data/stream_20261028.db", "15:40"]


def test_running_detection_is_per_day_and_per_job():
    procs = ["/x/.venv/bin/python ops/collect_chain.py data/study_chain_20261028.db 15:31",
             "/x/.venv/bin/python ops/stream.py data/stream_20261027.db 15:40"]              # yesterday's stream
    j = {x["name"]: x for x in rb.jobs(date(2026, 10, 28))}
    assert rb.is_running(j["chain"], procs)
    assert not rb.is_running(j["stream"], procs)                 # a different day's process does not count
    st = rb.status(date(2026, 10, 28), procs)
    assert st["jobs"]["chain"] and not st["jobs"]["quotes"]


def test_stale_desk_is_detected_by_its_start_date():
    ps = ("  PID STARTED                      COMMAND\n"
          "52592 Tue Oct 27 19:13:07 2026     /x/Python ops/desk.py --port 8001\n"
          "55562 Wed Oct 28 08:50:01 2026     /x/Python ops/desk.py --port 8001\n"
          "60000 Tue Oct 27 09:00:00 2026     /x/Python ops/stream.py data/stream_20261027.db 15:40\n")
    assert rb.stale_pids("ops/desk.py", date(2026, 10, 28), ps) == [52592]
    assert rb.stale_pids("ops/desk.py", date(2026, 10, 27), ps) == []


def test_morning_stops_when_the_bridge_is_down(monkeypatch):
    monkeypatch.setattr(rb, "health", lambda: {"error": "ConnectError"})
    monkeypatch.setattr(rb, "start", lambda job, day: (_ for _ in ()).throw(AssertionError("must not start")))
    out = rb.morning(date(2026, 10, 28))
    assert out["steps"][0].startswith("STOP: the bridge")


def test_morning_refreshes_index_bars_and_runs_the_brief_before_track(monkeypatch):
    # 28 Oct: track started before the brief wrote watch_<day>.json and crashed; OVN lacked yesterday's bar
    from bridge import panel
    order = []
    monkeypatch.setattr(rb, "health", lambda: {"gs": "FROZEN | day started 09:00"})
    monkeypatch.setattr(panel, "token_line", lambda: (True, "ok"))
    monkeypatch.setattr(panel, "power", lambda: (True, 100))
    monkeypatch.setattr(rb, "stale_pids", lambda match, day: [])
    monkeypatch.setattr(rb, "running", lambda lister=None: [])
    monkeypatch.setattr(rb, "start", lambda job, day: order.append("start " + job["name"]) or 1)

    class R:
        returncode, stdout, stderr = 0, "saved 3 symbols (2016-10-29..2026-10-28); failed: []", ""

    def run(cmd, **kw):
        order.append(" ".join(cmd[1:3]) + (" --only" if "--only" in cmd else ""))
        return R()
    monkeypatch.setattr(rb.subprocess, "run", run)
    out = rb.morning(date(2026, 10, 29))
    assert order[0] == f"ops/pull_daily.py {rb.DAILY} --only"
    assert order.index("ops/news_brief.py brief") < order.index("start track")
    assert order.count("ops/news_brief.py brief") == 1
    assert any(s.startswith("daily index bars: saved 3") for s in out["steps"])
