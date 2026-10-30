"""Telegram Bot API: send messages and read commands by long polling (no public URL needed).

Commands are accepted only from PRIVATE chats the bot knows: TELEGRAM_CHAT_ID, TELEGRAM_EXTRA_CHAT_IDS, the admins
(TELEGRAM_ADMIN_CHAT_IDS) and users the admin added with /adduser. Group chats are ignored. A message from an unknown
private chat is not executed; it is reported to the admins as an access request (`requests`).
Broadcasts (signals, reports) go to every known chat that has not muted itself (/stop); send_admin() goes to the
admins only; a reply goes to the chat that asked (reply_to). The update offset is
persisted through the supplied callbacks so a restart neither replays old commands nor loses new ones.
The bot token is part of the API URL, so httpx request logging is silenced to keep it out of log files.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

import httpx

log = logging.getLogger("nfce.telegram")
logging.getLogger("httpx").setLevel(logging.WARNING)      # httpx INFO lines contain the full URL (token)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class Telegram:
    def __init__(self, bot_token: str, chat_id: str, client: httpx.Client | None = None,
                 allowed_user_ids: set[str] | None = None, offset_get: Callable[[], int] | None = None,
                 offset_set: Callable[[int], None] | None = None, extra_chat_ids: set[str] | None = None,
                 admin_chat_ids: set[str] | None = None):
        import threading
        self.bot_token = bot_token
        self.chat_id = str(chat_id)
        self.client = client or httpx.Client(timeout=40.0)
        self.extra = {str(x) for x in (extra_chat_ids or set())}     # the owner's other private chats (creator)
        self.admins = {str(x) for x in (admin_chat_ids or set())} or ({self.chat_id} | self.extra)
        self.allowed = ({str(x) for x in (allowed_user_ids or set())} or {self.chat_id}) | self.extra | self.admins
        self.users: Callable[[], set[str]] = lambda: set()           # chats the admin added (/adduser)
        self.muted: Callable[[], set[str]] = lambda: set()           # chats that sent /stop
        self.requests: list[tuple[str, str, str]] = []                # (chat id, name, text) from unknown chats
        self._local = threading.local()                                # per-thread reply target
        self.sources: list[str] = []
        self._offset_get = offset_get or (lambda: self.__dict__.get("_offset", 0))
        self._offset_set = offset_set or (lambda v: self.__dict__.__setitem__("_offset", v))

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.bot_token}/{method}"

    @property
    def reply_to(self) -> str | None:
        return getattr(self._local, "chat", None)

    @reply_to.setter
    def reply_to(self, chat: str | None) -> None:
        self._local.chat = chat

    def known_chats(self) -> set[str]:
        return {self.chat_id} | self.extra | self.admins | set(self.users())

    def broadcast_targets(self) -> list[str]:
        """Every known chat that has not muted itself; the main chat first. Admins always get the broadcasts."""
        muted = set(self.muted()) - self.admins
        return [c for c in [self.chat_id] + sorted(self.known_chats() - {self.chat_id}) if c and c not in muted]

    def is_admin(self, chat: str | None) -> bool:
        return chat is None or str(chat) in self.admins           # None: a local call (console, tests)

    def send(self, text: str, html: bool = False, to=None) -> bool:
        if not self.enabled:
            log.info("telegram disabled; message:\n%s", text)
            return False
        targets = [self.reply_to] if self.reply_to else (list(to) if to else self.broadcast_targets())
        muted = set(self.muted()) - self.admins           # 26 Oct: a muted chat gets no direct replies either
        if self.reply_to and self.reply_to in muted:
            log.info("reply to muted chat %s not sent", self.reply_to)
            return True
        ok = True
        for chat in targets:
            ok &= self._send_one(chat, text, html)
        return ok

    def send_admin(self, text: str, html: bool = False) -> bool:
        """To the admins only, whoever asked (alerts, access requests, token warnings)."""
        if not self.enabled:
            log.info("telegram disabled; admin message:\n%s", text)
            return False
        ok = True
        for chat in sorted(self.admins):
            ok &= self._send_one(chat, text, html)
        return ok

    def _send_one(self, chat: str, text: str, html: bool) -> bool:
        ok = True
        for part in split_message(text):                 # long scanner reports: several messages, never truncated
            try:
                body = {"chat_id": chat, "text": part, "disable_web_page_preview": True}
                if html:
                    body["parse_mode"] = "HTML"
                r = self.client.post(self._url("sendMessage"), json=body)
                if r.status_code == 400 and html:          # a formatting slip must not lose the message
                    body.pop("parse_mode")
                    r = self.client.post(self._url("sendMessage"), json=body)
                if r.status_code != 200:
                    log.warning("telegram send failed: HTTP %s", r.status_code)
                ok &= r.status_code == 200
            except httpx.HTTPError as exc:
                log.warning("telegram send error: %s", type(exc).__name__)   # never log the URL
                return False
        return ok

    def send_document(self, path, caption: str = "", to=None) -> bool:
        if not self.enabled:
            return False
        ok = True
        for chat in ([self.reply_to] if self.reply_to else (list(to) if to else [self.chat_id])):
            try:
                with open(path, "rb") as f:
                    r = self.client.post(self._url("sendDocument"), data={"chat_id": chat, "caption": caption[:1000]},
                                         files={"document": (str(path).split("/")[-1], f, "text/csv")})
                ok &= r.status_code == 200
            except (httpx.HTTPError, OSError) as exc:
                log.warning("telegram document error: %s", type(exc).__name__)
                ok = False
        return ok

    def commit(self) -> None:
        """Acknowledge the updates returned by the last poll_commands() (Telegram then stops re-sending them)."""
        pending = getattr(self, "_pending", 0)
        if pending > self._offset_get():
            self._offset_set(pending)

    def poll_commands(self, timeout: int = 30) -> list[str]:
        """Return texts sent to the bot by an allowed sender in the configured private chat."""
        if not self.enabled:
            return []
        r = self.client.get(self._url("getUpdates"), params={"offset": self._offset_get(), "timeout": timeout})
        r.raise_for_status()
        out = []
        self.sources = []
        for upd in r.json().get("result", []):
            # FIX (M09): remember the offset; it is committed only after the commands were handled (commit())
            self._pending = max(getattr(self, "_pending", 0), self._offset_get(), upd["update_id"] + 1)
            msg = upd.get("message") or {}
            chat = msg.get("chat") or {}
            sender = str((msg.get("from") or {}).get("id", ""))
            cid = str(chat.get("id"))
            private = chat.get("type", "private") == "private"
            known = cid in self.known_chats()
            # in a private chat the sender IS the chat; admin-added users are allowed by their chat id
            if known and private and (sender in self.allowed or sender == cid) and msg.get("text"):
                out.append(msg["text"])
                self.sources.append(cid)
            elif private and not known and msg.get("text"):
                name = " ".join(x for x in ((msg.get("from") or {}).get("first_name"),
                                            (msg.get("from") or {}).get("username")) if x)
                self.requests.append((cid, name[:60], msg["text"][:200]))
                log.info("access request from chat %s", cid)
            elif msg:
                log.info("ignored a Telegram message from chat %s / sender %s", chat.get("id"), sender or "?")
        return out


def split_message(text: str, limit: int = 3900) -> list[str]:
    """Split on line breaks into parts of at most `limit` characters (Telegram's limit is 4096)."""
    parts, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:                         # a single over-long line is cut hard
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) + 1 > limit and cur:
            parts.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur or not parts:
        parts.append(cur)
    return parts
