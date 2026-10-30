"""Download NSE bars from Yahoo Finance (free, no key) into data/yahoo/, validated, with a SHA-256 manifest.

  pip install yfinance
  python tools/fetch_yahoo.py                 # 5m, last ~60 days: indices, VIX, ETFs, heavyweights
  python tools/fetch_yahoo.py --interval 60m  # ^NSEI and ^NSEBANK hourly, Yahoo's maximum (~730 calendar days)
  python tools/fetch_yahoo.py --interval 15m  # ^NSEI and ^NSEBANK 15m, last ~60 days
  python tools/fetch_yahoo.py --interval 1d   # ^NSEI and ^NSEBANK daily, full history

Index symbols (^NSEI, ^NSEBANK, ^INDIAVIX) carry no volume; stocks and ETFs do. A file is written only after it
passes nfce.data.validate (FIX v2, review L03: an empty or rate-limited response used to crash or save junk).
Yahoo's terms restrict redistribution: the CSVs are for personal research and are not part of the shared package.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce.data import DataError, normalise, update_manifest, validate  # noqa: E402

FIVE_MIN = ["^NSEI", "^NSEBANK", "^INDIAVIX", "NIFTYBEES.NS", "BANKBEES.NS", "HDFCBANK.NS", "ICICIBANK.NS",
            "RELIANCE.NS", "INFY.NS", "BHARTIARTL.NS", "SBIN.NS", "KOTAKBANK.NS", "AXISBANK.NS"]
PERIOD = {"5m": "60d", "15m": "60d", "60m": "730d", "1d": "max"}
OUT = Path(__file__).resolve().parent.parent / "data" / "yahoo"


def fetch(symbol: str, interval: str, period: str, tries: int = 3):
    import yfinance as yf
    last = None
    for k in range(tries):
        try:
            d = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=False,
                            multi_level_index=False)
            return normalise(d, f"{symbol} {interval}")
        except DataError as e:          # empty response: often a rate limit, so wait and retry
            last = e
            time.sleep(5 * (k + 1))
    raise last


def main(interval: str, out: Path = OUT) -> int:
    out.mkdir(parents=True, exist_ok=True)
    symbols = FIVE_MIN if interval == "5m" else ["^NSEI", "^NSEBANK"]
    failed = 0
    for s in symbols:
        name = s.replace("^", "").replace(".NS", "")
        try:
            d = fetch(s, interval, PERIOD[interval])
            mins = None if interval == "1d" else int(interval[:-1])
            summary = validate(d, f"{s} {interval}", mins, drop_off_session=True)
        except DataError as e:
            print(f"{s}: NOT SAVED - {e}")
            failed += 1
            continue
        f = out / f"{name}_{interval}.csv"
        d.to_csv(f)
        entry = update_manifest(out, f, symbol=s, interval=interval, requested=PERIOD[interval],
                                source="Yahoo Finance via yfinance (personal research use)")
        print(f"{s}: {summary['rows']} bars, {summary['sessions']} sessions {summary['first'][:10]} .. {summary['last'][:10]}"
              f", short sessions {len(summary['short_sessions'])}, off-session dropped {summary['off_session_dropped']}"
              f", sha256 {entry['sha256'][:12]}")
    return 1 if failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="5m", choices=sorted(PERIOD))
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    sys.exit(main(a.interval, a.out))
