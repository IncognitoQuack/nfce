"""Daily runbook: the morning start-up and the evening close, every step checked (27 Oct 2026).

    PYTHONPATH=. .venv/bin/python ops/runbook.py status
    PYTHONPATH=. .venv/bin/python ops/runbook.py morning     # after `nfce start` and the owner's Upstox sign-in
    PYTHONPATH=. .venv/bin/python ops/runbook.py evening     # after the 15:35 backup

morning: checks the bridge answers /health with a valid token, then starts each recorder, the shadow stream and the
desk, unless already running (nothing is ever started twice), and runs the news brief. It never signs in and never
sends a Telegram message: those stay the owner's and the operator's steps.
evening: waits for the 15:35 backup, stops the bridge, refreshes the daily candles, writes the end-of-day report
(which scores OVN v2/v3, OPX-1 and SCALP-1), rebuilds the package, and prints a summary.
Logs: ~/Library/Logs/nfce_<job>_<YYYYMMDD>.log.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = str(ROOT / ".venv" / "bin" / "python")
LOGS = Path.home() / "Library" / "Logs"


DAILY = Path.home() / "Downloads" / "nfce_data" / "daily"
OVN_DAILY = ("NIFTY", "BANKNIFTY", "INDIAVIX")


def jobs(day: date) -> list[dict]:
    """The session's background jobs: name, a pattern unique to its process, the command."""
    d = day.strftime("%Y%m%d")
    return [
        {"name": "chain", "match": f"ops/collect_chain.py data/study_chain_{d}.db",
         "cmd": [PY, "ops/collect_chain.py", f"data/study_chain_{d}.db", "15:31"]},
        {"name": "quotes", "match": f"ops/collect.py data/study_quotes_{d}.db",
         "cmd": [PY, "ops/collect.py", f"data/study_quotes_{d}.db", "15:31"]},
        {"name": "news", "match": f"ops/news_watch.py data/study_news_{d}.db",
         "cmd": [PY, "ops/news_watch.py", f"data/study_news_{d}.db", "15:30"]},
        {"name": "track", "match": "ops/news_brief.py track", "cmd": [PY, "ops/news_brief.py", "track", "15:30", "5"],
         "after_brief": True},                                       # it reads the brief's watch_<day>.json
        {"name": "stream", "match": f"ops/stream.py data/stream_{d}.db",
         "cmd": [PY, "ops/stream.py", f"data/stream_{d}.db", "15:40"]},
        {"name": "desk", "match": "ops/desk.py", "cmd": [PY, "ops/desk.py", "--port", "8001", "--lan"]},   # owner OK 28 Oct
    ]


def running(lister=None) -> list[str]:
    """Command lines of running processes (ps); `lister` lets tests inject a list."""
    if lister is not None:
        return lister()
    out = subprocess.run(["ps", "-eo", "command"], capture_output=True, text=True).stdout
    return out.splitlines()


def is_running(job: dict, procs: list[str]) -> bool:
    return any(job["match"] in p for p in procs)


def stale_pids(match: str, day: date, ps_out: str | None = None) -> list[int]:
    """PIDs of `match` processes started before `day` (a desk left running overnight keeps yesterday's code: on 27 Oct
    a 19:13 desk still had the inverted battery reading). `ps -eo pid,lstart,command`; lstart = 'Tue Oct 27 19:13:07 2026'."""
    if ps_out is None:
        ps_out = subprocess.run(["ps", "-eo", "pid,lstart,command"], capture_output=True, text=True).stdout
    out = []
    for line in ps_out.splitlines()[1:]:
        parts = line.split(None, 6)
        if len(parts) < 7 or match not in parts[6]:
            continue
        try:
            started = datetime.strptime(" ".join(parts[1:6]), "%a %b %d %H:%M:%S %Y").date()
        except ValueError:
            continue
        pid = int(parts[0])
        if started < day and pid not in (os.getpid(), os.getppid()):     # never the caller itself
            out.append(pid)
    return out


def start(job: dict, day: date) -> int:
    LOGS.mkdir(parents=True, exist_ok=True)
    log = open(LOGS / f"nfce_{job['name']}_{day:%Y%m%d}.log", "a")
    p = subprocess.Popen(job["cmd"], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                         env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                              "HOME": str(Path.home())})
    return p.pid


def health() -> dict:
    try:
        import httpx
        return httpx.get("http://127.0.0.1:8000/health", timeout=3).json()
    except Exception as exc:
        return {"error": type(exc).__name__}


def status(day: date, procs: list[str] | None = None) -> dict:
    procs = procs if procs is not None else running()
    h = health()
    return {"bridge": "up" if "error" not in h else f"down ({h['error']})",
            "gs": h.get("gs"), "jobs": {j["name"]: is_running(j, procs) for j in jobs(day)}}


def morning(day: date) -> dict:
    out = {"steps": []}
    h = health()
    if "error" in h:
        out["steps"].append("STOP: the bridge does not answer /health. Run `nfce start` (the owner signs in), then rerun.")
        return out
    from bridge import panel
    tok_ok, tok = panel.token_line()
    if not tok_ok:
        out["steps"].append(f"STOP: {tok}")
        return out
    on_ac, pct = panel.power()                     # (on charger, %)
    if on_ac is False:
        out["steps"].append(f"WARN: on battery ({pct}%): ask the owner to plug in")
    import signal
    for pid in stale_pids("ops/desk.py", day):                 # never reuse a desk running yesterday's code
        os.kill(pid, signal.SIGTERM)
        out["steps"].append(f"restarted a stale desk (pid {pid} was started before today)")
        time.sleep(2)
    env = {"PYTHONPATH": str(ROOT), "HOME": str(Path.home()), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([PY, "ops/pull_daily.py", str(DAILY), "--only", ",".join(OVN_DAILY)], cwd=ROOT,
                       capture_output=True, text=True, env=env)          # 28 Oct: OVN sat "pending" on a missing bar
    out["steps"].append("daily index bars: " + ((r.stdout.strip().splitlines() or [r.stderr[-200:]])[-1]))
    procs = running()
    brief_done = False
    for j in jobs(day):
        if j.get("after_brief") and not brief_done:                    # 28 Oct: track started before its input
            r = subprocess.run([PY, "ops/news_brief.py", "brief"], cwd=ROOT, capture_output=True, text=True, env=env)
            out["steps"].append(f"news brief: {'ok' if r.returncode == 0 else 'FAILED'} → "
                                f"data/news/brief_{day:%Y%m%d}.md (send it to the S chat with ops/reply.py)")
            brief_done = True
        if is_running(j, procs):
            out["steps"].append(f"ok   {j['name']}: already running")
        else:
            out["steps"].append(f"start {j['name']}: pid {start(j, day)}")
    out["steps"].append(f"GS: {h.get('gs')} (must read FROZEN | day started 09:0x before 09:21)")
    return out


def evening(day: date, wait_s: int = 900) -> dict:
    out = {"steps": []}
    backup = ROOT / "data" / "backups" / f"nfce_{day:%Y%m%d}_1535.db"
    t0 = time.time()
    while not backup.exists() and time.time() - t0 < wait_s and "error" not in health():
        time.sleep(15)
    out["steps"].append(f"15:35 backup: {'present' if backup.exists() else 'MISSING'}")
    r = subprocess.run([str(ROOT / "nfce"), "stop"], cwd=ROOT, capture_output=True, text=True)
    out["steps"].append(f"nfce stop: {'ok' if r.returncode == 0 else r.stdout[-200:]}")
    env = {"PYTHONPATH": str(ROOT), "HOME": str(Path.home()), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([PY, "ops/pull_daily.py", str(DAILY), "--with-today"], cwd=ROOT,
                       capture_output=True, text=True, env=env)
    out["steps"].append("daily candles: " + (r.stdout.strip().splitlines() or ["?"])[-1])
    r = subprocess.run([PY, "ops/eod_report.py", day.isoformat()], cwd=ROOT, capture_output=True, text=True, env=env)
    out["steps"].append("EOD report: " + (r.stdout.strip() or r.stderr[-300:]))
    r = subprocess.run([PY, "ops/build_package.py"], cwd=ROOT, capture_output=True, text=True, env=env)
    out["steps"].append("package: " + (r.stdout.strip().splitlines() or ["?"])[-1])
    out["steps"].append(f"still running: {[k for k, v in status(day)['jobs'].items() if v]}")
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    day = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date.today()
    fn = {"status": status, "morning": morning, "evening": evening}[cmd]
    res = fn(day)
    print(json.dumps(res, indent=1, default=str) if cmd == "status" else "\n".join(res["steps"]))
