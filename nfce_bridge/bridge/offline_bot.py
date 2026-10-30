"""Offline responder: answers Telegram while the bridge is stopped (admin, 22 Oct 16:39: "a better bot that even
responds when the system is offline").

* It polls Telegram ONLY while the bridge's /health does not answer, so the two never compete for updates, and it uses
  the bridge's own offset (kv tg_offset): what it answers is acknowledged and never handled twice.
* Read-only: status, the paper accounts (side by side), today's results, open risk, the ledger (admin), /about, /meme.
  It never trades, never changes a setting and never restarts anything.
* Any other message is saved in `events` (telegram-admin / telegram-note) for the assistant and the admin.

Run detached:  nohup .venv/bin/python -m bridge.offline_bot >> ~/Library/Logs/nfce_offline_bot.log 2>&1 & disown
It does not keep the Mac awake: while the Mac sleeps, nothing answers.
"""
from __future__ import annotations

import csv
import logging
import random
import sqlite3
import time
from datetime import datetime
from types import SimpleNamespace

import httpx

from .providers import IST

log = logging.getLogger("nfce.offline")

MEMES = [
    "📉 Me: \"this SELL is a sure thing.\"\nThe market at 12:20: 🚀",
    "🧾 Costs: the only trader in this system with a 100% win rate.",
    "🧘 Paper trading: all of the emotions, none of the margin calls.",
    "📊 Backtest: +40%. Live: \"we don't talk about that.\"\nNFCE: reports both. 🫡",
    "⏰ 15:15: the square-off arrives like a teacher collecting the exam papers.",
    "🤖 \"Is it 90% accurate?\"\nThe honest bot: \"is anything?\"",
    "☕ Market opens 09:15. The engine waits till 09:30. Patience is a strategy too.",
    "🎯 T1 hit! (on paper) 🎉 The most expensive free money there is.",
    "🔮 Every chart is obvious in hindsight. That's why we lock the rules BEFORE the test.",
    "🐂🐻 Bulls win, bears win, and the stop loss makes sure we learn something.",
    "🧮 Ten SELL signals in six minutes: not ten trades, one opinion said ten times.",
    "📏 A stop loss is like a seat belt: annoying, until it isn't.",
]

DOWN_GRACE_S, LAUNCH_GRACE_S, MAX_RESTARTS, HUNG_S = 60, 90, 3, 300
BRIDGE_PROC = "[-]m bridge[.]start"     # never a leading "-": pgrep would read it as an option (23 Oct)

HELP = ("🌙 NFCE bot (the system is offline; these still work):\n"
        "/status: is the system running, and when does it start\n"
        "/account: the paper accounts, side by side\n"
        "/today: today's signals and results\n"
        "/risk: open positions: direction and the loss if every stop is hit\n"
        "/about: what is and is not proven\n"
        "/ledger: the account ledger as a CSV (admin)\n"
        "/meme: a little trading humour\n"
        "Anything else you write is saved for the admin and the assistant.\n"
        "Paper trading only · no orders placed")

ABOUT = ("ℹ️ NFCE is a paper-trading signal system: it never places orders.\n"
         "Measured so far (after costs): index signals −0.20R per trade (94 trades), stock 3-min signals −0.27R "
         "(16,598 trades; 4× wider stops −0.03R), scanner −0.07R (7,135). The range forecast (size of the next hour's move) has real skill. "
         "Nothing is proven profitable; five paper accounts measure different ways of handling the signals.")


class OfflineBot:
    def __init__(self, settings, store, tg, now=None, bridge_up=None, health_url: str = "http://127.0.0.1:8000/health"):
        self.s, self.store, self.tg = settings, store, tg
        self.now = now or (lambda: datetime.now(IST))
        self.health_url = health_url
        self._bridge_up = bridge_up or self._probe
        self._seen_up_day = None                          # supervisor state
        self._down_since: datetime | None = None
        self._last_launch: datetime | None = None
        self._restarts: dict = {}                         # day -> restarts so far
        self._gave_up_day = None
        self._last_stop: datetime | None = None
        from pathlib import Path
        self.maintenance_file = Path.home() / ".nfce_maintenance"

    # ---------- supervisor (22 Oct: the bridge died at 09:49; nothing noticed for 30 minutes) ----------
    def _health_json(self) -> dict | None:
        try:
            return httpx.get(self.health_url, timeout=3).json()
        except (httpx.HTTPError, ValueError):
            return None

    @staticmethod
    def _stop_bridge() -> None:
        import subprocess
        subprocess.run(["pkill", "-TERM", "-f", BRIDGE_PROC], capture_output=True)   # start.sh restarts it

    @staticmethod
    def _bridge_process() -> bool:
        import subprocess
        return subprocess.run(["pgrep", "-f", BRIDGE_PROC], capture_output=True).returncode == 0

    @staticmethod
    def _launch_bridge() -> None:
        import subprocess
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        logf = open(Path.home() / "Library" / "Logs" / "nfce_bridge.log", "a")
        subprocess.Popen(["bash", str(root / "start.sh")], cwd=root, stdout=logf, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True)       # detached: survives this process

    def supervise(self) -> None:
        """Restart a bridge that died during market hours (weekday 09:15-15:15) AFTER it had run that day.
        Never the morning start (the owner signs in), never a second copy, at most MAX_RESTARTS a day."""
        n = self.now().astimezone(IST)
        day, mins = n.date(), n.hour * 60 + n.minute
        if self.maintenance_file.exists():               # a deliberate stop: touch ~/.nfce_maintenance
            self._down_since = None
            return
        if self._bridge_up():
            in_market = n.weekday() < 5 and 9 * 60 + 15 <= mins <= 15 * 60 + 15
            beat = (self._health_json() or {}).get("poll_beat") if in_market else None
            if beat and (n - datetime.fromisoformat(beat)).total_seconds() > HUNG_S and \
                    (self._last_stop is None or (n - self._last_stop).total_seconds() > LAUNCH_GRACE_S):
                self._last_stop = n
                self.tg.send_admin(f"⚠️ The system is not responding (market loop silent since "
                                   f"{datetime.fromisoformat(beat).astimezone(IST):%H:%M}); restarting it.")
                self._stop_bridge()
                return
            if self._down_since is not None and self._last_launch is not None and self._seen_up_day == day:
                self.tg.send_admin(f"✅ The system is running again ({n:%H:%M}) after an automatic restart.")
            self._seen_up_day, self._down_since, self._last_launch = day, None, None
            return
        if not (n.weekday() < 5 and 9 * 60 + 15 <= mins <= 15 * 60 + 15) or self._seen_up_day != day:
            self._down_since = None
            return
        if self._down_since is None:
            self._down_since = n
        if (n - self._down_since).total_seconds() < DOWN_GRACE_S or self._bridge_process():
            return
        if self._last_launch is not None and (n - self._last_launch).total_seconds() < LAUNCH_GRACE_S:
            return
        used = self._restarts.get(day, 0)
        if used >= MAX_RESTARTS:
            if self._gave_up_day != day:
                self._gave_up_day = day
                self.tg.send_admin(f"🆘 The system stopped again at {n:%H:%M} after {MAX_RESTARTS} automatic restarts "
                                   "today: it needs a person at the Mac (see ~/Library/Logs/nfce_bridge.log).")
            return
        self._restarts[day] = used + 1
        self._last_launch = n
        self.tg.send_admin(f"⚠️ The system stopped during market hours (down since {self._down_since:%H:%M}); "
                           f"restarting it automatically (attempt {used + 1} of {MAX_RESTARTS}).")
        self._launch_bridge()

    def _probe(self) -> bool:
        try:
            httpx.get(self.health_url, timeout=3)          # any answer (200 or 503) means the bridge is running
            return True
        except httpx.HTTPError:
            return False

    # ---------- answers ----------
    def _accounts(self) -> list:
        from .account import Account
        b = SimpleNamespace(store=self.store, now=self.now, provider=None, tg=None)
        names = self.s.accounts or {}
        return [Account(b, cap, name=n, strategy=self.s.account_strategies.get(n, "base"), quiet=i > 0)
                for i, (n, cap) in enumerate(names.items())]

    def _last_seen(self) -> str:
        try:
            row = self.store.db.execute("SELECT ts FROM sent_messages WHERE text NOT LIKE '[assistant%' "
                                        "ORDER BY id DESC LIMIT 1").fetchone()
        except sqlite3.OperationalError:
            row = None
        if not row:
            return "never"
        return datetime.fromisoformat(row[0]).astimezone(IST).strftime("%a %d %b %H:%M")

    def status(self) -> str:
        n = self.now().astimezone(IST)
        weekday = n.weekday() < 5
        nxt = ("today" if weekday and n.hour * 60 + n.minute < 9 * 60 + 15 else "the next market day")
        return (f"🌙 NFCE is offline right now ({n:%a %H:%M}).\n"
                f"It runs on market days from about 08:45 to 15:40; next start: {nxt}, about 08:45.\n"
                f"Last message from the running system: {self._last_seen()}.\n"
                "Your messages are saved; /help lists what works now.")

    def accounts_text(self) -> str:
        accts = self._accounts()
        if not accts:
            return "The paper accounts are off."
        text = accts[0].report()
        if len(accts) > 1:
            text += ("\n\n📊 <b>Strategy accounts</b> (same signals, different handling; paper)\n"
                     + "\n".join(a.summary_line() for a in accts))
        return text

    def today(self) -> str:
        day = self.now().astimezone(IST).date().isoformat()
        q = self.store.db.execute
        try:
            books = q("SELECT book, COUNT(*), SUM(net_pts > 0) FROM paper_trades WHERE substr(opened,1,10)=? "
                      "GROUP BY book", (day,)).fetchall()
        except sqlite3.OperationalError:                 # a fresh database has no paper books yet
            books = []
        lines = [f"📅 Today {day} (system offline; final figures)"]
        if not books:
            lines.append("No paper trades today.")
        names = {"executable": "NIFTY/SENSEX signals (futures paper)", "stock3m": "Stock 3-min signals",
                 "scanner": "Scanner picks"}
        for book, n, won in books:
            if book in names:                            # r4 / theoretical are research shadows of the index book
                lines.append(f"• {names[book]}: {n} trades, {won or 0} won")
        for a in self._accounts():
            lines.append(a.summary_line())
        lines.append("Paper trading only · no orders placed")
        return "\n".join(lines)

    def risk(self) -> str:
        out = []
        for a in self._accounts():
            if a.positions:
                x = a.exposure()
                out.append(f"• {a.name}: {x['sell']} SELL / {x['buy']} BUY · if every stop is hit −₹{x['at_risk']:,.0f}")
        return "\n".join(["⚖️ Open risk"] + out) if out else "⚖️ No open positions (everything is squared off by 15:15)."

    def ledger(self, chat: str) -> str:
        if not self.tg.is_admin(chat):
            return "The ledger is for the admin."
        self._accounts()                                  # creates the account tables on a fresh database
        path = self.s.db_path.parent / f"account_ledger_{self.now():%Y-%m-%d}.csv"
        cur = self.store.db.execute("SELECT acct, ts, sid, symbol, action, lots, units, price, cash_flow, fees, realized, "
                                    "reason, cash_after FROM account_fills ORDER BY id")
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([c[0] for c in cur.description])
            w.writerows(cur.fetchall())
        self.tg.send_document(path, "Paper account ledger (sent by the offline bot)", to=[chat])
        return "📎 Ledger sent."

    def handle(self, chat: str, text: str) -> str:
        cmd = text.strip().split()[0].lower().split("@")[0] if text.strip() else ""
        if cmd in ("/status", "/health", "/start"):
            return self.status()
        if cmd in ("/account", "/pnl", "/accounts"):
            return self.accounts_text()
        if cmd == "/today":
            return self.today()
        if cmd in ("/risk", "/open"):
            return self.risk()
        if cmd == "/about":
            return ABOUT
        if cmd == "/ledger":
            return self.ledger(chat)
        if cmd == "/meme":
            return random.choice(MEMES)
        if cmd in ("/help", "/admin"):
            return HELP
        admin = self.tg.is_admin(chat)
        self.store.add_event("telegram-admin" if admin else "telegram-note",
                             {"text": text[:2000], "chat": chat, "offline": True})
        if not admin:
            self.tg.send_admin(f"💬 (offline) Message from user {chat}:\n{text[:1500]}")
        return ("📨 Saved. The system is offline right now, so " +
                ("your assistant will reply here." if admin else "the admin will see it.") +
                (" Commands work again when it starts (about 08:45 on market days)." if cmd.startswith("/") else ""))

    # ---------- loop ----------
    def step(self) -> int:
        """One poll while the bridge is down; returns the number of messages answered."""
        if self._bridge_up():
            return 0
        texts = self.tg.poll_commands(timeout=10)
        for chat, text in zip(list(self.tg.sources), texts):
            try:
                reply = self.handle(chat, text)
            except Exception:                            # one bad answer must not stop the responder
                log.exception("offline answer failed")
                reply = "Sorry, that answer failed; the message is saved."
            self.tg._send_one(chat, reply, html="<b>" in reply)
        for cid, name, text in getattr(self.tg, "requests", [])[:5]:
            self.tg.send_admin(f"🔐 (offline) Access request from {name or 'unknown'} (chat {cid}): {text}\n"
                               f"/adduser {cid} once the system is running")
        if hasattr(self.tg, "requests"):
            self.tg.requests.clear()
        self.tg.commit()
        return len(texts)

    def run(self) -> None:
        log.info("offline responder and supervisor running")
        while True:
            try:
                self.supervise()
                if self._bridge_up():
                    time.sleep(20)
                    continue
                self.step()
            except Exception:
                log.exception("offline poll failed")
                time.sleep(15)


def main() -> None:
    from .app import build_bridge_parts
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    settings, store, tg = build_bridge_parts()
    OfflineBot(settings, store, tg).run()


if __name__ == "__main__":
    main()
