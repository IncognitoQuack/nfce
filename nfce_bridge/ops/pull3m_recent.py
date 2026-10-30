"""Pull Upstox 3-minute candles for a few recent days (default 2026-10-20 .. 2026-10-26) for every F&O stock and India
VIX into their own folder (one request per symbol, ~214 in all), for the GS-SIP-1 replay of the recorded live days.
Read-only use of Upstox; never touches nfce_data/hist3m_fo or the live databases.

usage (from nfce_bridge/): PYTHONPATH=. .venv/bin/python ops/pull3m_recent.py ~/Downloads/nfce_data/hist3m_recent [from to]
"""
import datetime as dt
import sys
import time
from pathlib import Path

from bridge.config import Settings
from bridge.live_engine import frame
from bridge.providers import ProviderError, UpstoxProvider

OUT = Path(sys.argv[1]).expanduser()
A = dt.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else dt.date(2026, 10, 20)
B = dt.date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else dt.date(2026, 10, 26)
OUT.mkdir(parents=True, exist_ok=True)
s = Settings.from_env()
p = UpstoxProvider(s.token_file, min_interval_s=0.35, instruments_cache=s.db_path.parent / "instruments_NSE.json")
uni = {u["symbol"]: u["equity_key"] for u in p.fno_stocks(dt.date.today())}
uni["INDIAVIX"] = "NSE_INDEX|India VIX"
done = 0
for sym, key in sorted(uni.items()):
    for attempt in range(3):
        try:
            rows = p.candles_5m(key, A, B, minutes=3)
            frame(rows, 3).to_pickle(OUT / f"{sym}_3m.pkl")
            done += 1
            break
        except ProviderError as e:
            print(sym, "retry", attempt, str(e)[:100], flush=True)
            time.sleep(5 * (attempt + 1))
print(f"done: {done}/{len(uni)} symbols, {A}..{B} -> {OUT}", flush=True)
