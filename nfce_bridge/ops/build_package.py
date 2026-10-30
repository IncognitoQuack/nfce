"""Build the shareable package ~/Downloads/Final Trade Software.zip from the project, refusing to write it if any
secret or chat id from .env appears in a packaged file. (25 Oct: moved here from a temporary folder that macOS
cleaned up, which had silently left the old zip in place.)

usage (from nfce_bridge/): .venv/bin/python ops/build_package.py
"""
import fnmatch
import hashlib
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

SRC = Path(__file__).resolve().parents[2]                       # ~/Downloads/nfce
OUT = Path.home() / "Downloads" / "Final Trade Software.zip"
EX_DIRS = {".venv", "venv", "__pycache__", ".pytest_cache", "data", "tv_logs_private", "node_modules"}
EX_FILES = [".env", "*.db", "*.db-*", "*token*", "*.csv", "*.pkl", "*.pyc", ".DS_Store", "*.log"]
KEEP = {"nfce_bridge/bridge/models/range_r4.pkl", "nfce_bridge/.env.example"}


def secrets() -> list[str]:
    env = {}
    for line in open(SRC / "nfce_bridge" / ".env"):
        k, sep, v = line.strip().partition("=")
        if sep and not k.startswith("#"):
            env[k.strip()] = v.strip().strip('"').strip("'")
    out = [env[k] for k in ("UPSTOX_API_KEY", "UPSTOX_API_SECRET", "TELEGRAM_BOT_TOKEN", "WEBHOOK_SECRET") if env.get(k)]
    for k in ("TELEGRAM_CHAT_ID", "TELEGRAM_ADMIN_CHAT_IDS", "TELEGRAM_EXTRA_CHAT_IDS"):
        out += [x.strip() for x in env.get(k, "").split(",") if x.strip()]
    return out


def main() -> int:
    stage = Path(tempfile.mkdtemp()) / "Final Trade Software"
    files = []
    for p in SRC.rglob("*"):
        rel = p.relative_to(SRC)
        if p.is_dir() or any(part in EX_DIRS for part in rel.parts[:-1]):
            continue
        r = rel.as_posix()
        if r not in KEEP and not r.startswith("evidence/ledgers/") and any(fnmatch.fnmatch(p.name, x) for x in EX_FILES):
            continue
        d = stage / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, d)
        files.append(d)
    if not (stage / "docs").exists():
        print("refused: the docs/ folder (reviews, research reports) is missing from the project")
        return 1
    needles = secrets()
    hits = sorted({str(f.relative_to(stage)) for f in files for v in needles if v.encode() in f.read_bytes()})
    if hits:
        print("refused: secrets or chat ids found in:", *hits, sep="\n  ")
        return 1
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(files):
            z.write(f, Path("Final Trade Software") / f.relative_to(stage))
    print(f"{OUT.name}: {len(files)} files, {OUT.stat().st_size / 1e6:.1f} MB, secrets found 0, "
          f"sha256 {hashlib.sha256(OUT.read_bytes()).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
