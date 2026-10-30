"""News watcher (26 Oct 2026, owner: "from 11:45 see the news ... what works the best"): poll NSE's public corporate
announcements every 15 s and log each new one with its exchange dissemination time and the time we saw it.
F&O stocks are marked. Price reactions are scored after the close from the minute quotes that ops/collect.py records
(same day), so this script only logs: no trades, no messages. Writes to its own database.

usage (from nfce_bridge/): .venv/bin/python ops/news_watch.py <out.db> [end HH:MM]
"""
import datetime as dt, json, sqlite3, sys, time
import httpx

OUT, END = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "15:30")
H = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0 Safari/537.36",
     "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9",
     "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements"}
PAGE = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
API = "https://www.nseindia.com/api/corporate-announcements"

rows = json.load(open("data/instruments_NSE.json"))["rows"]
fno = {r["underlying_symbol"] for r in rows if r.get("instrument_type") == "FUT" and r.get("underlying_type") == "EQUITY"}

db = sqlite3.connect(OUT)
db.execute("""create table if not exists news (seq_id text primary key, symbol text, fno integer, an_dt text,
    disseminated text, seen text, category text, text text, attachment text)""")
seen = {r[0] for r in db.execute("select seq_id from news")}
client = httpx.Client(headers=H, timeout=30, follow_redirects=True)
client.get(PAGE)                                      # NSE sets its cookies on the page visit
fails = 0
while dt.datetime.now().strftime("%H:%M") < END:
    try:
        r = client.get(API, params={"index": "equities"})
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        items, fails = r.json(), 0
    except Exception as e:
        fails += 1
        print(dt.datetime.now().strftime("%H:%M:%S"), "fail", repr(e)[:100], flush=True)
        if fails % 3 == 0:                            # refresh cookies
            client.close(); client = httpx.Client(headers=H, timeout=30, follow_redirects=True)
            try:
                client.get(PAGE)
            except Exception:
                pass
        time.sleep(30); continue
    now = dt.datetime.now().isoformat(timespec="seconds")
    new = [x for x in items if x.get("seq_id") and x["seq_id"] not in seen]
    with db:
        for x in new:
            seen.add(x["seq_id"])
            db.execute("insert or ignore into news values (?,?,?,?,?,?,?,?,?)",
                       (x["seq_id"], x.get("symbol"), int(x.get("symbol") in fno), x.get("an_dt"),
                        x.get("exchdisstime"), now, x.get("desc"), (x.get("attchmntText") or "")[:500],
                        x.get("attchmntFile")))
    for x in new:
        if x.get("symbol") in fno:
            print(now[11:], "F&O", x.get("symbol"), "|", x.get("desc"), "|", (x.get("attchmntText") or "")[:90], flush=True)
    if len(new) >= len(items) and items:
        print(now[11:], "warning: all", len(items), "items new; some may have been missed", flush=True)
    time.sleep(15)
print("done", flush=True)
