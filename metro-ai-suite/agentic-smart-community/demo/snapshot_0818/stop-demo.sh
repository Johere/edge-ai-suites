#!/usr/bin/env bash
# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# Stop the 0818 demo: the two RTSP pushers, the shared MediaMTX, and the app tier.
#
# vllm-ipex-serving is deliberately left running — its FP8 recompile on Intel XPU
# costs minutes, and nothing here needs it restarted. Use `setup_docker.sh --down`
# to take the whole stack down.
#
# Usage:
#   bash demo/snapshot_0818/stop-demo.sh              # streams + app tier
#   bash demo/snapshot_0818/stop-demo.sh --streams    # streams only
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_COMPONENT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
if [[ ! -f "$DEFAULT_COMPONENT_ROOT/setup_docker.sh" ]]; then
  DEFAULT_COMPONENT_ROOT="$HOME/edge-ai-suites/metro-ai-suite/agentic-smart-community"
fi
REPO_DIR="${COMPONENT_ROOT:-$DEFAULT_COMPONENT_ROOT}"
RUN_DIR="$SCRIPT_DIR/.run"
PUSHER_SCRIPT="$SCRIPT_DIR/helpers/timeline_to_rtsp.sh"

STREAMS_ONLY=0
[[ "${1:-}" == "--streams" ]] && STREAMS_ONLY=1

if (( ! STREAMS_ONLY )) && [[ ! -f "$REPO_DIR/setup_docker.sh" ]]; then
  echo "error: Agentic Smart Community source not found at $REPO_DIR" >&2
  echo "       set COMPONENT_ROOT to its directory, or stop streams only with --streams" >&2
  exit 1
fi

pusher_path_for_monitor() {
  case "$1" in
    cam_child) echo "child" ;;
    cam_elder_care) echo "eldercare" ;;
    *) return 1 ;;
  esac
}

is_pusher_pid() {
  local pid="$1" monitor="$2" stream_path command
  stream_path="$(pusher_path_for_monitor "$monitor")"
  command="$(ps -p "$pid" -o args= 2>/dev/null || true)"
  [[ "$command" == *"$PUSHER_SCRIPT"* && \
     "$command" == *"--url rtsp://localhost:8557/live/$stream_path"* ]]
}

find_pusher_pids() {
  local monitor="$1" stream_path pid command
  stream_path="$(pusher_path_for_monitor "$monitor")"
  while read -r pid command; do
    [[ "$command" == *"$PUSHER_SCRIPT"* && \
       "$command" == *"--url rtsp://localhost:8557/live/$stream_path"* ]] && \
      printf '%s\n' "$pid"
  done < <(ps -u "$(id -u)" -o pid=,args=)
}

stop_pusher_pid() {
  local monitor="$1" pid="$2"
  # Stop the ffmpeg child first. If the wrapper has to be SIGKILLed later, this
  # prevents it from leaving an orphan publisher connected to MediaMTX.
  pkill -TERM -P "$pid" 2>/dev/null || true
  kill -TERM "$pid" 2>/dev/null || true
  for _ in {1..25}; do kill -0 "$pid" 2>/dev/null || break; sleep 0.2; done
  if kill -0 "$pid" 2>/dev/null; then
    pkill -KILL -P "$pid" 2>/dev/null || true
    kill -KILL "$pid" 2>/dev/null || true
  fi
  echo "stopped $monitor pusher (pid $pid)"
}

stop_pusher() {
  local monitor="$1"
  local pid_file="$RUN_DIR/$monitor.pid"
  local pid
  declare -A candidate_pids=()

  if [[ -f "$pid_file" ]]; then
    pid="$(cat "$pid_file")"
    if [[ -n "$pid" ]] && is_pusher_pid "$pid" "$monitor"; then
      candidate_pids["$pid"]=1
    fi
  fi

  # PID files can be removed by an interrupted prior shutdown while the wrapper
  # continues under init. Recover only this user's pusher for this exact snapshot.
  while read -r pid; do
    [[ -n "$pid" ]] && candidate_pids["$pid"]=1
  done < <(find_pusher_pids "$monitor")

  for pid in "${!candidate_pids[@]}"; do
    stop_pusher_pid "$monitor" "$pid"
  done
  rm -f "$pid_file"
}

stop_pusher cam_child
stop_pusher cam_elder_care
rm -f "$RUN_DIR/active-streams.txt"

bash "$SCRIPT_DIR/helpers/start_rtsp_server.sh" --stop

if (( STREAMS_ONLY )); then
  echo "streams stopped; app tier left running"
  exit 0
fi

# shellcheck disable=SC1091
source "$REPO_DIR/docker/set_env.sh"
echo "stopping the app tier (setup_docker.sh --light-down)…"
bash "$REPO_DIR/setup_docker.sh" --light-down
echo "done. vllm-ipex-serving left running — use setup_docker.sh --down to stop it too."
