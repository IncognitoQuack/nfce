"""Pull 5-minute history 2022-01 .. today for NIFTY, BANKNIFTY and India VIX (spot indices) into <out_dir>.
The older copies end on 2026-07-31; tests that need NIFTY state up to today use these.
usage (from nfce_bridge/): PYTHONPATH=. .venv/bin/python ops/pull_index5m.py <out_dir>
"""
import datetime as dt
import sys
from pathlib import Path

from bridge.config import Settings
from bridge.live_engine import frame
from bridge.providers import UpstoxProvider

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
s = Settings.from_env()
prov = UpstoxProvider(s.token_file, instruments_cache=Path("data/instruments_NSE.json"), min_interval_s=1.0)
for sym, key in (("NIFTY", "NSE_INDEX|Nifty 50"), ("BANKNIFTY", "NSE_INDEX|Nifty Bank"), ("INDIAVIX", "NSE_INDEX|India VIX")):
    rows = prov.candles_5m(key, dt.date(2022, 1, 1), dt.date.today(), minutes=5)
    d = frame(rows, 5)
    d.to_pickle(OUT / f"{sym}_5m.pkl")
    print(sym, len(d), d.index[0], d.index[-1], flush=True)
print("DONE")
