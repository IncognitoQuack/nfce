#!/bin/bash
# One-time setup:  bash setup.sh
# Creates .venv, installs packages, generates WEBHOOK_SECRET, runs the tests, then checks .env.
set -e
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"

if [ ! -d .venv ]; then
  echo "== creating .venv"
  "$PY" -m venv .venv
fi
echo "== installing packages"
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt

[ -f .env ] || cp .env.example .env
.venv/bin/python -c "from pathlib import Path; from bridge.check_setup import ensure_webhook_secret as e; print('== WEBHOOK_SECRET generated' if e(Path('.env')) else '== WEBHOOK_SECRET already set')"
chmod 600 .env

echo "== running tests"
.venv/bin/python -m pytest -q -p no:cacheprovider

echo "== checking .env"
.venv/bin/python -m bridge.check_setup --no-send || true
echo
echo "Next: fill the missing items in .env, then run:  .venv/bin/python -m bridge.check_setup"
echo "Every trading day:  bash start.sh"
