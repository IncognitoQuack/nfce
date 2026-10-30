"""Pull ~10 years of daily candles (Upstox v3 allows 10 years per request) for every F&O stock, NIFTY, BANKNIFTY and
India VIX. usage (from nfce_bridge/): PYTHONPATH=. .venv/bin/python ops/pull_daily.py <out_dir> [from to]
  [--only NIFTY,INDIAVIX,...]   just these symbols (lots.json is merged, never cut down to them)
  [--with-today]                after the close: append today's bar from the intraday endpoint (the historical one
                                ends yesterday, so the 28 Oct evening refresh stopped at 27 Oct and OVN lacked a bar)
Saves <SYMBOL>_1d.pkl (index = date, columns open/high/low/close/volume/oi)."""
import datetime as dt
import json
import sys
import time
from pathlib import Path

import pandas as pd

COLS = ["ts", "open", "high", "low", "close", "volume", "oi"]


def frame(candles: list) -> pd.DataFrame:
    d = pd.DataFrame(candles, columns=COLS[:len(candles[0])])
    d.index = pd.to_datetime(d.pop("ts").str[:10])
    return d.sort_index()


def with_today(hist: pd.DataFrame, intraday: list, today: dt.date) -> pd.DataFrame:
    """Append today's daily bar (from the intraday endpoint) when it is dated today and not already there."""
    if not intraday:
        return hist
    t = frame(intraday)
    t = t[t.index.date == today]
    return pd.concat([hist[hist.index.date != today], t]).sort_index() if len(t) else hist


def main(argv: list[str]) -> None:
    import httpx
    from bridge.config import Settings

    flags = [a for a in argv if a.startswith("--")]
    args = [a for a in argv if not a.startswith("--")]
    only = next((a.split("=", 1)[1] for a in flags if a.startswith("--only=")), None)
    if "--only" in argv:                                   # also accept "--only A,B"
        only = argv[argv.index("--only") + 1]
        args.remove(only)
    want = set(only.split(",")) if only else None
    out = Path(args[0])
    out.mkdir(parents=True, exist_ok=True)
    tok = json.load(open(Settings.from_env().token_file))
    tok = tok.get("access_token", tok) if isinstance(tok, dict) else tok
    hdr = {"Authorization": f"Bearer {tok}", "Accept": "application/json"}
    today = dt.date.today()
    keys = {}
    for r in json.load(open("data/instruments_NSE.json"))["rows"]:
        if r["instrument_type"] == "FUT" and r["underlying_type"] == "EQUITY" and \
                dt.datetime.fromtimestamp(r["expiry"] / 1000).date() >= today:
            keys[r["underlying_symbol"]] = (r["underlying_key"], r["lot_size"])
    keys.update({"NIFTY": ("NSE_INDEX|Nifty 50", 65), "BANKNIFTY": ("NSE_INDEX|Nifty Bank", 30),
                 "INDIAVIX": ("NSE_INDEX|India VIX", 1)})
    if want:
        keys = {k: v for k, v in keys.items() if k in want}
    to, frm = today - dt.timedelta(days=1), today - dt.timedelta(days=3652)
    if len(args) > 2:                                      # explicit range: <out_dir> <from> <to> (YYYY-MM-DD)
        frm, to = dt.date.fromisoformat(args[1]), dt.date.fromisoformat(args[2])

    def get(url: str) -> list:
        for attempt in range(4):
            r = httpx.get(url, headers=hdr, timeout=30)
            if r.status_code == 429:
                time.sleep(10 * (attempt + 1))
                continue
            return r.json().get("data", {}).get("candles", []) if r.status_code == 200 else []
        return []

    lots_f = out / "lots.json"
    lots = json.loads(lots_f.read_text()) if lots_f.exists() else {}
    bad, saved, added = [], 0, 0
    for sym, (key, lot) in sorted(keys.items()):
        k = key.replace("|", "%7C").replace(" ", "%20")
        c = get(f"https://api.upstox.com/v3/historical-candle/{k}/days/1/{to}/{frm}")
        if not c:
            bad.append(sym)
            continue
        d = frame(c)
        if "--with-today" in flags:
            n0 = len(d)
            d = with_today(d, get(f"https://api.upstox.com/v3/historical-candle/intraday/{k}/days/1"), today)
            added += len(d) > n0
        d.to_pickle(out / f"{sym}_1d.pkl")
        lots[sym] = lot
        saved += 1
        time.sleep(0.4)
    lots_f.write_text(json.dumps(lots, indent=0))
    last = max((pd.read_pickle(out / f"{s}_1d.pkl").index[-1].date() for s in keys if s not in bad), default=None)
    print(f"saved {saved} symbols ({frm}..{last}){f'; today added to {added}' if '--with-today' in flags else ''}; "
          f"failed: {bad}")


if __name__ == "__main__":
    main(sys.argv[1:])
