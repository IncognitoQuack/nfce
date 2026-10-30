"""Send a plain-text Telegram message as the bridge: reply.py "text" chat_id   (run from nfce_bridge/)

The message is also logged in data/nfce.db sent_messages (22 Oct: replies sent this way were missing from the log).
"""
import sqlite3
import sys
from datetime import datetime, timezone

import httpx

env = {}
for line in open(".env"):
    k, sep, v = line.strip().partition("=")
    if sep and not k.startswith("#"):
        env[k.strip()] = v.strip().strip('"').strip("'")
r = httpx.post(f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/sendMessage",
               json={"chat_id": sys.argv[2], "text": sys.argv[1]}, timeout=20)
ok = bool(r.json().get("ok"))
db = sqlite3.connect("data/nfce.db", timeout=10)
with db:
    db.execute("INSERT INTO sent_messages (ts, ok, text) VALUES (?,?,?)",
               (datetime.now(timezone.utc).isoformat(), int(ok), f"[assistant reply to {sys.argv[2]}] {sys.argv[1]}"))
print(r.status_code, ok, r.json().get("description", ""))
