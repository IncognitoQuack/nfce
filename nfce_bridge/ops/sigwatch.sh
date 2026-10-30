#!/bin/bash
# Signal watcher (27 Oct): exits when a new paper-account fill OR a new index/stock signal (any non-scanner paper
# trade) appears, after MAX minutes (heartbeat), or at END. Prints what is new. Complements watch.sh (health, battery,
# Telegram). On 27 Oct a fills-only watcher missed a signal that the cost gate skipped.
#   bash ops/sigwatch.sh [MAX_MIN=30] [END=15:30]        (it reads the current maxima itself)
DB="$(cd "$(dirname "$0")/.." && pwd)/data/nfce.db"
MAX=${1:-30}; END=${2:-15:30}
FBASE=$(sqlite3 "$DB" "select coalesce(max(id),0) from account_fills")
SBASE=$(sqlite3 "$DB" "select coalesce(max(id),0) from paper_trades where book!='scanner'")
t0=$(date +%s)
while true; do
  f=$(sqlite3 "$DB" "select coalesce(max(id),0) from account_fills")
  s=$(sqlite3 "$DB" "select coalesce(max(id),0) from paper_trades where book!='scanner'")
  if [ "$f" -gt "$FBASE" ] || [ "$s" -gt "$SBASE" ]; then
    sleep 5
    echo "NEW (fills after $FBASE, signals after $SBASE):"
    sqlite3 -header "$DB" "select id, acct, ts, symbol, action, lots, price, round(realized) realized, reason from account_fills where id > $FBASE order by id"
    sqlite3 -header "$DB" "select id, book, opened, underlying, side, entry from paper_trades where book!='scanner' and id > $SBASE order by id"
    exit 0
  fi
  [ "$(date +%H:%M)" \> "$END" ] && { echo "end"; exit 0; }
  [ $(( $(date +%s) - t0 )) -ge $((MAX*60)) ] && { echo "heartbeat $(date +%H:%M), nothing new"; exit 0; }
  sleep 15
done
