"""Daily start: log in to Upstox if today's token is missing or expired, then run the bridge.

    python -m bridge.start      (start.sh runs this)
"""
from __future__ import annotations

from .check_setup import token_status
from .config import Settings


def main() -> None:
    s = Settings.from_env()
    if s.provider == "upstox":
        ok, msg = token_status(s.token_file)
        print(msg)
        if not ok:
            from . import upstox_login
            try:
                upstox_login.main()
            except SystemExit as exc:           # nobody at the Mac (e.g. an automatic restart): run anyway
                print(f"Upstox login not completed ({exc}). Starting without market data; "
                      "the admin can sign in from Telegram with /login.")
    from . import app
    app.main()


if __name__ == "__main__":
    main()
