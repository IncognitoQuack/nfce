"""Check that .env, Telegram and the Upstox token are working. Never prints secrets.

    python -m bridge.check_setup                 # full check, sends one Telegram test message
    python -m bridge.check_setup --no-send       # same, without the Telegram message
    python -m bridge.check_setup --find-chat-id  # print the chat id of whoever last messaged your bot
"""
from __future__ import annotations

import argparse
import json
import logging
import secrets
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .analytics import summarize
from .config import ROOT, Settings
from .providers import IST, ProviderError, TokenExpired, UpstoxProvider

logging.getLogger("httpx").setLevel(logging.WARNING)      # request URLs contain the Telegram bot token


def ensure_webhook_secret(env_file: Path) -> bool:
    """Fill an empty WEBHOOK_SECRET= line with a random value. Returns True if it changed the file."""
    if not env_file.is_file():
        return False
    lines = env_file.read_text().splitlines()
    changed = False
    for i, line in enumerate(lines):
        if line.strip() == "WEBHOOK_SECRET=":
            lines[i] = "WEBHOOK_SECRET=" + secrets.token_urlsafe(24)
            changed = True
    if changed:
        env_file.write_text("\n".join(lines) + "\n")
        env_file.chmod(0o600)
    return changed


def token_status(token_file: Path) -> tuple[bool, str]:
    if not token_file.is_file():
        return False, "no Upstox token yet (run the daily login)"
    try:
        info = json.loads(token_file.read_text())
        exp = float(info["expires_at"])
    except (ValueError, KeyError):
        return False, "token file unreadable (run the daily login again)"
    if exp <= time.time():
        return False, "Upstox token expired (they expire at 03:30 IST; run the daily login)"
    return True, f"Upstox token valid until {datetime.fromtimestamp(exp, IST):%Y-%m-%d %H:%M} IST"


def check_config(s: Settings) -> list[tuple[str, bool, str]]:
    out = []
    out.append(("UPSTOX_API_KEY", bool(s.upstox_api_key), "set" if s.upstox_api_key else "missing"))
    out.append(("UPSTOX_API_SECRET", bool(s.upstox_api_secret), "set" if s.upstox_api_secret else "missing"))
    r = urlparse(s.upstox_redirect_uri)
    ok = r.scheme == "http" and r.hostname in ("127.0.0.1", "localhost") and bool(r.port)
    out.append(("UPSTOX_REDIRECT_URI", ok, s.upstox_redirect_uri if ok else "must be like http://127.0.0.1:8765/callback"))
    out.append(("TELEGRAM_BOT_TOKEN", ":" in s.telegram_bot_token,
                "set" if ":" in s.telegram_bot_token else "missing (looks like 123456:ABC...)"))
    out.append(("TELEGRAM_CHAT_ID", s.telegram_chat_id.lstrip("-").isdigit(),
                "set" if s.telegram_chat_id.lstrip("-").isdigit() else "missing (a number; use --find-chat-id)"))
    admins = s.telegram_admin_chat_ids
    out.append(("TELEGRAM_ADMIN_CHAT_IDS", all(x.lstrip("-").isdigit() for x in admins),
                f"{len(admins)} admin chat(s)" if admins else "not set: the main and extra chats are all admins"))
    out.append(("WEBHOOK_SECRET", len(s.webhook_secret) >= 16,
                "set" if len(s.webhook_secret) >= 16 else "missing (run setup.sh to generate it)"))
    return out


def telegram_get(client: httpx.Client, token: str, method: str, **params) -> dict:
    r = client.get(f"https://api.telegram.org/bot{token}/{method}", params=params, timeout=15)
    return r.json()


def feature_checks(prov, s: Settings, now) -> int:
    """SENSEX, the bridge's own engine (futures candles), option legs and the F&O scanner, against live Upstox data."""
    from datetime import timedelta
    from .options import pick_leg
    problems = 0
    roots = sorted(set(s.poll_underlyings) | set(s.engine_underlyings))
    print("== Instruments, engine and option legs ==")
    for root in roots:
        try:
            fut = prov.front_future(s.futures_symbol.get(root, root), now.date())
            spot_key = s.underlyings[root]
            qs = prov.quotes([fut.instrument_key, spot_key])
            fq, sq = qs.get(fut.instrument_key), qs.get(spot_key)
            print(f"  [{'ok' if fq and sq else '!!'}] {root}: future {fut.trading_symbol} (lot {fut.lot_size}), quotes "
                  + ("ok" if fq and sq else "MISSING"))
            problems += not (fq and sq)
            if root in s.engine_underlyings:
                hist = prov.candles_5m(fut.instrument_key, now.date() - timedelta(days=10), now.date() - timedelta(days=1))
                today = prov.candles_5m(fut.instrument_key, now.date(), now.date(), intraday=True)
                ok = len(hist) >= 150
                print(f"  [{'ok' if ok else '!!'}] {root} engine candles: {len(hist)} history bars (10 days), "
                      f"{len(today)} today (0 before 09:20 is normal)")
                problems += not ok
            if s.option_legs and sq:
                leg = pick_leg(prov, spot_key, root, sq.last_price, 1, sq.last_price, sq.last_price * 0.998,
                               (sq.last_price * 1.002, sq.last_price * 1.004, sq.last_price * 1.006), fut.lot_size,
                               now.date())
                print(f"  [ok] {root} option leg example: {leg.strike:g} {leg.typ} {leg.expiry} bid {leg.bid} ask {leg.ask}"
                      + (f" ({leg.note})" if leg.note else ""))
        except Exception as exc:                                   # report every feature separately
            print(f"  [!!] {root}: {type(exc).__name__}: {exc}"[:200])
            problems += 1
    if s.engine_underlyings:
        missing = [h for h in ("HDFCBANK", "ICICIBANK", "RELIANCE", "INFY", "BHARTIARTL") if not prov.equity_key(h)]
        print(f"  [{'ok' if not missing else '!!'}] heavyweight stock keys" + (f": missing {missing}" if missing else ""))
        problems += bool(missing)
    if s.scanner:
        uni = prov.fno_stocks(now.date())
        print(f"  [{'ok' if len(uni) >= 150 else '!!'}] F&O scanner universe: {len(uni)} stocks with live futures")
        problems += len(uni) < 150
    return problems


def main(argv: list[str] | None = None, client: httpx.Client | None = None, provider=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-send", action="store_true")
    ap.add_argument("--find-chat-id", action="store_true")
    ap.add_argument("--env", type=Path, default=ROOT / ".env")
    a = ap.parse_args(argv)
    s = Settings.from_env(a.env)
    client = client or httpx.Client()

    if a.find_chat_id:
        if ":" not in s.telegram_bot_token:
            print("Put TELEGRAM_BOT_TOKEN in .env first, then send your bot any message.")
            return 1
        res = telegram_get(client, s.telegram_bot_token, "getUpdates").get("result", [])
        chats = {str(u["message"]["chat"]["id"]): u["message"]["chat"].get("first_name", "")
                 for u in res if u.get("message")}
        if not chats:
            print("No messages found. Send your bot any message (e.g. 'hi') and run this again.")
            return 1
        for cid, name in chats.items():
            print(f"chat id {cid}  ({name})  -> put TELEGRAM_CHAT_ID={cid} in .env")
        return 0

    problems = 0
    print("== .env ==")
    for name, ok, msg in check_config(s):
        print(f"  [{'ok' if ok else '!!'}] {name}: {msg}")
        problems += not ok

    print("== Telegram ==")
    if ":" in s.telegram_bot_token:
        me = telegram_get(client, s.telegram_bot_token, "getMe")
        if me.get("ok"):
            print(f"  [ok] bot @{me['result'].get('username')} reachable")
            if not a.no_send and s.telegram_chat_id:
                sent = client.post(f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage", json={
                    "chat_id": s.telegram_chat_id, "text": "NFCE bridge setup test: Telegram works."}, timeout=15).json()
                print(f"  [{'ok' if sent.get('ok') else '!!'}] test message "
                      + ("sent: check your Telegram" if sent.get("ok") else f"failed: {sent.get('description')}"))
                problems += not sent.get("ok")
        else:
            print(f"  [!!] bot token rejected by Telegram: {me.get('description')}")
            problems += 1
    else:
        print("  [--] skipped (no bot token yet)")

    print("== Upstox ==")
    ok, msg = token_status(s.token_file)
    print(f"  [{'ok' if ok else '--'}] {msg}")
    if ok:
        prov = provider or UpstoxProvider(s.token_file, instruments_cache=s.instruments_cache)
        key = s.underlyings["NIFTY"]
        now = datetime.now(IST)
        try:
            exp = prov.nearest_expiry(key)
            chain = prov.chain(key, exp)
            summ = summarize(chain, s.window)
            pcr = "n/a" if summ.pcr_oi is None else f"{summ.pcr_oi:.2f}"
            print(f"  [ok] NIFTY chain {exp}: spot {summ.spot:,.1f}, ATM {summ.atm_strike:g}, "
                  f"PCR OI {pcr}, {len(chain.rows)} strikes")
            print(f"  [{'ok' if summ.doi_available else '!!'}] previous-day OI "
                  + ("present (ΔOI flow works)" if summ.doi_available else "MISSING: vetoes will show UNCHECKED"))
            problems += not summ.doi_available
            fut = prov.front_future("NIFTY", now.date())
            print(f"  [ok] front-month future {fut.trading_symbol} (expiry {fut.expiry}, lot {fut.lot_size})")
            qs = prov.quotes([fut.instrument_key, key])
            fq, sq = qs.get(fut.instrument_key), qs.get(key)
            if fq is None or sq is None:
                print("  [!!] futures or spot quote missing")
                problems += 1
            else:
                for name, q in (("futures", fq), ("spot index", sq)):     # review round 3, H05
                    has = q.last_trade_time is not None
                    print(f"  [{'ok' if has or name != 'futures' else '!!'}] {name} quote "
                          + ("carries an exchange last-trade time" if has else
                             "has NO exchange last-trade time" + (": executable paper entries will be refused"
                                                                   if name == "futures" else " (receipt time used for the basis)")))
                    problems += (not has and name == "futures")
                if sq.prev_close is None:
                    print("  [!!] spot quote has no previous close: the range forecast will refuse to run")
                    problems += 1
                age = fq.age_s(now)
                fresh = age <= s.max_quote_age_s
                print(f"  [{'ok' if fresh else '--'}] futures {fq.last_price:,.1f} (last trade {age:,.0f}s ago"
                      + ("" if fresh else ": stale, normal outside market hours") + f"), spot {sq.last_price:,.1f}, "
                      f"basis {fq.last_price - sq.last_price:+.1f}, spread "
                      + (f"{fq.spread:.2f}" if fq.spread is not None else "n/a"))
        except TokenExpired as exc:
            print(f"  [!!] {exc}")
            problems += 1
        except (ProviderError, httpx.HTTPError, ValueError) as exc:
            print(f"  [!!] Upstox data fetch failed: {exc}")
            problems += 1
        problems += feature_checks(prov, s, now)

    print("== Paper accounts ==")
    if s.accounts:
        for name, cap in s.accounts.items():
            print(f"  [ok] {name}: ₹{cap:,.0f} start, {s.account_risk_pct:g}% risk per trade, "
                  f"{s.account_daily_loss_pct:g}% daily loss limit, max {s.account_max_open} open")
    else:
        print("  [--] none (set ACCOUNTS=2L:200000,5L:500000 in .env)")

    print("== R4 range model ==")
    try:
        from .range_model import RangeForecaster
        rf = RangeForecaster(None)
        meta = rf.meta
        print(f"  [ok] model {meta.get('model', 'M0')} loads (scikit-learn {meta['versions']['sklearn']}, "
              f"{meta['rows']:,} training rows, {meta['trained_on'][0]}..{meta['trained_on'][1]})")
        har = rf.har()
        print(f"  [{'ok' if har else '!!'}] linear HAR+VIX benchmark model (R6) " + ("loads" if har else "missing"))
        problems += har is None
    except Exception as exc:                                       # missing file, wrong library version, corrupt pickle
        print(f"  [!!] R4 model unavailable: {exc} (run setup.sh)")
        problems += 1

    print("\nAll good." if problems == 0 else f"\n{problems} item(s) to fix (marked !!).")
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
