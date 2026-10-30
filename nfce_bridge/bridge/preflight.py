"""Preflight self-check: is the system aligned and ready? Offline (no Upstox or Telegram calls, no messages sent).

    python -m bridge.preflight          (from nfce_bridge/; exit code 0 = ready, 1 = problems)

Checks: .env keys; the database (integrity, writable); every paper account's ledger reconciles to its cash;
no positions left open after the close; frozen-file hashes match REGISTRY.md; the range models load; free disk;
the offline responder / supervisor is running; the Mac is on the charger; the Upstox token (information only).
"""
from __future__ import annotations

import hashlib
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # nfce_bridge/
REPO = ROOT.parent                                     # nfce/
NEEDED = ("UPSTOX_API_KEY", "UPSTOX_API_SECRET", "UPSTOX_REDIRECT_URI", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
          "TELEGRAM_ADMIN_CHAT_IDS")


def ledger_problems(store, accounts: dict) -> list[str]:
    """Each account's cash must equal its capital (or last RESET) plus every cash flow since, within ₹1."""
    out = []
    for name, cap in accounts.items():
        cash = store.kv_get(f"account_{name}_cash")
        if cash is None:
            continue                                   # not created yet: it starts with its capital
        try:
            rows = store.db.execute("SELECT action, cash_flow, cash_after FROM account_fills WHERE acct=? ORDER BY id",
                                    (name,)).fetchall()
        except sqlite3.OperationalError:
            rows = []
        start = float(store.kv_get(f"account_{name}_capital", cap))
        expect = start
        for action, flow, after in rows:
            expect = float(after) if action == "RESET" else expect + float(flow)
        if abs(expect - float(cash)) > 1.0:
            out.append(f"account {name}: cash ₹{float(cash):,.2f} does not match the ledger (₹{expect:,.2f})")
    return out


def registry_problems(repo: Path = REPO) -> list[str]:
    """Every file in REGISTRY.md's frozen-file table must still have its registered SHA-256."""
    reg = repo / "REGISTRY.md"
    if not reg.exists():
        return ["REGISTRY.md not found"]
    text = reg.read_text()
    m = re.search(r"^#+ Frozen files \(v\d[^\n]*\n(.*?)(?=^#|\Z)", text, re.M | re.S)   # the CURRENT table only
    table = m.group(1) if m else text                    # superseded tables and closed tests keep old hashes
    out = []
    for path, want in re.findall(r"^\|\s*(nfce_[\w/]+\.py)[^|]*\|\s*`([0-9a-f]{64})`\s*\|", table, re.M):
        f = repo / path
        if not f.exists():
            out.append(f"frozen file missing: {path}")
        elif hashlib.sha256(f.read_bytes()).hexdigest() != want:
            out.append(f"frozen file changed since registration: {path} (re-register or revert)")
    return out


def checks() -> list[tuple[bool, str]]:
    from .check_setup import token_status
    from .config import Settings
    from .store import Store
    res: list[tuple[bool, str]] = []
    s = Settings.from_env()
    import os
    missing = [k for k in NEEDED if not os.environ.get(k)]
    res.append((not missing, ".env: all keys set" if not missing else f".env: missing {', '.join(missing)}"))
    try:
        st = Store(s.db_path)
        ok = st.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        res.append((ok, f"database {s.db_path.name}: integrity {'ok' if ok else 'FAILED'}"))
        lp = ledger_problems(st, s.accounts)
        res.append((not lp, "paper accounts: every ledger reconciles to its cash" if not lp else "; ".join(lp)))
        n = datetime.now()
        open_n = 0
        try:
            open_n = st.db.execute("SELECT COUNT(*) FROM account_positions WHERE status='OPEN'").fetchone()[0]
        except sqlite3.OperationalError:
            pass
        after_close = n.hour * 60 + n.minute > 15 * 60 + 30 or n.hour < 9
        res.append((not (after_close and open_n), f"open account positions: {open_n}"
                    + (" (should be 0 outside market hours)" if after_close and open_n else "")))
        res.append((True, f"accounts: {', '.join(f'{k} ({s.account_strategies.get(k, 'base')})' for k in s.accounts)}"))
    except sqlite3.Error as exc:
        res.append((False, f"database: {exc}"))
    rp = registry_problems()
    res.append((not rp, "frozen files: all match REGISTRY.md" if not rp else "; ".join(rp)))
    try:
        import pickle
        models = sorted((ROOT / "bridge" / "models").glob("*.pkl"))
        for m in models:
            pickle.loads(m.read_bytes())
        res.append((bool(models), f"range models load ({len(models)})"))
    except Exception as exc:                            # a version mismatch shows here, not at 09:30
        res.append((False, f"range models: {type(exc).__name__}: {exc}"[:200]))
    free = shutil.disk_usage(ROOT).free / 1e9
    res.append((free > 2, f"free disk: {free:.1f} GB"))
    sup = subprocess.run(["pgrep", "-f", "bridge.offline_bot"], capture_output=True).returncode == 0
    res.append((True, "offline responder / supervisor: running" if sup else      # opt-in (owner, 22 Oct)
                "offline responder / supervisor: off (optional: nfce supervisor on)"))
    from .bot import power_status
    ac, pct = power_status()
    res.append((ac is not False, "power: on the charger" if ac else f"power: ON BATTERY ({pct}%): connect the charger"))
    ok, msg = token_status(s.token_file)
    res.append((True, f"Upstox token: {msg}" + ("" if ok else " (the owner signs in at the start)")))
    return res


def main() -> int:
    res = checks()
    for ok, msg in res:
        print(("  [ok] " if ok else "  [!!] ") + msg)
    bad = sum(not ok for ok, _ in res)
    print("READY" if not bad else f"{bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
