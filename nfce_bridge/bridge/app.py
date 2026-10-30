"""FastAPI app: POST /tv receives NFCE TradingView alerts; GET /health reports real worker/data health.

Run:  python -m bridge.app        (listens on 127.0.0.1:8000; put a tunnel in front for TradingView webhooks)

Webhook hygiene: shared-secret key (constant-time compare), 16 KB body limit, per-minute rate limit, access log
disabled (the key travels in the query string, which access logs would record), every accepted payload written to
the durable SQLite inbox BEFORE the 200 reply, then processed in the background and deduplicated by signal id.
"""
from __future__ import annotations

import hmac
import json
import logging
import threading
import time
from collections import deque
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .config import Settings
from .providers import FileProvider, UpstoxProvider
from .service import Bridge
from .store import Store
from .telegram import Telegram

log = logging.getLogger("nfce.app")


class _RedactKey(logging.Filter):
    """Belt and braces: strip ?key=... from any log line."""

    def filter(self, record: logging.LogRecord) -> bool:
        import re
        record.msg = re.sub(r"key=[^&\s\"']+", "key=***", str(record.msg))
        if record.args and isinstance(record.args, tuple):
            # only string arguments can carry a key; numbers stay numbers (uvicorn logs "%d")
            record.args = tuple(re.sub(r"key=[^&\s\"']+", "key=***", a) if isinstance(a, str) else a
                                for a in record.args)
        return True


def make_telegram(settings: Settings, store: Store) -> Telegram:
    """The bot's Telegram client; its update offset lives in the store (shared with the offline responder)."""
    tg = Telegram(settings.telegram_bot_token, settings.telegram_chat_id,
                  allowed_user_ids=settings.telegram_allowed_user_ids,
                  extra_chat_ids=settings.telegram_extra_chat_ids,
                  admin_chat_ids=settings.telegram_admin_chat_ids,
                  offset_get=lambda: int(store.kv_get("tg_offset", 0)),
                  offset_set=lambda v: store.kv_set("tg_offset", int(v)))
    tg.users = lambda: {str(x) for x in (store.kv_get("tg_users") or [])}      # admin-added users (bot.py)
    return tg


def build_bridge_parts() -> tuple:
    """Settings, store and Telegram client without the market-data provider (for bridge/offline_bot.py)."""
    settings = Settings.from_env()
    store = Store(settings.db_path)
    return settings, store, make_telegram(settings, store)


def build_bridge(settings: Settings) -> Bridge:
    if settings.provider == "mock":
        if not settings.mock_chain_file:
            raise SystemExit("PROVIDER=mock needs MOCK_CHAIN_FILE")
        provider = FileProvider(settings.mock_chain_file)
    else:
        provider = UpstoxProvider(settings.token_file, instruments_cache=settings.instruments_cache,
                                  min_interval_s=0.25)        # 4 requests/s: within Upstox's limits, faster loading
    store = Store(settings.db_path)
    tg = make_telegram(settings, store)
    return Bridge(settings, provider, store, tg)


def create_app(bridge: Bridge, start_loops: bool = True) -> FastAPI:
    stop = threading.Event()
    hits: deque = deque()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        n = bridge.recover_inbox()
        if n:
            log.info("processed %d alert(s) left in the inbox from a previous run", n)
        if start_loops:
            threading.Thread(target=bridge.poll_loop, args=(stop,), daemon=True, name="poll").start()
            threading.Thread(target=bridge.telegram_loop, args=(stop,), daemon=True, name="telegram").start()
            st = bridge.s
            bridge.tg.send("NFCE bridge started (alerts only, paper trading, no orders).\n"
                           f"Signals: {', '.join(st.engine_underlyings) or 'TradingView webhooks only'}"
                           + (" (computed by the bridge from Upstox futures candles)" if st.engine_underlyings else "")
                           + f"\nOption chain and quotes: {', '.join(st.poll_underlyings)}"
                           + f"\nOption legs: {'on' if st.option_legs else 'off'} | F&O scanner: "
                           + (f"on ({', '.join(st.scanner_times)})" if st.scanner else "off")
                           + f" | paper size: {st.paper_lots} lots"
                           + ("\nPaper accounts: " + ", ".join(f"{a.name} (equity ₹{a.equity():,.0f})" for a in bridge.accounts)
                              + f", {st.account_risk_pct:g}% risk per trade, {st.account_daily_loss_pct:g}% daily loss limit"
                              if bridge.accounts else "")
                           + f"\nAdmins: {len(bridge.tg.admins) if hasattr(bridge.tg, 'admins') else 1} chat(s); "
                           "ask in plain words (\"profit?\", \"open positions\") or send /help.")
        yield
        stop.set()

    app = FastAPI(title="NFCE bridge", lifespan=lifespan)

    @app.post("/tv")
    async def tv(request: Request, background: BackgroundTasks, key: str = ""):
        secret = bridge.s.webhook_secret
        if not secret or not hmac.compare_digest(key.encode(), secret.encode()):
            raise HTTPException(status_code=403, detail="bad or missing key")
        now = time.monotonic()
        while hits and now - hits[0] > 60:
            hits.popleft()
        if len(hits) >= bridge.s.max_requests_per_minute:
            raise HTTPException(status_code=429, detail="too many requests")
        hits.append(now)
        body = await request.body()
        if len(body) > bridge.s.max_body_bytes:
            raise HTTPException(status_code=413, detail="body too large")
        try:
            payload = json.loads(body)
        except ValueError:
            raise HTTPException(status_code=400, detail="body is not JSON")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="JSON object expected")
        inbox_id, dup = bridge.accept(payload, "tradingview")     # durable before we answer
        if dup:
            return {"ok": True, "duplicate": True}
        # TradingView cancels requests that take more than 3 s: answer now, work in the background.
        background.add_task(bridge.process, inbox_id, payload, "tradingview")
        return {"ok": True, "id": inbox_id}

    from .admin_api import register as register_admin
    register_admin(app, bridge)                     # the desk's controls: localhost + DESK_ADMIN_SECRET only

    @app.get("/health")
    def health():
        h = bridge.health_status()
        h.update(signals=bridge.store.count("signals"), snapshots=bridge.store.count("snapshots"),
                 inbox=bridge.store.count("inbox"))
        return JSONResponse(h, status_code=200 if h["ok"] else 503)

    return app


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    for name in ("", "uvicorn", "uvicorn.error"):
        logging.getLogger(name).addFilter(_RedactKey())
    settings = Settings.from_env()
    if not settings.webhook_secret:
        log.warning("WEBHOOK_SECRET is empty: /tv will reject every request (Telegram commands still work)")
    uvicorn.run(create_app(build_bridge(settings)), host="127.0.0.1", port=8000, access_log=False)


if __name__ == "__main__":
    main()
