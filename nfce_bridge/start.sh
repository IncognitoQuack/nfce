#!/bin/bash
# Every trading day:  bash start.sh
# Logs in to Upstox if needed (the browser opens; or sign in later from Telegram with /login), then runs the bridge
# until you press Ctrl+C. While it runs it keeps the Mac awake, and it restarts the bridge by itself after a crash
# or an admin /restart.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Run 'bash setup.sh' first."
  exit 1
fi
if command -v caffeinate >/dev/null 2>&1; then
  caffeinate -dimsu -w $$ &          # no sleep while this script runs (on battery, keep the lid open)
fi
trap 'echo; echo "Stopped."; exit 0' INT TERM
echo "Preflight $(date '+%Y-%m-%d %H:%M'):"
.venv/bin/python -m bridge.preflight || echo "Preflight found problems (listed above); starting anyway."
fails=0
while true; do
  started=$(date +%s)
  .venv/bin/python -m bridge.start
  code=$?
  [ $code -eq 0 ] && break                        # a normal stop (Ctrl+C)
  if [ $code -ne 3 ]; then                        # 3 = /restart from the admin: straight back
    if [ $(( $(date +%s) - started )) -lt 60 ]; then fails=$((fails + 1)); else fails=0; fi
    if [ $fails -ge 5 ]; then
      echo "The bridge failed 5 times in a row within a minute of starting; giving up. See the messages above."
      exit 1
    fi
    echo "The bridge stopped (exit code $code); restarting in 10 s. Press Ctrl+C to stop."
    sleep 10
  fi
done
