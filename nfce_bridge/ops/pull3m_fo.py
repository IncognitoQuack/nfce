"""Pull Upstox 3-minute history (2022-01 .. 2026-10-22) for every F&O stock (front-future universe), paced for
rate limits. Reuses the 50 already pulled. usage: python pull3m_fo.py <out_dir> <existing hist3m dir>"""
import datetime as dt
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
from bridge.config import Settings  # noqa: E402
from bridge.live_engine import frame  # noqa: E402
from bridge.providers import ProviderError, UpstoxProvider  # noqa: E402

OUT, OLD = Path(sys.argv[1]), Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
for f in OLD.glob("*_3m.pkl"):
    if not (OUT / f.name).exists():
        shutil.copy2(f, OUT / f.name)
INSTR = Path("./data/instruments_NSE.json")
today = dt.date.today()
keys = {}
for r in json.load(open(INSTR))["rows"]:
    if r["instrument_type"] == "FUT" and r["underlying_type"] == "EQUITY" and \
            dt.datetime.fromtimestamp(r["expiry"] / 1000).date() >= today:
        keys[r["underlying_symbol"]] = r["underlying_key"]
s = Settings.from_env()
prov = UpstoxProvider(s.token_file, instruments_cache=INSTR, min_interval_s=1.0)
todo = [k for k in sorted(keys) if not (OUT / f"{k}_3m.pkl").exists()]
print(f"{len(keys)} F&O stocks, {len(todo)} to pull", flush=True)
t0 = time.time()
for i, sym in enumerate(todo):
    for attempt in range(3):
        try:
            rows = prov.candles_5m(keys[sym], dt.date(2022, 1, 1), dt.date(2026, 10, 22), minutes=3)
            break
        except ProviderError as exc:
            print(sym, "retry", exc, flush=True)
            time.sleep(60)
    else:
        print(sym, "FAILED", flush=True)
        continue
    if not rows:
        print(sym, "no data", flush=True)
        continue
    d = frame(rows, 3)
    d.to_pickle(OUT / f"{sym}_3m.pkl")
    print(f"{i + 1}/{len(todo)} {sym} {len(d)} bars {d.index[0].date()}..{d.index[-1].date()}  {time.time() - t0:.0f}s", flush=True)
print("DONE", flush=True)
