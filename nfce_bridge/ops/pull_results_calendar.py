"""Board meetings / results dates from NSE's public board-meeting list, month by month, gently (one request a second).
usage (from nfce_bridge/): .venv/bin/python ops/pull_results_calendar.py <out.csv> [from YYYY-MM] [to YYYY-MM]
Columns: symbol, date (YYYY-MM-DD), results (1 if the purpose mentions financial results), purpose."""
import csv
import sys
import time
from datetime import date, datetime

import httpx

H = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0 Safari/537.36",
     "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9",
     "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-board-meetings"}
out = sys.argv[1]
y0, m0 = map(int, (sys.argv[2] if len(sys.argv) > 2 else "2022-01").split("-"))
y1, m1 = map(int, (sys.argv[3] if len(sys.argv) > 3 else f"{date.today():%Y-%m}").split("-"))
rows, seen = [], set()
with httpx.Client(headers=H, timeout=30, follow_redirects=True) as c:
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        start = date(y, m, 1)
        end = date(y + (m == 12), m % 12 + 1, 1)
        params = {"index": "equities", "from_date": f"{start:%d-%m-%Y}",
                  "to_date": f"{date.fromordinal(end.toordinal() - 1):%d-%m-%Y}"}
        for attempt in range(3):
            r = c.get("https://www.nseindia.com/api/corporate-board-meetings", params=params)
            if r.status_code == 200:
                break
            time.sleep(5)
        data = r.json() if r.status_code == 200 else []
        for x in data:
            try:
                d = datetime.strptime(x["bm_date"], "%d-%b-%Y").date()
            except (KeyError, ValueError):
                continue
            purpose = " ".join(str(x.get(k, "")) for k in ("bm_purpose", "bm_desc"))
            key = (x.get("bm_symbol"), d)
            if key in seen:
                continue
            seen.add(key)
            rows.append({"symbol": x.get("bm_symbol"), "date": d.isoformat(),
                         "results": int("result" in purpose.lower()), "purpose": purpose[:200]})
        print(f"{y}-{m:02d}: {len(data)} meetings", flush=True)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        time.sleep(1)
with open(out, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["symbol", "date", "results", "purpose"])
    w.writeheader()
    w.writerows(rows)
print(f"saved {len(rows)} meetings ({sum(r['results'] for r in rows)} with results) to {out}")
