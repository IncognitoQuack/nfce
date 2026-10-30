"""Admin API for the desk's controls (MASTER_SYSTEM_PLAN.md L6; owner OK 28 Oct ~13:55: "full, audited").

Only from this Mac (the bridge listens on 127.0.0.1, and the client must be local) and only with DESK_ADMIN_SECRET
in the X-Admin-Secret header (constant-time compare). The desk relays its CONTROL-token users here; nothing else does.

  GET  /admin/positions                 every account: strategy, paused, open positions (sid, symbol, lots, entry)
  POST /admin/action {action, acct, sid, device}
       close      one position of ONE account (by sid; `/close <n>` on Telegram hits every account)
       close_all  every position of ONE account
       pause / resume   one account's new entries
       halt / unhalt    everything: the risk gate and every account (as Telegram /pause, /resume)
       sell       some (`lots`) or all of one position of one account, at the live bid
       buy        {underlying, side (+1 call / -1 put), lots}: ONLY in an account whose strategy is "manual" (MAN).
                  The 1-ITM option is chosen by the engine's own pick_leg (same strike rule and spread checks) and
                  bought at the ask. The strategy accounts never take manual buys.
  GET  /admin/universe                  what can be bought: the index roots and the stock engine's F&O stocks

Every call is written to `events` (source 'admin', via 'desk') before it acts, and its result after. Exits made here are
sold at the live bid like any exit, with reason "MANUAL …", so reports can keep them out of the strategy scores.
"""
from __future__ import annotations

import hmac
from pathlib import Path

from fastapi import HTTPException, Request

LOCAL = {"127.0.0.1", "::1", "localhost"}
ACTIONS = ("close", "close_all", "pause", "resume", "halt", "unhalt", "sell", "buy")
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def env_secret(env_file: Path = ENV_FILE) -> str:
    """DESK_ADMIN_SECRET from .env, read at each call (bridge/config.py is a registered frozen file, so the secret is
    not a Settings field; a new secret also works without a restart)."""
    try:
        for line in env_file.read_text().splitlines():
            if line.startswith("DESK_ADMIN_SECRET="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def register(app, bridge, local_hosts: set[str] = LOCAL, secret_fn=env_secret) -> None:
    def auth(request: Request) -> None:
        secret = secret_fn()
        if not secret:
            raise HTTPException(status_code=503, detail="admin API off (no DESK_ADMIN_SECRET)")
        host = request.client.host if request.client else ""
        if host not in local_hosts:
            raise HTTPException(status_code=403, detail="local only")
        given = request.headers.get("x-admin-secret", "")
        if not hmac.compare_digest(given.encode(), secret.encode()):
            raise HTTPException(status_code=403, detail="bad secret")

    def account(name: str):
        for a in bridge.accounts:
            if a.name == name:
                return a
        raise HTTPException(status_code=404, detail=f"no account {name!r}")

    def universe() -> dict:
        """{underlying: (spot key, lot units)} for manual buys: index roots + the stock engine's universe."""
        from .paper import LOT
        out = {r: (k, int(LOT.get(r, 1))) for r, k in getattr(bridge.s, "underlyings", {}).items()}
        stocks = getattr(bridge, "stocks", None)
        for u in (getattr(stocks, "universe", None) or []):
            out[u["symbol"]] = (u["equity_key"], int(u["lot"]))
        return out

    def buy(a, body: dict, now) -> list[str]:
        from .options import pick_leg
        from .providers import ProviderError
        if a.strategy != "manual":
            raise HTTPException(status_code=403, detail=f"{a.name} is a strategy account: manual buys only in the manual account")
        und = str(body.get("underlying", "")).upper().strip()
        side = 1 if int(body.get("side", 0) or 0) > 0 else -1
        lots = int(body.get("lots", 0) or 0)
        if lots < 1 or lots > 100:
            raise HTTPException(status_code=400, detail="lots must be 1–100")
        uni = universe()
        if und not in uni:
            raise HTTPException(status_code=404, detail=f"{und!r} is not tradeable here (not an index root or F&O stock)")
        key, units = uni[und]
        q = bridge.provider.quotes([key]).get(key)
        spot = getattr(q, "last_price", None) if q is not None else None
        if not spot:
            return [f"{a.name}: no live price for {und}; not bought"]
        try:
            leg = pick_leg(bridge.provider, key, und, spot, side, spot, spot, (spot, spot, spot), units, now.date())
        except ProviderError as exc:
            return [f"{a.name}: option chain unavailable for {und}: {exc}"[:200]]
        return [a.manual_buy(now, leg, lots, key, side)]

    @app.get("/admin/universe")
    def universe_(request: Request):
        auth(request)
        return {"underlyings": sorted(universe())}

    @app.get("/admin/positions")
    def positions(request: Request):
        auth(request)
        return {"halted": bool(bridge.risk.halted()), "accounts": [
            {"acct": a.name, "strategy": a.strategy, "paused": a.paused,
             "positions": [{"sid": p.sid, "symbol": p.symbol, "lots": p.lots, "rem_lots": p.rem_lots,
                            "entry": p.entry, "opened": p.opened, "hits": p.hits} for p in list(a.positions.values())]}
            for a in bridge.accounts]}

    @app.post("/admin/action")
    async def action(request: Request):
        auth(request)
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="JSON body expected")
        act, name, sid = body.get("action"), body.get("acct", ""), body.get("sid", "")
        extra = {k: body.get(k) for k in ("underlying", "side", "lots") if body.get(k) not in (None, "")}
        device = str(body.get("device", ""))[:80]
        if act not in ACTIONS:
            raise HTTPException(status_code=400, detail=f"action must be one of {', '.join(ACTIONS)}")
        if act in ("close", "close_all", "pause", "resume", "sell", "buy"):
            a = account(name)
        if act in ("close", "sell") and (not sid or sid not in a.positions):
            raise HTTPException(status_code=404, detail=f"{name} has no open position {sid!r}")
        audit = {"cmd": act, "acct": name, "sid": sid, "via": "desk", "device": device} | extra
        bridge.store.add_event("admin", audit)
        now = bridge.now()
        if act == "close":
            out = a.close(now, sid, reason="MANUAL close (desk)")
        elif act == "sell":
            out = a.manual_sell(now, sid, int(body.get("lots") or 0) or None)
        elif act == "buy":
            out = buy(a, body, now)
        elif act == "close_all":
            out = a.close(now, "all", reason="MANUAL close-all (desk)")
        elif act in ("pause", "resume"):
            a.set_paused(act == "pause")
            out = [f"{name}: {'paused' if act == 'pause' else 'resumed'} (new entries)"]
        else:
            bridge.risk.set_halted(act == "halt")
            for x in bridge.accounts:
                x.set_paused(act == "halt")
            out = ["HALTED: no new entries anywhere; open positions keep their stops" if act == "halt"
                   else "Resumed: new entries allowed"]
        bridge.store.add_event("admin", audit | {"result": out})
        return {"ok": True, "result": out}
