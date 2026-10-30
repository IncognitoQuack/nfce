"""Pull 1-minute candles for every F&O stock (equity + front future), index spots/futures and VIX for the given days.
usage (from nfce_bridge/): PYTHONPATH=. .venv/bin/python pull1m.py <out_dir> 2026-10-21 2026-10-22
Saves <out_dir>/<day>/<SYMBOL>__<kind>.csv (ts, open, high, low, close, volume, oi).
"""
import datetime as dt, json, sys, time
from pathlib import Path
import httpx
from bridge.config import Settings

out, days = Path(sys.argv[1]), sys.argv[2:]
tok = json.load(open(Settings.from_env().token_file)); tok = tok.get("access_token", tok) if isinstance(tok, dict) else tok
H = {"Authorization": f"Bearer {tok}", "Accept": "application/json"}
rows = json.load(open("data/instruments_NSE.json"))["rows"]
today = dt.date.today()
front = {}
for r in rows:
    if r["instrument_type"] != "FUT" or r["underlying_type"] not in ("EQUITY", "INDEX"):
        continue
    exp = dt.datetime.fromtimestamp(r["expiry"] / 1000).date()
    if exp >= today and (r["underlying_symbol"] not in front or exp < front[r["underlying_symbol"]][0]):
        front[r["underlying_symbol"]] = (exp, r)
inst = []
for u, (_, r) in sorted(front.items()):
    if r["underlying_type"] == "EQUITY":
        inst += [(u, "eq", r["underlying_key"]), (u, "fut", r["instrument_key"])]
    elif u == "NIFTY":
        inst.append((u, "fut", r["instrument_key"]))
inst += [("NIFTY", "spot", "NSE_INDEX|Nifty 50"), ("SENSEX", "spot", "BSE_INDEX|SENSEX"),
         ("INDIAVIX", "spot", "NSE_INDEX|India VIX"), ("SENSEX", "fut", "BSE_FO|864571")]
print(len(inst), "instruments x", len(days), "days", flush=True)

def get(url):
    for attempt in range(4):
        r = httpx.get(url, headers=H, timeout=30)
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1)); continue
        r.raise_for_status()
        return r.json().get("data", {}).get("candles", [])
    return []

miss = 0
for day in days:
    d = out / day; d.mkdir(parents=True, exist_ok=True)
    for sym, kind, key in inst:
        f = d / f"{sym}__{kind}.csv"
        if f.exists():
            continue
        k = key.replace("|", "%7C")
        url = (f"https://api.upstox.com/v3/historical-candle/intraday/{k}/minutes/1" if day == today.isoformat()
               else f"https://api.upstox.com/v3/historical-candle/{k}/minutes/1/{day}/{day}")
        try:
            c = get(url)
        except Exception as e:
            print("fail", sym, kind, day, repr(e)[:120], flush=True); miss += 1; continue
        if not c:
            miss += 1
        f.write_text("ts,open,high,low,close,volume,oi\n" + "".join(",".join(map(str, x)) + "\n" for x in sorted(c)))
        time.sleep(0.25)
    print(day, "done", flush=True)
print("missing/empty:", miss)
