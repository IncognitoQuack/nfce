#!/bin/bash
# Session watch (no python): exits with a reason. 2 = health problem 3 checks in a row (stale SENSEX ignored),
# 3 = battery <= 20% on battery, 4 = new Telegram note/request, 0 = end time.
DB=./data/nfce.db
END=${1:-15:40}
base=$(sqlite3 "$DB" "select coalesce(max(id),0) from events where source like 'telegram%' or source='admin'")
bad=0
while true; do
  [ "$(date +%H:%M)" \> "$END" ] && { echo "$(date +%H:%M) end time"; exit 0; }
  h=$(curl -s -m 10 localhost:8000/health)
  if [ -z "$h" ]; then
    bad=$((bad+1)); why="health unreachable"
  else
    probs=$(echo "$h" | sed -n 's/.*"problems":\[\([^]]*\)\].*/\1/p' | tr ',' '\n' | grep -v 'SENSEX' | grep -c '"')
    if [ "$probs" -gt 0 ]; then bad=$((bad+1)); why="$(echo "$h" | sed -n 's/.*"problems":\(\[[^]]*\]\).*/\1/p')"; else bad=0; fi
  fi
  [ $bad -ge 3 ] && { echo "$(date +%H:%M) PROBLEM x$bad: $why"; exit 2; }
  b=$(pmset -g batt)
  if echo "$b" | grep -q "Battery Power"; then
    p=$(echo "$b" | grep -o '[0-9]*%' | head -1 | tr -d %)
    [ -n "$p" ] && [ "$p" -le 20 ] && { echo "$(date +%H:%M) BATTERY $p%"; exit 3; }
  fi
  new=$(sqlite3 "$DB" "select coalesce(max(id),0) from events where source like 'telegram%' or source='admin'")
  if [ "$new" -gt "$base" ]; then
    echo "$(date +%H:%M) NEW MESSAGES:"
    sqlite3 "$DB" "select ts, source, substr(raw,1,600) from events where id > $base and (source like 'telegram%' or source='admin') order by id"
    exit 4
  fi
  sleep 60
done
