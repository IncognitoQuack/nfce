"""`nfce`: the NFCE control panel (owner, 22 Oct 2026 evening). One terminal command to run, watch, check, repair and
set up the whole system. With no arguments it opens an interactive menu.

Standard library only at import time, so it also runs on a new Mac before the virtual environment exists
(`nfce setup` builds it). Nothing here places orders: the system is paper trading only.

Rules it keeps (owner's standing rules):
* the Upstox sign-in is always done by the owner in the browser: `nfce login` only opens the page;
* keys and passwords are typed by the owner (hidden input), never invented or printed in full;
* money records (the account ledgers) are checked, never edited automatically;
* no background process runs unless the owner turns it on (`nfce supervisor on`).
"""
from __future__ import annotations

import getpass
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

BRIDGE = Path(__file__).resolve().parent.parent          # nfce_bridge/
REPO = BRIDGE.parent
VENV_PY = BRIDGE / ".venv" / "bin" / "python"
ENV_FILE, ENV_EXAMPLE = BRIDGE / ".env", BRIDGE / ".env.example"
DB = BRIDGE / "data" / "nfce.db"
LOGS = Path.home() / "Library" / "Logs"
BRIDGE_LOG, SUP_LOG = LOGS / "nfce_bridge.log", LOGS / "nfce_offline_bot.log"
MAINT = Path.home() / ".nfce_maintenance"
AGENT = Path.home() / "Library" / "LaunchAgents" / "com.nfce.supervisor.plist"
AGENT_LABEL = "com.nfce.supervisor"
HEALTH = "http://127.0.0.1:8000/health"
BRIDGE_PROC = "[-]m bridge[.]start"     # never a leading "-": pgrep would read it as an option (23 Oct)
REQUIRED = ("UPSTOX_API_KEY", "UPSTOX_API_SECRET", "UPSTOX_REDIRECT_URI", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
            "TELEGRAM_ADMIN_CHAT_IDS")
SECRET = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD)", re.I)
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

# ---------------------------------------------------------------- look and feel
_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def ok(msg: str) -> None:
    print(f"  {c('✔', '32')} {msg}")


def warn(msg: str) -> None:
    print(f"  {c('!', '33;1')} {msg}")


def bad(msg: str) -> None:
    print(f"  {c('✘', '31;1')} {msg}")


def info(msg: str) -> None:
    print(f"  {c('·', '36')} {msg}")


def title(text: str) -> None:
    print("\n" + c(f" {text} ", "1;37;44") + "\n")


def ask(prompt: str, default: bool = False) -> bool:
    if not sys.stdin.isatty():
        return default
    a = input(f"  {prompt} [{'Y/n' if default else 'y/N'}] ").strip().lower()
    return default if not a else a in ("y", "yes")


# ---------------------------------------------------------------- .env helpers (tested)
def parse_env(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        k, sep, v = line.strip().partition("=")
        if sep and not k.startswith("#") and KEY_RE.match(k.strip()):
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def mask(key: str, value: str) -> str:
    if not value:
        return "(empty)"
    if not SECRET.search(key):
        return value
    return f"{value[:4]}…{value[-2:]} ({len(value)} chars)" if len(value) > 8 else f"•••• ({len(value)} chars)"


def set_env_value(text: str, key: str, value: str) -> str:
    """Replace KEY=... in place (comments and order kept), or append it. Refuses keys or values that could inject."""
    if not KEY_RE.match(key):
        raise ValueError(f"not a valid key: {key!r}")
    if "\n" in value or "\r" in value:
        raise ValueError("a value cannot contain a line break")
    lines, done = text.splitlines(), False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}=") and not done:
            lines[i], done = f"{key}={value}", True
    if not done:
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def missing_keys(env: dict) -> list[str]:
    return [k for k in REQUIRED if not env.get(k)]


# ---------------------------------------------------------------- probes
def sh(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def bridge_running() -> bool:
    return sh(["pgrep", "-f", BRIDGE_PROC]).returncode == 0


def supervisor_running() -> bool:
    return sh(["pgrep", "-f", "bridge.offline_bot"]).returncode == 0


def health() -> dict | None:
    try:
        with urllib.request.urlopen(HEALTH, timeout=3) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:                    # 503 = running but not ok; the body has the details
        try:
            return json.loads(e.read() or b"{}")
        except ValueError:
            return {}
    except (urllib.error.URLError, OSError, ValueError):
        return None


def in_market(now: datetime | None = None) -> bool:
    n = now or datetime.now()
    return n.weekday() < 5 and 9 * 60 + 15 <= n.hour * 60 + n.minute <= 15 * 60 + 30


def power() -> tuple[bool | None, int | None]:
    out = sh(["pmset", "-g", "batt"]).stdout
    m = re.search(r"(\d+)%", out)
    return ("AC Power" in out) if out else None, int(m.group(1)) if m else None


def venv_ok() -> bool:
    if not VENV_PY.exists():
        return False
    r = sh([str(VENV_PY), "-c", "import fastapi, uvicorn, httpx, numpy, pandas, sklearn, websockets, google.protobuf; "
            "assert numpy.__version__=='2.5.4' and pandas.__version__=='3.0.6' and sklearn.__version__=='1.9.1'"])
    return r.returncode == 0


def in_venv(code: str) -> subprocess.CompletedProcess:
    """Run a snippet with the project's python (the bridge package and its pinned libraries)."""
    return sh([str(VENV_PY), "-c", code], cwd=BRIDGE)


def token_line() -> tuple[bool, str]:
    r = in_venv("from bridge.check_setup import token_status; from bridge.config import Settings; "
                "ok, m = token_status(Settings.from_env().token_file); print(int(ok)); print(m)")
    if r.returncode:
        return False, "token status unknown (environment not ready)"
    flag, _, msg = r.stdout.strip().partition("\n")
    return flag == "1", msg


def hung(h: dict | None) -> bool:
    beat = (h or {}).get("poll_beat")
    if not beat or not in_market():
        return False
    try:
        return (datetime.now().astimezone() - datetime.fromisoformat(beat)).total_seconds() > 300
    except ValueError:
        return False


def state() -> dict:
    env = parse_env(ENV_FILE.read_text()) if ENV_FILE.exists() else {}
    h = health()
    v = venv_ok()
    st = dict(venv_ok=v, env_missing=missing_keys(env), supervisor=supervisor_running(), maintenance=MAINT.exists(),
              bridge_proc=bridge_running(), health=h, in_market=in_market(), on_ac=power()[0] is not False,
              db_ok=True, ledger_problems=[], log_mb=BRIDGE_LOG.stat().st_size / 1e6 if BRIDGE_LOG.exists() else 0.0,
              disk_gb=shutil.disk_usage(BRIDGE).free / 1e9, hung=hung(h), token_ok=True,
              port_other=bool(h is None and sh(["lsof", "-ti", ":8000"]).stdout.strip()))
    if DB.exists():
        try:
            con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
            st["db_ok"] = con.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            con.close()
        except sqlite3.Error:
            st["db_ok"] = False
    if v:
        st["token_ok"] = token_line()[0]
        r = in_venv("from bridge.preflight import ledger_problems; from bridge.config import Settings; "
                    "from bridge.store import Store; s = Settings.from_env(); "
                    "print('\\n'.join(ledger_problems(Store(s.db_path), s.accounts)))")
        st["ledger_problems"] = [x for x in r.stdout.splitlines() if x.strip()]
    return st


# ---------------------------------------------------------------- the repair plan (tested)
def diagnose(s: dict) -> list[tuple[str, str, str | None]]:
    """(level, message, action): level 'fix' = repairable here, 'report' = needs a person, 'info' = optional."""
    out: list[tuple[str, str, str | None]] = []
    if not s["supervisor"]:
        out.append(("info", "supervisor is off (optional, self-healing during market hours: nfce supervisor on)", None))
    if not s["venv_ok"]:
        out.append(("fix", "Python environment missing or wrong library versions", "rebuild_venv"))
    if s["env_missing"]:
        out.append(("fix", f".env is missing: {', '.join(s['env_missing'])}", "ask_env"))
    if not s["db_ok"]:
        out.append(("fix", "database integrity check failed", "restore_db"))
    for p in s["ledger_problems"]:
        out.append(("report", f"{p} (money records are never edited automatically: check the ledger)", None))
    if s["maintenance"] and not (s["in_market"] and not s["bridge_proc"]):
        out.append(("fix", "a leftover maintenance switch (~/.nfce_maintenance)", "clear_maintenance"))
    if s["bridge_proc"] and s["hung"]:
        out.append(("fix", "the bridge is running but its market loop is silent (> 5 min)", "restart_bridge"))
    if s["port_other"]:
        out.append(("report", "port 8000 is used by another program (the bridge cannot start there)", None))
    if not s["token_ok"]:
        out.append(("fix", "the Upstox token is missing or expired (you sign in)", "login"))
    if s["log_mb"] > 200:
        out.append(("fix", f"the bridge log is {s['log_mb']:.0f} MB", "rotate_logs"))
    if not s["on_ac"]:
        out.append(("report", "the Mac is on battery: connect the charger and keep the lid open", None))
    if s["disk_gb"] < 2:
        out.append(("report", f"only {s['disk_gb']:.1f} GB of disk free", None))
    return out


# ---------------------------------------------------------------- commands
def cmd_status(args) -> int:
    title("NFCE · status")
    h = health()
    if bridge_running() and h is not None:
        good = h.get("ok")
        (ok if good else warn)(f"bridge running · health {'ok' if good else 'NOT ok: ' + '; '.join(h.get('problems', []))}")
        for k in ("engine", "scanner", "stocks3m"):
            if h.get(k):
                info(f"{k}: {h[k] if not isinstance(h[k], dict) else ', '.join(f'{a} {b}' for a, b in h[k].items())}")
        if h.get("last_error"):
            info(f"last error: {h['last_error']}")
    elif bridge_running():
        warn("bridge process exists but /health does not answer (starting, or stuck)")
    else:
        info("bridge stopped" + (" (market hours!)" if in_market() else ""))
    (ok if supervisor_running() else info)("supervisor " + ("running" if supervisor_running() else "off (optional)"))
    if MAINT.exists():
        warn("maintenance switch is ON (~/.nfce_maintenance)")
    ac, pct = power()
    (ok if ac else warn)(f"power: {'charger' if ac else 'BATTERY'} ({pct}%)")
    if VENV_PY.exists():
        t_ok, t_msg = token_line()
        (ok if t_ok else warn)(t_msg)
        r = in_venv("import re; from bridge.app import build_bridge_parts; from bridge.offline_bot import OfflineBot; "
                    "s, st, tg = build_bridge_parts(); ob = OfflineBot(s, st, tg, bridge_up=lambda: True); "
                    "print('\\n'.join(re.sub('<[^>]+>', '', a.summary_line()) for a in ob._accounts()))")
        if r.stdout.strip():
            print(c("\n  Paper accounts", "1"))
            for line in r.stdout.strip().splitlines():
                print("   " + line)
        j = sh([str(VENV_PY), str(BRIDGE / "ops" / "runbook.py"), "status"], cwd=BRIDGE,
               env=dict(os.environ, PYTHONPATH=str(BRIDGE)))
        try:
            jobs_ = json.loads(j.stdout)["jobs"]
            print(c("\n  Today's jobs", "1") + "  " + "  ".join(f"{n} {'✔' if v else '·'}" for n, v in jobs_.items()))
        except (ValueError, KeyError):
            pass
    _recent(3)
    return 0


def _recent(n: int) -> None:
    if not DB.exists():
        return
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
    try:
        sent = con.execute("SELECT ts, text FROM sent_messages ORDER BY id DESC LIMIT ?", (n,)).fetchall()
        got = con.execute("SELECT ts, raw FROM events WHERE source LIKE 'telegram%' ORDER BY id DESC LIMIT ?",
                          (n,)).fetchall()
    except sqlite3.Error:
        return
    finally:
        con.close()
    fmt = lambda ts: datetime.fromisoformat(ts).astimezone().strftime("%d %b %H:%M")
    print(c("\n  Latest messages out", "1"))
    for ts, t in sent:
        print(f"   {fmt(ts)}  {re.sub('<[^>]+>', '', t).splitlines()[0][:90]}")
    print(c("  Latest messages in", "1"))
    for ts, raw in got:
        print(f"   {fmt(ts)}  {json.loads(raw).get('text', '')[:90]}")


def _stop_processes() -> bool:
    sh(["pkill", "-f", "nfce_bridge/start.sh"])
    sh(["pkill", "-TERM", "-f", BRIDGE_PROC])
    for _ in range(20):
        if not bridge_running():
            return True
        time.sleep(0.5)
    sh(["pkill", "-KILL", "-f", BRIDGE_PROC])
    return not bridge_running()


def cmd_start(args) -> int:
    title("NFCE · start")
    if bridge_running():
        ok("already running")
        return 0
    if not venv_ok():
        bad("the Python environment is not ready: run  nfce setup")
        return 1
    if MAINT.exists():
        MAINT.unlink()
        info("maintenance switch cleared")
    r = sh([str(VENV_PY), "-m", "bridge.preflight"], cwd=BRIDGE)
    for line in r.stdout.splitlines():
        if "[!!]" in line:
            warn(line.replace("[!!]", "").strip())
    t_ok, msg = token_line()
    if not t_ok:
        warn(f"{msg}: a browser window opens; please sign in to Upstox there (the system waits up to 5 minutes)")
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(BRIDGE_LOG, "a") as logf:
        subprocess.Popen(["bash", str(BRIDGE / "start.sh")], cwd=BRIDGE, stdout=logf, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True)   # detached: closing the terminal is safe
    info("starting (detached; log: ~/Library/Logs/nfce_bridge.log) …")
    for _ in range(360 if not t_ok else 60):
        if health() is not None:
            ok("running: health answers")
            return 0
        time.sleep(1)
    warn("not answering yet; see  nfce logs")
    return 1


def cmd_stop(args) -> int:
    title("NFCE · stop")
    if not bridge_running():
        info("already stopped")
        return 0
    if in_market():
        MAINT.write_text(datetime.now().isoformat())
        warn("market hours: maintenance switch set so nothing restarts it (nfce start clears it)")
    (ok if _stop_processes() else bad)("stopped" if not bridge_running() else "could not stop it")
    return 0 if not bridge_running() else 1


def cmd_restart(args) -> int:
    cmd_stop(args)
    return cmd_start(args)


def cmd_login(args) -> int:
    title("NFCE · Upstox sign-in")
    info("a browser window opens: please sign in there yourself (your password is never typed by this tool)")
    return subprocess.call([str(VENV_PY), "-m", "bridge.upstox_login"], cwd=BRIDGE)


def cmd_check(args) -> int:
    title("NFCE · check")
    rc = subprocess.call([str(VENV_PY), "-m", "bridge.preflight"], cwd=BRIDGE)
    if "--live" in args:
        info("live check (Upstox + Telegram; sends one Telegram test message)")
        rc |= subprocess.call([str(VENV_PY), "-m", "bridge.check_setup"], cwd=BRIDGE)
    return rc


def _rebuild_venv() -> bool:
    py = shutil.which("python3")
    if not py:
        bad("python3 not found: install it (for example `brew install python@3.14`) and run nfce setup again")
        return False
    if not VENV_PY.exists():
        subprocess.call([py, "-m", "venv", str(BRIDGE / ".venv")])
    info("installing the pinned packages from PyPI (requirements.txt) …")
    return subprocess.call([str(VENV_PY), "-m", "pip", "install", "-q", "-r", str(BRIDGE / "requirements.txt")]) == 0


def _restore_db() -> bool:
    backups = sorted((BRIDGE / "data" / "backups").glob("nfce_*.db"))
    if not backups:
        bad("no backup in data/backups to restore from")
        return False
    src = backups[-1]
    if not ask(f"restore the database from {src.name}? (the damaged file is kept as nfce.db.broken)"):
        return False
    shutil.move(str(DB), str(DB) + ".broken")
    shutil.copy2(src, DB)
    return True


def _rotate_logs() -> bool:
    dst = BRIDGE_LOG.with_suffix(f".{datetime.now():%Y%m%d}.log")
    shutil.move(str(BRIDGE_LOG), dst)
    info(f"old log kept as {dst.name}")
    return True


def cmd_fix(args) -> int:
    title("NFCE · diagnose and repair")
    plan = diagnose(state())
    if not [p for p in plan if p[0] != "info"]:
        ok("nothing to fix")
    actions = {"rebuild_venv": lambda: ask("rebuild the Python environment now?", True) and _rebuild_venv(),
               "ask_env": lambda: cmd_env(["setup"]) == 0,
               "restore_db": _restore_db,
               "clear_maintenance": lambda: (MAINT.unlink(), True)[1],
               "restart_bridge": lambda: ask("restart the stuck bridge now?", True) and cmd_restart([]) == 0,
               "login": lambda: ask("open the Upstox sign-in now?", False) and cmd_login([]) == 0,
               "rotate_logs": _rotate_logs}
    bad_left = 0
    for level, msg, action in plan:
        if level == "info":
            info(msg)
        elif level == "report":
            warn(msg)
            bad_left += 1
        else:
            done = False
            try:
                done = bool(actions[action]())
            except Exception as exc:                       # a failed repair is reported, never hidden
                bad(f"repair failed: {type(exc).__name__}: {exc}")
            (ok if done else warn)(("fixed: " if done else "still open: ") + msg)
            bad_left += not done
    return 1 if bad_left else 0


def cmd_logs(args) -> int:
    which = SUP_LOG if args and args[0] in ("supervisor", "offline") else BRIDGE_LOG
    n = next((int(a) for a in args if a.isdigit()), 40)
    if not which.exists():
        info(f"no log yet: {which}")
        return 0
    if "-f" in args:
        return subprocess.call(["tail", "-n", str(n), "-f", str(which)])
    lines = which.read_text(errors="replace").splitlines()[-n:]
    for line in lines:
        col = "31" if re.search(r"ERROR|Traceback|CRITICAL", line) else ("33" if "WARNING" in line else "0")
        print(c(line, col))
    return 0


def cmd_messages(args) -> int:
    title("NFCE · Telegram messages")
    _recent(next((int(a) for a in args if a.isdigit()), 10))
    return 0


def _venv_print(code: str) -> int:
    r = in_venv(code)
    print(re.sub("<[^>]+>", "", r.stdout) or r.stderr[-2000:])
    return r.returncode


def cmd_accounts(args) -> int:
    title("NFCE · paper accounts")
    return _venv_print("from bridge.app import build_bridge_parts; from bridge.offline_bot import OfflineBot; "
                       "s, st, tg = build_bridge_parts(); print(OfflineBot(s, st, tg, bridge_up=lambda: True)"
                       ".accounts_text())")


def cmd_report(args) -> int:
    title("NFCE · today")
    return _venv_print("from bridge.app import build_bridge_parts; from bridge.offline_bot import OfflineBot; "
                       "s, st, tg = build_bridge_parts(); ob = OfflineBot(s, st, tg, bridge_up=lambda: True); "
                       "print(ob.today()); print(); print(ob.risk())")


def _ops(script: str, *args: str, capture: bool = False):
    """Run an ops/ script with the project's python, from nfce_bridge/."""
    env = dict(os.environ, PYTHONPATH=str(BRIDGE))
    cmd = [str(VENV_PY), str(BRIDGE / "ops" / script), *args]
    if capture:
        return subprocess.run(cmd, cwd=BRIDGE, env=env, capture_output=True, text=True)
    return subprocess.call(cmd, cwd=BRIDGE, env=env)


def cmd_morning(args) -> int:
    title("NFCE · morning runbook")
    if not bridge_running():
        bad("the bridge is not running: run `nfce start` first (the owner signs in), then `nfce morning`")
        return 1
    return _ops("runbook.py", "morning")


def cmd_evening(args) -> int:
    title("NFCE · evening runbook")
    if in_market() and not (args and args[0] == "--now"):
        bad("the market is still open: `nfce evening` stops the bridge. After 15:35, or `nfce evening --now`")
        return 1
    return _ops("runbook.py", "evening")


def cmd_jobs(args) -> int:
    title("NFCE · today's background jobs")
    r = _ops("runbook.py", "status", *args[:1], capture=True)
    try:
        st = json.loads(r.stdout)
    except ValueError:
        print(r.stdout or r.stderr[-1500:])
        return 1
    (ok if st["bridge"] == "up" else info)(f"bridge {st['bridge']}" + (f" · GS {st['gs']}" if st.get("gs") else ""))
    for name, up in st["jobs"].items():
        (ok if up else info)(f"{name:7s} {'running' if up else 'not running'}")
    return 0


def cmd_desk(args) -> int:
    title("NFCE · trading desk")
    url = "http://127.0.0.1:8001"
    r = _ops("runbook.py", "status", capture=True)
    try:
        running_ = json.loads(r.stdout)["jobs"]["desk"]
    except (ValueError, KeyError):
        running_ = False
    if not running_:
        s = subprocess.run([str(VENV_PY), "-c", "from datetime import date; from ops import runbook as rb; "
                            "j = [x for x in rb.jobs(date.today()) if x['name'] == 'desk'][0]; print(rb.start(j, date.today()))"],
                           cwd=BRIDGE, env=dict(os.environ, PYTHONPATH=str(BRIDGE)), capture_output=True, text=True)
        (ok if s.returncode == 0 else bad)(f"desk started (pid {s.stdout.strip()})" if s.returncode == 0 else s.stderr[-500:])
        time.sleep(2)
    else:
        ok("desk already running")
    info(f"open {url}  (safe in market hours; on this Mac no token is needed; phone links: System tab)")
    if sys.platform == "darwin" and not (args and args[0] == "--no-open"):
        subprocess.call(["open", url])
    return 0


def cmd_eod(args) -> int:
    title("NFCE · end-of-day analysis")
    r = _ops("eod_report.py", *args[:1], capture=True)
    if r.returncode != 0:
        bad(r.stderr[-1500:])
        return r.returncode
    path = Path(r.stdout.strip().splitlines()[-1])
    ok(f"written: {path}")
    print(path.read_text()[:4000])
    return 0


def cmd_research(args) -> int:
    title("NFCE · research tracks (OVN v2 / v3, OPX-1, SCALP-1)")
    day = args[0] if args else datetime.now().date().isoformat()
    code = ("import json, sys; sys.path.insert(0, '../nfce_engine'); from ops import eod_report as e; "
            f"r = e.research('{day}'); r.pop('gs', None); print(json.dumps(r, indent=1, default=str)[:6000])")
    r = in_venv(code)
    print(r.stdout or r.stderr[-1500:])
    return r.returncode


def cmd_test(args) -> int:
    title("NFCE · tests")
    a = subprocess.call([str(VENV_PY), "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=BRIDGE)
    b = subprocess.call([str(VENV_PY), "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=REPO / "nfce_engine")
    (ok if not (a or b) else bad)(f"bridge {'passed' if not a else 'FAILED'} · engine {'passed' if not b else 'FAILED'}")
    return a or b


def cmd_verify(args) -> int:
    """Everything that must hold before any restart (MASTER_SYSTEM_PLAN.md L7). 28 Oct's desk NaN and desk sign bug
    would both have failed it. Power and an expired token are reported but are not code faults."""
    title("NFCE · verify")
    env = dict(os.environ, PYTHONPATH=str(BRIDGE))
    eng = REPO / "nfce_engine"
    results = []

    def run(name, cmd, cwd=BRIDGE, judge=None):
        r = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, capture_output=True, text=True)
        out = (r.stdout + r.stderr).strip().splitlines()
        good = judge(out) if judge else r.returncode == 0
        results.append(good)
        (ok if good else bad)(f"{name}: {out[-1] if out else ('ok' if good else 'failed')}")

    run("compile sweep", [VENV_PY, "-m", "compileall", "-q", "bridge", "ops", eng / "tools", eng / "nfx", eng / "gs"])
    run("imports", [VENV_PY, "-c", "import bridge.service, bridge.admin_api, ops.desk, ops.runbook; print('ok')"])
    run("bridge tests", [VENV_PY, "-m", "pytest", "-q", "-p", "no:cacheprovider"])
    run("engine tests", [VENV_PY, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=eng)
    run("preflight (frozen files, database, ledgers)", [VENV_PY, "-m", "bridge.preflight"],
        judge=lambda out: not [x for x in out if "[!!]" in x and "power:" not in x and "Upstox token" not in x])
    run("desk smoke (strict JSON)", [VENV_PY, "-c", "import json; from ops import desk; json.dumps(desk.json_safe("
                                     "desk.snapshot(with_live=False, with_research=False)), allow_nan=False); print('ok')"])
    good = all(results)
    (ok if good else bad)("VERIFIED: safe to restart" if good else "NOT verified: fix the failures above first")
    return 0 if good else 1


def cmd_study(args) -> int:
    title("NFCE · after-close study")
    if bridge_running():
        warn("the bridge is still running: the study is meant for after the close")
    env = dict(os.environ, PYTHONPATH=str(BRIDGE))
    return subprocess.call([str(VENV_PY), str(BRIDGE / "ops" / "day_study.py")], cwd=BRIDGE, env=env)


def cmd_backup(args) -> int:
    title("NFCE · backup")
    dst = BRIDGE / "data" / "backups" / f"nfce_{datetime.now():%Y%m%d_%H%M}.db"
    dst.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(DB)
    out = sqlite3.connect(dst)
    with out:
        src.backup(out)                                     # consistent copy even while the bridge writes
    src.close()
    out.close()
    ok(f"{dst.name} ({dst.stat().st_size / 1e6:.1f} MB)")
    return 0


def cmd_supervisor(args) -> int:
    sub = args[0] if args else "status"
    uid = str(os.getuid())
    if sub in ("on", "install"):
        tpl = (BRIDGE / "ops" / "com.nfce.supervisor.plist").read_text()
        AGENT.parent.mkdir(parents=True, exist_ok=True)
        AGENT.write_text(tpl.replace("__BRIDGE__", str(BRIDGE)).replace("__HOME__", str(Path.home())))
        sh(["launchctl", "bootout", f"gui/{uid}/{AGENT_LABEL}"])
        r = sh(["launchctl", "bootstrap", f"gui/{uid}", str(AGENT)])
        (ok if r.returncode == 0 else bad)("supervisor on: starts at login, answers Telegram while the bridge is "
                                           "down, restarts a bridge that died in market hours" if r.returncode == 0
                                           else f"could not load it: {r.stderr.strip()}")
        return r.returncode
    if sub in ("off", "uninstall"):
        sh(["launchctl", "bootout", f"gui/{uid}/{AGENT_LABEL}"])
        AGENT.unlink(missing_ok=True)
        sh(["pkill", "-f", "bridge.offline_bot"])
        ok("supervisor off: nothing runs in the background")
        return 0
    (ok if supervisor_running() else info)("supervisor " + ("running" if supervisor_running() else "off"))
    info("auto-start at login: " + ("yes" if AGENT.exists() else "no"))
    return 0


def cmd_env(args) -> int:
    if not ENV_FILE.exists():
        if not ENV_EXAMPLE.exists():
            bad(".env.example not found")
            return 1
        shutil.copy2(ENV_EXAMPLE, ENV_FILE)
        os.chmod(ENV_FILE, 0o600)
        info(".env created from .env.example")
    text = ENV_FILE.read_text()
    env = parse_env(text)
    if args and args[0] == "set" and len(args) > 1:
        keys = [args[1]]
    elif args and args[0] == "setup":
        keys = missing_keys(env)
    else:
        title("NFCE · .env (secrets masked)")
        for k, v in env.items():
            print(f"   {k:28s} {mask(k, v)}")
        for k in missing_keys(env):
            warn(f"{k} is empty: nfce env set {k}")
        return 0
    for k in keys:
        if not sys.stdin.isatty():
            bad(f"{k}: needs a terminal to type the value")
            return 1
        prompt = f"  {k} (typed hidden): " if SECRET.search(k) else f"  {k}: "
        v = (getpass.getpass(prompt) if SECRET.search(k) else input(prompt)).strip()
        if v:
            text = set_env_value(text, k, v)
            ok(f"{k} saved ({mask(k, v)})")
    ENV_FILE.write_text(text)
    os.chmod(ENV_FILE, 0o600)
    return 0


def cmd_setup(args) -> int:
    title("NFCE · set up / repair on this Mac")
    if sys.version_info < (3, 11):
        bad(f"Python {sys.version.split()[0]} is too old: install Python 3.11+ and run nfce setup again")
        return 1
    if venv_ok():
        ok("Python environment ready (pinned libraries)")
    elif ask("create the Python environment and install the packages now?", True):
        if not _rebuild_venv() or not venv_ok():
            bad("package installation failed (see above)")
            return 1
        ok("Python environment ready")
    cmd_env(["setup"])
    (BRIDGE / "data").mkdir(exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    r = sh([str(VENV_PY), "-c", "from pathlib import Path; from bridge.check_setup import ensure_webhook_secret as e; "
            "print(e(Path('.env')))"], cwd=BRIDGE)
    if r.stdout.strip() == "True":
        ok("WEBHOOK_SECRET generated")
    install_command()
    if ask("turn on the supervisor (a small background program that answers Telegram while the system is off "
           "and restarts it after a crash in market hours)?", False):
        cmd_supervisor(["on"])
    else:
        info("supervisor left off (nfce supervisor on, any time)")
    if ask("run the tests now?", True):
        cmd_test([])
    cmd_check([])
    info("next: nfce login (Upstox sign-in), then nfce start on a market morning")
    return 0


def install_command() -> None:
    target = Path.home() / ".local" / "bin" / "nfce"
    target.parent.mkdir(parents=True, exist_ok=True)
    launcher = BRIDGE / "nfce"
    if target.is_symlink() or target.exists():
        target.unlink()
    target.symlink_to(launcher)
    on_path = str(target.parent) in os.environ.get("PATH", "").split(":")
    ok(f"command installed: {target}" + ("" if on_path else "  (add ~/.local/bin to your PATH)"))


COMMANDS = [
    ("status", cmd_status, "dashboard: bridge, health, power, token, accounts, latest messages"),
    ("start", cmd_start, "start the system (detached; checks first; sign-in if the token expired)"),
    ("stop", cmd_stop, "stop the system (in market hours it also sets the maintenance switch)"),
    ("restart", cmd_restart, "stop, then start"),
    ("login", cmd_login, "Upstox sign-in in the browser (you sign in)"),
    ("check", cmd_check, "preflight self-check; `check --live` also tests Upstox and Telegram"),
    ("fix", cmd_fix, "diagnose and repair what can be repaired; report the rest"),
    ("logs", cmd_logs, "recent log lines: `logs [supervisor] [N] [-f]`"),
    ("messages", cmd_messages, "recent Telegram messages, in and out"),
    ("accounts", cmd_accounts, "the six paper accounts side by side"),
    ("report", cmd_report, "today's results and open risk"),
    ("morning", cmd_morning, "after `start` + sign-in: recorders, stream, desk (each once) and the news brief"),
    ("evening", cmd_evening, "after 15:35: stop, refresh daily candles, EOD report, package"),
    ("jobs", cmd_jobs, "which of today's background jobs are running"),
    ("desk", cmd_desk, "open the trading desk (starts it if needed): http://127.0.0.1:8001"),
    ("eod", cmd_eod, "write and show the end-of-day analysis: `eod [YYYY-MM-DD]`"),
    ("research", cmd_research, "score the research tracks now: OVN v2/v3, OPX-1, SCALP-1"),
    ("test", cmd_test, "run both test suites"),
    ("verify", cmd_verify, "before any restart: compile, imports, both suites, frozen files, desk smoke test"),
    ("study", cmd_study, "after-close study (losses, recoveries, variants)"),
    ("backup", cmd_backup, "a consistent database backup now"),
    ("supervisor", cmd_supervisor, "`supervisor on|off|status`: optional background self-healing"),
    ("setup", cmd_setup, "install or repair on this Mac: environment, .env keys, command, checks"),
    ("env", cmd_env, "show .env (masked) · `env set KEY` · `env setup` asks for missing keys"),
]


def cmd_help(args=None) -> int:
    print(c("NFCE control panel", "1") + "  ·  paper trading only, never places orders\n")
    print("usage: nfce [command]   (no command: the interactive menu)\n")
    for name, _, doc in COMMANDS:
        print(f"  {name:11s} {doc}")
    print("  help        this list")
    return 0


def menu() -> int:
    while True:
        cmd_status([])
        print(c("\n  Menu", "1"))
        for i, (name, _, doc) in enumerate(COMMANDS, 1):
            print(f"  {i:2d}  {name:11s} {c(doc, '2')}")
        print("   q  quit")
        try:
            a = input("\n  choose: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if a in ("q", "quit", "exit", ""):
            return 0
        chosen = COMMANDS[int(a) - 1] if a.isdigit() and 1 <= int(a) <= len(COMMANDS) else \
            next((x for x in COMMANDS if x[0] == a), None)
        if not chosen:
            warn("unknown choice")
            continue
        try:
            chosen[1]([])
        except KeyboardInterrupt:
            print()
        input(c("\n  press Enter to go back to the menu", "2"))


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        return menu() if sys.stdin.isatty() else cmd_help()
    name, args = argv[0].lstrip("-"), argv[1:]
    if name in ("help", "h"):
        return cmd_help()
    for n, f, _ in COMMANDS:
        if n == name:
            try:
                return f(args)
            except KeyboardInterrupt:
                print()
                return 130
    bad(f"unknown command {name!r}")
    cmd_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
