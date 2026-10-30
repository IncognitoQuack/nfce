"""Watch the NFCE bridge; exit (with a reason) when something needs attention.

Exit codes: 0 = end time reached, 2 = health problem for 3+ checks,
3 = battery low, 4 = new incoming Telegram note/request.
"""
import datetime as dt, json, sqlite3, subprocess, sys, time, urllib.request

DB = "./data/nfce.db"
END = sys.argv[1] if len(sys.argv) > 1 else "15:40"
Q = "select coalesce(max(id),0) from events where source like 'telegram%' or source='admin'"

def db(q):
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)
    try:
        return c.execute(q).fetchall()
    finally:
        c.close()

base = db(Q)[0][0]
bad = 0
while True:
    now = dt.datetime.now()
    if now.strftime("%H:%M") >= END:
        print(f"{now:%H:%M} end time reached"); sys.exit(0)
    try:
        try:
            h = json.load(urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=10))
        except urllib.error.HTTPError as e:              # 503 = not ok; the body still has the details
            h = json.loads(e.read() or b"{}")
        known = "no fresh futures quotes for SENSEX"     # the known stale SENSEX feed: the account handles it
        ok = all(p == known for p in h.get("problems") or []) and "poll_beat" in h
        why = json.dumps({k: h.get(k) for k in ("ok", "problems", "engine", "scanner", "stocks3m", "last_error")})
    except Exception as e:
        ok, why = False, f"health unreachable: {e!r}"
    bad = 0 if ok else bad + 1
    if bad >= 3:
        print(f"{now:%H:%M} PROBLEM x{bad}: {why}"); sys.exit(2)
    batt = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout
    if "Battery Power" in batt:
        try:
            pct = int(batt.split("%")[0].split()[-1])
        except ValueError:
            pct = 100
        if pct <= 20:
            print(f"{now:%H:%M} BATTERY {pct}% and discharging"); sys.exit(3)
    new = db(Q)[0][0]
    if new > base:
        rows = db(f"select ts, source, substr(raw,1,500) from events where id > {base} and (source like 'telegram%' or source='admin') order by id")
        print(f"{now:%H:%M} NEW MESSAGES:"); [print(r) for r in rows]; sys.exit(4)
    time.sleep(60)
