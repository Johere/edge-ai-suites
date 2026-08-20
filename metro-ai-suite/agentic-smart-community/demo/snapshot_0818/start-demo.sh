#!/usr/bin/env bash
# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# One-shot launcher for the 0818 two-camera demo (child safety + elder care).
#
#   export SMART_COMMUNITY_DEMO_CHILD_CLIPS=/absolute/path/child_safety_snippets
#   export SMART_COMMUNITY_DEMO_ELDER_CLIPS=/absolute/path/elder_care_snippets
#   bash demo/snapshot_0818/start-demo.sh
#   bash demo/snapshot_0818/stop-demo.sh
#
# Both variables default to the clip directories in this snapshot. A camera whose
# directory is missing or holds no MP4s is warned about and skipped; the other one
# still starts.
#
# Unlike the ready-to-run demo this streams from a timeline EDL rather than
# looping a file, so the picture tracks the real clock: the child living room is
# dark and motionless from 21:30 to 06:30, and the elder room's night events land
# at night. That is also why demo/videos/start-streams.sh is not reused — it only
# knows how to loop a single file, and it keeps its run state in
# demo/videos/.run/active-streams.txt, which the ready-to-run launcher reads to
# decide which monitors to register.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_COMPONENT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
if [[ ! -f "$DEFAULT_COMPONENT_ROOT/setup_docker.sh" ]]; then
  DEFAULT_COMPONENT_ROOT="$HOME/edge-ai-suites/metro-ai-suite/agentic-smart-community"
fi
REPO_DIR="${COMPONENT_ROOT:-$DEFAULT_COMPONENT_ROOT}"
HELPERS="$SCRIPT_DIR/helpers"
RUN_DIR="$SCRIPT_DIR/.run"
DATA_DIR="${SMART_COMMUNITY_DATA_DIR:-$HOME/.mcp-smart-community}"
SUMMARY_URL="${SUMMARY_SERVICE_URL:-http://localhost:8192}"

ACTIVE_STREAMS_FILE="$RUN_DIR/active-streams.txt"

[[ -f "$REPO_DIR/setup_docker.sh" ]] || {
  echo "error: Agentic Smart Community source not found at $REPO_DIR" >&2
  echo "       clone it first, or set COMPONENT_ROOT to its directory" >&2
  exit 1
}
command -v md5sum >/dev/null || { echo "md5sum not found in PATH" >&2; exit 1; }
command -v ffmpeg  >/dev/null || { echo "ffmpeg not found in PATH" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 not found in PATH" >&2; exit 1; }

mkdir -p "$RUN_DIR"

# ── 1. Decide which cameras can run ─────────────────────────────────────────
# Clip libraries are user-provided: demo/.gitignore excludes every *.mp4, so a
# fresh clone has none of them.
CHILD_CLIPS="${SMART_COMMUNITY_DEMO_CHILD_CLIPS:-$HELPERS/child_safety_snippets}"
ELDER_CLIPS="${SMART_COMMUNITY_DEMO_ELDER_CLIPS:-$HELPERS/elder_care_snippets}"

has_clips() {
  local dir="$1"
  [[ -d "$dir" ]] || return 1
  compgen -G "$dir/*.mp4" >/dev/null 2>&1
}

CHILD_ENABLED=1
ELDER_ENABLED=1
has_clips "$CHILD_CLIPS" || {
  echo "warning: no MP4s in $CHILD_CLIPS — skipping cam_child" >&2
  CHILD_ENABLED=0
}
has_clips "$ELDER_CLIPS" || {
  echo "warning: no MP4s in $ELDER_CLIPS — skipping cam_elder_care" >&2
  ELDER_ENABLED=0
}
if (( ! CHILD_ENABLED && ! ELDER_ENABLED )); then
  echo "error: no clip library found for either camera — nothing to start" >&2
  exit 1
fi

# ── 2. Normalize the clip libraries ─────────────────────────────────────────
# Output always lands inside this snapshot, whatever the source directory was:
# each timeline's `clips_dir` is resolved relative to the timeline file, so the
# normalized library has to sit where the timeline expects it. That also lets the
# user's clip directory be read-only. Reruns skip up-to-date outputs, so a warm
# rerun is a fast ffprobe pass rather than a re-encode.
if (( CHILD_ENABLED )); then
  echo "preparing child-safety clips…"
  bash "$HELPERS/child_safety_snippets/prepare_child_clips.sh" "$CHILD_CLIPS"
fi
if (( ELDER_ENABLED )); then
  echo "preparing elder-care clips…"
  bash "$HELPERS/normalize_clips_for_concat.sh" \
    "$ELDER_CLIPS" "$HELPERS/elder_care_snippets/normalized"
fi

# ── 3. Build and gate on the timelines ──────────────────────────────────────
# --verify's per-hour budget check becomes a launch gate here rather than a report
# somebody has to remember to read.
build_timeline() {
  local timeline="$1" label="$2"
  echo "building timeline: $label"
  if ! python3 "$HELPERS/build_timeline.py" \
        --timeline "$HELPERS/$timeline" --mode rtsp24h --verify \
        >"$RUN_DIR/${label}-verify.log" 2>&1; then
    echo "error: $timeline failed verification — see $RUN_DIR/${label}-verify.log" >&2
    tail -n 20 "$RUN_DIR/${label}-verify.log" >&2
    exit 1
  fi
  grep -E '^  (total events|observed seconds)' "$RUN_DIR/${label}-verify.log" || true
}

(( CHILD_ENABLED )) && build_timeline child_safety_timeline.yaml child_safety
(( ELDER_ENABLED ))  && build_timeline elder_care_timeline.yaml  elder_care

# ── 4. Shared RTSP server ───────────────────────────────────────────────────
# Must precede the pushers: each pusher would otherwise start its own MediaMTX
# declaring only its own path, and would kill it again on exit. See
# helpers/mediamtx.demo.yml.
bash "$HELPERS/start_rtsp_server.sh"

# ── 5. Push each enabled stream ─────────────────────────────────────────────
# No --at: timeline_to_rtsp.sh defaults to `now` and re-anchors to the wall clock
# on every relaunch, which is what keeps the picture aligned with real time.
: >"$ACTIVE_STREAMS_FILE"

start_stream() {
  local monitor="$1" timeline="$2" path="$3"
  local pid_file="$RUN_DIR/$monitor.pid" log_file="$RUN_DIR/$monitor.log"

  if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
    echo "  $monitor already streaming (pid $(cat "$pid_file"))"
    echo "$monitor" >>"$ACTIVE_STREAMS_FILE"
    return 0
  fi

  nohup bash "$HELPERS/timeline_to_rtsp.sh" \
    --timeline "$HELPERS/$timeline" \
    --url "rtsp://localhost:8557/$path" \
    >"$log_file" 2>&1 &
  local pid=$!
  echo "$pid" >"$pid_file"

  # Fail loudly here rather than leaving a monitor registered against a dead path.
  sleep 3
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "error: $monitor pusher exited immediately — see $log_file" >&2
    tail -n 20 "$log_file" >&2
    rm -f "$pid_file"
    return 1
  fi
  echo "  $monitor -> rtsp://localhost:8557/$path (pid $pid)"
  echo "$monitor" >>"$ACTIVE_STREAMS_FILE"
}

echo "starting RTSP pushers…"
(( CHILD_ENABLED )) && start_stream cam_child      child_safety_timeline.yaml live/child
(( ELDER_ENABLED ))  && start_stream cam_elder_care elder_care_timeline.yaml   live/eldercare

# ── 6. Stage the elder-care alert rule ──────────────────────────────────────
# The container sees this host data directory at the same absolute path. Its
# Node process does not expand `~`, so render the portable source config below
# with this resolved path before persisting it as the runtime config.
mkdir -p "$DATA_DIR"
DATA_DIR="$(cd "$DATA_DIR" && pwd)"
if (( ELDER_ENABLED )); then
  install -D -m 0644 "$SCRIPT_DIR/elder_care/evaluate_rules.py" \
    "$DATA_DIR/use-cases/elder_care/evaluate_rules.py"
  echo "staged elder_care evaluate_rules.py"
fi

# ── 7. Persist config + the matching monitor subset ─────────────────────────
RUNTIME_CONFIG="$(mktemp)"
FILTERED_MONITORS="$(mktemp)"
trap 'rm -f "$RUNTIME_CONFIG" "$FILTERED_MONITORS"' EXIT

python3 - "$SCRIPT_DIR/config.demo.yaml" "$RUNTIME_CONFIG" "$DATA_DIR" <<'PY'
import sys

import yaml

source_path, output_path, data_dir = sys.argv[1:]
with open(source_path, encoding="utf-8") as handle:
  config = yaml.safe_load(handle) or {}

elder_care = (config.get("use_case_dict") or {}).get("elder_care")
if elder_care is None:
  raise SystemExit("config.demo.yaml is missing use_case_dict.elder_care")
elder_care["evaluate_rules_path"] = (
  f"{data_dir}/use-cases/elder_care/evaluate_rules.py"
)

with open(output_path, "w", encoding="utf-8") as handle:
  yaml.safe_dump(config, handle, sort_keys=False, allow_unicode=True)
PY

python3 - "$SCRIPT_DIR/monitors.demo.yaml" "$ACTIVE_STREAMS_FILE" "$FILTERED_MONITORS" <<'PY'
import sys

import yaml

monitors_path, active_path, output_path = sys.argv[1:]
with open(active_path, encoding="utf-8") as handle:
  active = {line.strip() for line in handle if line.strip()}
with open(monitors_path, encoding="utf-8") as handle:
  config = yaml.safe_load(handle) or {}

monitors = config.get("monitors") or {}
config["monitors"] = {}
for monitor_id, monitor in monitors.items():
  if monitor_id not in active:
    continue
  monitor = dict(monitor)
  monitor["enabled"] = True
  config["monitors"][monitor_id] = monitor
with open(output_path, "w", encoding="utf-8") as handle:
  yaml.safe_dump(config, handle, sort_keys=False, allow_unicode=True)

print(f"  prepared {len(config['monitors'])} monitor(s) for active streams")
PY

persist_demo_config() {
  local source="$1" target="$2" backup

  [[ ! -L "$target" ]] || { echo "refusing to overwrite symbolic link: $target" >&2; return 1; }
  [[ ! -e "$target" || -f "$target" ]] || { echo "refusing to overwrite non-regular file: $target" >&2; return 1; }
  if [[ -f "$target" ]] && [[ "$(md5sum "$source" | awk '{print $1}')" == "$(md5sum "$target" | awk '{print $1}')" ]]; then
    return
  fi
  if [[ -f "$target" ]]; then
    backup="$target.$(date '+%Y%m%d-%H%M%S').bak"
    [[ ! -e "$backup" && ! -L "$backup" ]] || { echo "backup already exists: $backup" >&2; return 1; }
    cp -- "$target" "$backup"
    echo "backed up ${target} to ${backup}"
  fi
  cp -- "$source" "$target"
  echo "updated $target from $source"
}

persist_demo_config "$RUNTIME_CONFIG" "$DATA_DIR/config.yaml"
persist_demo_config "$FILTERED_MONITORS" "$DATA_DIR/monitors.yaml"
rm -f "$RUNTIME_CONFIG"
rm -f "$FILTERED_MONITORS"
trap - EXIT

# ── 8. Bring the stack up ───────────────────────────────────────────────────
# set_env.sh forwards the host timezone into the MCP container, so SQLite's
# datetime('now','localtime') on every event and alert matches the wall clock the
# timeline is aligned to. Skipping it would mix local-time seeded rows with
# UTC live rows in one table — an offset that is nearly invisible in a report.
# shellcheck disable=SC1091
source "$REPO_DIR/docker/set_env.sh"
if [ -n "$(docker compose -f "$REPO_DIR/docker/compose.yaml" ps -q \
    smart-community-mcp-server multilevel-video-understanding videostream-analytics 2>/dev/null)" ]; then
  echo "app tier already running — bouncing it (--light-down) to reload the demo config…"
  bash "$REPO_DIR/setup_docker.sh" --light-down
fi
echo "starting the stack (setup_docker.sh --light)…"
bash "$REPO_DIR/setup_docker.sh" --light

# ── 9. Register the VLM task prompts (idempotent) ───────────────────────────
# After the stack, not before: the bounce above takes :8192 down with it, so
# registering earlier just posts into a closed port.
register_task() {
  local task_name="$1" prompt_file="$2" code
  [[ -f "$prompt_file" ]] || { echo "  skip $task_name (no $prompt_file)"; return 0; }
  # Dynamic task registrations survive a container restart, and re-POSTing one
  # returns 409 already_registered. That is the normal path on every rerun, so it
  # must not be reported as a failure.
  # Prompts staged for use_case_register use `## SECTION` headings, which the
  # service rejects (422 missing_anchors); the converter is a no-op on files that
  # already carry `SECTION = '''…'''` anchors.
  code="$(python3 "$HELPERS/prompt_md_to_task.py" "$prompt_file" \
       | jq -Rs --arg name "$task_name" \
         '{task_name: $name, mode: "full", content: {text: .}}' \
       | curl -s -o /dev/null -w '%{http_code}' "$SUMMARY_URL/v1/tasks" \
         -H "Content-Type: application/json" --data-binary @-)"
  case "$code" in
    2*)  echo "  registered $task_name" ;;
    409) echo "  $task_name already registered" ;;
    *)   echo "  warning: registering $task_name returned HTTP $code" >&2 ;;
  esac
}

if command -v jq >/dev/null && command -v curl >/dev/null; then
  echo "registering video-summary tasks…"
  for _ in {1..30}; do
    curl -fsS "$SUMMARY_URL/v1/tasks" >/dev/null 2>&1 && break
    sleep 1
  done
  (( CHILD_ENABLED )) && register_task child_safety_monitor "$REPO_DIR/demo/prompts/child_safety_monitor.txt"
  (( ELDER_ENABLED ))  && register_task elder_care_monitor   "$SCRIPT_DIR/elder_care/prompt.md"
else
  echo "warning: jq/curl missing — register the VLM task prompts manually" >&2
fi

cat <<EOF

demo is up. Active streams: $(paste -sd' ' "$ACTIVE_STREAMS_FILE")

Next: seed six days of history so week-over-week questions have data.

  bash "$SCRIPT_DIR/helpers/seed_demo_history.sh"            # dry run
  bash "$SCRIPT_DIR/helpers/seed_demo_history.sh" --commit --days 7
EOF
