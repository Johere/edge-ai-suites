#!/usr/bin/env bash
# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# Bring up the shared RTSP server for the 0818 demo (see mediamtx.demo.yml for
# why the pushers must not own it).
#
# Idempotent: if :8557 is already listening this exits 0 without touching it, so
# start-demo.sh can call it unconditionally.
#
# Usage:
#   bash start_rtsp_server.sh            # start (or report already-running)
#   bash start_rtsp_server.sh --stop     # stop the server this script started
#   bash start_rtsp_server.sh --status
#
# Environment:
#   MEDIAMTX_BIN=/path/to/mediamtx   # default: ~/.local/bin/mediamtx

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$SCRIPT_DIR/mediamtx.demo.yml"
RUN_DIR="$SCRIPT_DIR/../.run"
PID_FILE="$RUN_DIR/mediamtx.pid"
LOG_FILE="$RUN_DIR/mediamtx.log"
MEDIAMTX_BIN="${MEDIAMTX_BIN:-$HOME/.local/bin/mediamtx}"
RTSP_PORT=8557

port_is_listening() {
  command -v ss >/dev/null 2>&1 || return 1
  ss -H -ltn "sport = :$RTSP_PORT" 2>/dev/null | grep -q .
}

running_pid() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid
  pid="$(cat "$PID_FILE")"
  is_server_pid "$pid" && printf '%s\n' "$pid"
}

is_server_pid() {
  local pid="$1" command
  [[ -n "$pid" ]] || return 1
  command="$(ps -p "$pid" -o args= 2>/dev/null || true)"
  [[ "$command" == *"$MEDIAMTX_BIN"* && "$command" == *"$CONFIG"* ]]
}

find_server_pids() {
  local pid command
  while read -r pid command; do
    [[ "$command" == *"$MEDIAMTX_BIN"* && "$command" == *"$CONFIG"* ]] && \
      printf '%s\n' "$pid"
  done < <(ps -u "$(id -u)" -o pid=,args=)
}

stop_server_pid() {
  local pid="$1"
  kill -TERM "$pid" 2>/dev/null || true
  for _ in {1..25}; do kill -0 "$pid" 2>/dev/null || break; sleep 0.2; done
  kill -KILL "$pid" 2>/dev/null || true
  echo "stopped shared MediaMTX (pid $pid)"
}

case "${1:-}" in
  --status)
    if pid="$(running_pid)"; then
      echo "shared MediaMTX running on :$RTSP_PORT (pid $pid)"
    elif pid="$(find_server_pids | head -n 1)"; then
      echo "shared MediaMTX running without PID file on :$RTSP_PORT (pid $pid)"
    elif port_is_listening; then
      echo "something else is listening on :$RTSP_PORT (not started by this script)"
    else
      echo "nothing listening on :$RTSP_PORT"
    fi
    exit 0
    ;;
  --stop)
    if pid="$(running_pid)"; then
      stop_server_pid "$pid"
    else
      mapfile -t server_pids < <(find_server_pids)
      if (( ${#server_pids[@]} == 0 )); then
        echo "shared MediaMTX is not running"
      else
        for pid in "${server_pids[@]}"; do stop_server_pid "$pid"; done
      fi
    fi
    rm -f "$PID_FILE"
    exit 0
    ;;
  "" ) ;;
  * ) echo "unknown option: $1" >&2; exit 1 ;;
esac

if pid="$(running_pid)"; then
  echo "shared MediaMTX already running on :$RTSP_PORT (pid $pid)"
  exit 0
fi

if port_is_listening; then
  # Most likely a pusher-owned MediaMTX from an earlier session, which declares
  # only its own path. Say so plainly rather than letting the second stream fail
  # later with an opaque publish rejection.
  echo "warning: :$RTSP_PORT is already in use by a server this script did not start." >&2
  echo "         If it was started by timeline_to_rtsp.sh it declares only one path," >&2
  echo "         and the second camera will be refused. Stop that pusher first." >&2
  exit 0
fi

[[ -x "$MEDIAMTX_BIN" ]] || {
  echo "error: MediaMTX is not executable: $MEDIAMTX_BIN" >&2
  echo "       install it there or set MEDIAMTX_BIN" >&2
  exit 1
}
[[ -f "$CONFIG" ]] || { echo "error: config not found: $CONFIG" >&2; exit 1; }

mkdir -p "$RUN_DIR"
"$MEDIAMTX_BIN" "$CONFIG" >"$LOG_FILE" 2>&1 &
pid=$!
echo "$pid" >"$PID_FILE"

for _ in {1..25}; do
  port_is_listening && break
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "error: MediaMTX failed to start:" >&2
    tail -n 20 "$LOG_FILE" >&2
    rm -f "$PID_FILE"
    exit 1
  fi
  sleep 0.2
done

port_is_listening || {
  echo "error: MediaMTX did not begin listening on :$RTSP_PORT" >&2
  tail -n 20 "$LOG_FILE" >&2
  exit 1
}

echo "started shared MediaMTX on :$RTSP_PORT (pid $pid) — paths: live/child, live/eldercare"
