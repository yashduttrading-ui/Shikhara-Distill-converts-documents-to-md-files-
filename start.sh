#!/bin/bash
# MD Vault watcher control: start / stop / status / restart

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$DIR/converter.pid"
LOG_FILE="$DIR/converter.log"
PYTHON="${PYTHON:-python3}"

start() {
  if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Already running (PID $(cat "$PID_FILE"))"
    exit 0
  fi
  cd "$DIR"
  nohup "$PYTHON" converter.py >> "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  echo "Started MD Vault watcher (PID $(cat "$PID_FILE"))"
}

stop() {
  if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    kill "$(cat "$PID_FILE")"
    rm -f "$PID_FILE"
    echo "Stopped."
  else
    echo "Not running."
    rm -f "$PID_FILE"
  fi
}

status() {
  if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Running (PID $(cat "$PID_FILE"))"
  else
    echo "Not running."
  fi
}

case "$1" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  restart) stop; start ;;
  *) echo "Usage: $0 {start|stop|status|restart}" ;;
esac
