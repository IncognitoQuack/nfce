"""Daily Upstox login: opens the Upstox login page, captures the redirect code locally,
exchanges it for an access token and saves it to data/upstox_token.json (mode 0600, written atomically).

You type your Upstox credentials on Upstox's own page; this script never sees them.
Upstox access tokens expire at 03:30 IST the next morning, so run this once per trading day.

Run:  python -m bridge.upstox_login        (start.sh does this automatically when needed)
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import time
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .config import Settings
from .providers import IST, UPSTOX_BASE

LOGIN_TIMEOUT_S = 300


def token_expiry(issued: datetime) -> datetime:
    """03:30 IST on the day after issue (or the same day if issued before 03:30)."""
    issued = issued.astimezone(IST)
    cut = issued.replace(hour=3, minute=30, second=0, microsecond=0)
    return cut if issued < cut else cut + timedelta(days=1)


def write_private(path: Path, text: str) -> None:
    """Create the file with 0600 permissions from the first byte, then atomically replace the old one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, text.encode())
    finally:
        os.close(fd)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


_HINTS = {
    "UDAPI100057": "the login code was already used or expired (it is single-use and short-lived): run bash start.sh again "
                   "and finish the Upstox login without refreshing or going back",
    "UDAPI100069": "API key or secret does not match the app: copy both again from Upstox -> My Apps into .env",
    "UDAPI100058": "your Upstox account has no active trading segment yet (account opening still in progress, or "
                   "segments inactive): activate Equity and F&O in the Upstox app or web, then run bash start.sh again",
}


def _upstox_reason(r: httpx.Response) -> str:
    """Upstox's error code and message (never echoes anything we sent), plus a plain hint."""
    try:
        errs = r.json().get("errors") or []
    except ValueError:
        return ""
    parts = []
    for e in errs[:3]:
        code, msg = str(e.get("errorCode", "")), str(e.get("message", ""))
        parts.append(f"{code} {msg}".strip() + (f" -> {_HINTS[code]}" if code in _HINTS else ""))
    return "; ".join(parts)


def auth_url(s: Settings, state: str) -> str:
    return f"{UPSTOX_BASE}/login/authorization/dialog?" + urlencode({
        "response_type": "code", "client_id": s.upstox_api_key, "redirect_uri": s.upstox_redirect_uri, "state": state})


class LoginError(Exception):
    pass


def exchange_code(s: Settings, code: str) -> datetime:
    """Swap the one-time login code for an access token and save it; returns the token's expiry."""
    try:
        r = httpx.post(f"{UPSTOX_BASE}/login/authorization/token", headers={"Accept": "application/json"}, data={
            "code": code, "client_id": s.upstox_api_key, "client_secret": s.upstox_api_secret,
            "redirect_uri": s.upstox_redirect_uri, "grant_type": "authorization_code"}, timeout=15)
    except httpx.HTTPError as exc:
        raise LoginError(f"Token exchange failed: {type(exc).__name__}") from None
    if r.status_code != 200:
        raise LoginError(f"Token exchange failed: HTTP {r.status_code} {_upstox_reason(r)}")
    access = r.json().get("access_token")
    if not access:
        raise LoginError("Token exchange returned no access_token")
    exp = token_expiry(datetime.now(IST))
    write_private(s.token_file, json.dumps({"access_token": access, "expires_at": exp.timestamp()}))
    return exp


def code_from(text: str, state: str | None) -> str:
    """The login code from what the admin pasted: the whole redirect address (the page itself will not load on a
    phone, but its address holds the code) or the bare code. The state must match the /login that was sent."""
    text = text.strip()
    if "code=" in text:
        q = parse_qs(urlparse(text).query)
        if state and q.get("state", [""])[0] != state:
            raise LoginError("that address is from a different login (state mismatch): send /login again")
        code = q.get("code", [""])[0]
    else:
        code = text
    if not code or len(code) > 200 or any(c.isspace() for c in code):
        raise LoginError("no login code found: paste the whole address the browser shows after the Upstox login")
    return code


def main(timeout_s: int = LOGIN_TIMEOUT_S) -> None:
    s = Settings.from_env()
    if not (s.upstox_api_key and s.upstox_api_secret):
        sys.exit("Set UPSTOX_API_KEY and UPSTOX_API_SECRET in .env first.")
    redirect = urlparse(s.upstox_redirect_uri)
    if redirect.hostname not in ("127.0.0.1", "localhost") or not redirect.port:
        sys.exit("UPSTOX_REDIRECT_URI must be a local address such as http://127.0.0.1:8765/callback")
    state = secrets.token_urlsafe(16)
    got: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path != (redirect.path or "/"):
                msg, code = "Not found.", 404
            elif q.get("state", [""])[0] != state:
                msg, code = "Unexpected request (state mismatch).", 400
            elif "error" in q:
                got["error"] = q.get("error_description", q["error"])[0]
                msg, code = f"Upstox login failed: {got['error']}. You can close this tab.", 200
            elif "code" in q:
                got["code"] = q["code"][0]
                msg, code = "Upstox login received. You can close this tab.", 200
            else:
                msg, code = "No code in the redirect.", 400
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(msg.encode())

        def log_message(self, *args):   # the redirect URL contains the one-time code: do not log it
            pass

    server = HTTPServer((redirect.hostname, redirect.port), Handler)   # listening BEFORE the browser opens
    server.timeout = 1.0
    url = auth_url(s, state)
    print("Opening the Upstox login page. If it does not open, paste this into your browser:\n" + url)
    webbrowser.open(url)
    deadline = time.monotonic() + timeout_s
    try:
        while "code" not in got and "error" not in got:
            if time.monotonic() > deadline:
                sys.exit(f"No Upstox login within {timeout_s // 60} minutes; run it again.")
            server.handle_request()
    finally:
        server.server_close()
    if "error" in got:
        sys.exit(f"Upstox login failed: {got['error']}")

    try:
        exp = exchange_code(s, got["code"])
    except LoginError as exc:
        sys.exit(str(exc))
    print(f"Saved token to {s.token_file} (valid until {exp:%Y-%m-%d %H:%M} IST).")


if __name__ == "__main__":
    main()
