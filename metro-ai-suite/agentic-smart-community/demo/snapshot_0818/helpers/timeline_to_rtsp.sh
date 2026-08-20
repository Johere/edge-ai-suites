#!/usr/bin/env bash
# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# Publish a timeline EDL as a wall-clock-aligned RTSP stream.
#
# The stream is served straight from the normalized 15s clips via the ffmpeg
# concat demuxer, so a 24h day costs ~200MB on disk instead of ~50GB. The
# playlist is regenerated before every ffmpeg run and rotated to whatever should
# be on screen at that moment, so daylight and darkness line up with the real
# clock and `-re` drift never accumulates.
#
# Usage:
#   bash scripts/helpers/timeline_to_rtsp.sh --timeline PATH [options]
#
# Options:
#   --timeline PATH   timeline EDL (required)
#   --url URL         RTSP destination (default: rtsp://localhost:8557/live/eldercare)
#   --at HH:MM|now    where in the day to start (default: now)
#   --until HH:MM     relaunch point; keep it inside quiet footage (default: 04:00)
#   --speed N         debug fast-forward via ffmpeg -readrate N (default: 1)
#   --once            play one playlist and exit instead of looping forever
#   -h, --help
#
# Environment:
#   MEDIAMTX_BIN=/path/to/mediamtx   # default: ~/.local/bin/mediamtx
#   PYTHON=python3
#
# An RTSP server already listening on the target port is reused as-is; otherwise
# a private MediaMTX is started and torn down with this script. That is what lets
# this coexist with the ready-to-run demo streams on :8554.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILDER="$SCRIPT_DIR/build_timeline.py"
PYTHON="${PYTHON:-python3}"
MEDIAMTX_BIN="${MEDIAMTX_BIN:-$HOME/.local/bin/mediamtx}"

TIMELINE=""
RTSP_URL="rtsp://localhost:8557/live/eldercare"
START_AT="now"
UNTIL="04:00"
SPEED="1"
ONCE=0

RUN_DIR=""
MEDIAMTX_PID=""
FFMPEG_PID=""
SHUTTING_DOWN=0

usage() { sed -n '4,31p' "$0"; }

while (( $# )); do
  case "$1" in
    --timeline) TIMELINE="${2:-}"; shift 2 ;;
    --url)      RTSP_URL="${2:-}"; shift 2 ;;
    --at)       START_AT="${2:-}"; shift 2 ;;
    --until)    UNTIL="${2:-}";    shift 2 ;;
    --speed)    SPEED="${2:-}";    shift 2 ;;
    --once)     ONCE=1;            shift ;;
    -h|--help)  usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

# Forward termination to the ffmpeg child; without this, killing the wrapper
# leaves an orphan holding the RTSP path open.
cleanup() {
  SHUTTING_DOWN=1
  local pid
  for pid in "$FFMPEG_PID" "$MEDIAMTX_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
  [[ -n "$RUN_DIR" && -d "$RUN_DIR" ]] && rm -rf "$RUN_DIR"
  return 0
}
trap cleanup EXIT
trap 'SHUTTING_DOWN=1; exit 143' INT TERM

[[ -n "$TIMELINE" ]] || { echo "error: --timeline is required" >&2; usage; exit 1; }
[[ -f "$TIMELINE" ]] || { echo "error: timeline not found: $TIMELINE" >&2; exit 1; }
[[ -f "$BUILDER" ]]  || { echo "error: build_timeline.py not found: $BUILDER" >&2; exit 1; }
command -v ffmpeg >/dev/null || { echo "error: ffmpeg not found in PATH" >&2; exit 1; }

if [[ ! "$RTSP_URL" =~ ^rtsp://(\[[0-9A-Fa-f:]+\]|[A-Za-z0-9.-]+):([0-9]{1,5})/([-A-Za-z0-9._~%]+(/[-A-Za-z0-9._~%]+)*)$ ]]; then
  echo "ERROR: Invalid RTSP URL: $RTSP_URL" >&2
  echo "Expected format: rtsp://host:port/path" >&2
  exit 1
fi
RTSP_PORT="$((10#${BASH_REMATCH[2]}))"
RTSP_PATH="${BASH_REMATCH[3]}"
if (( RTSP_PORT < 1 || RTSP_PORT > 65535 )); then
  echo "ERROR: RTSP port must be between 1 and 65535: $RTSP_PORT" >&2
  exit 1
fi

port_is_listening() {
  command -v ss >/dev/null 2>&1 || return 1
  ss -H -ltn "sport = :$RTSP_PORT" 2>/dev/null | grep -q .
}

RUN_DIR="$(mktemp -d)"

start_mediamtx() {
  if port_is_listening; then
    echo "reusing the RTSP server already listening on :$RTSP_PORT"
    return 0
  fi

  [[ -x "$MEDIAMTX_BIN" ]] || {
    echo "ERROR: nothing is listening on :$RTSP_PORT and MediaMTX is not executable: $MEDIAMTX_BIN" >&2
    exit 1
  }

  local config="$RUN_DIR/mediamtx.yml"
  local log="$RUN_DIR/mediamtx.log"
  printf '%s\n' \
    'logLevel: warn' \
    'rtsp: true' \
    'rtspTransports: [tcp]' \
    "rtspAddress: :${RTSP_PORT}" \
    'rtmp: false' \
    'hls: false' \
    'webrtc: false' \
    'srt: false' \
    'api: false' \
    'paths:' \
    "  ${RTSP_PATH}:" \
    '    source: publisher' >"$config"

  "$MEDIAMTX_BIN" "$config" >"$log" 2>&1 &
  MEDIAMTX_PID=$!

  for _ in {1..25}; do
    port_is_listening && break
    if ! kill -0 "$MEDIAMTX_PID" 2>/dev/null; then
      echo "ERROR: MediaMTX failed to start:" >&2
      tail -n 20 "$log" >&2
      exit 1
    fi
    sleep 0.2
  done
  echo "started MediaMTX on :$RTSP_PORT (pid $MEDIAMTX_PID)"
}

start_mediamtx

PLAYLIST="$RUN_DIR/playlist.ffconcat"

# One pass: rebuild the playlist anchored at the current wall clock, then stream
# it. Returns ffmpeg's exit status.
push_once() {
  local build_at="$1"

  # Artifacts go to a scratch dir so a long-running pusher never rewrites the
  # committed SRTs under the timeline directory.
  if ! "$PYTHON" "$BUILDER" \
        --timeline "$TIMELINE" \
        --mode rtsp24h \
        --at "$build_at" \
        --until "$UNTIL" \
        --out-dir "$RUN_DIR" \
        --print-playlist-path >"$RUN_DIR/playlist_path.txt"; then
    echo "ERROR: failed to build the playlist" >&2
    return 1
  fi
  PLAYLIST="$(cat "$RUN_DIR/playlist_path.txt")"

  # The header line carries the id and slot hash — log it so the running stream
  # can be matched against the groundtruth SRT on hand.
  local header
  header="$(sed -n '2s/^# //p' "$PLAYLIST")"
  local slots
  slots="$(grep -c '^file ' "$PLAYLIST")"
  echo "streaming $slots slots -> $RTSP_URL"
  echo "  $header"

  local rate_args=(-re)
  if [[ "$SPEED" != "1" ]]; then
    rate_args=(-readrate "$SPEED")
    echo "  (fast-forward: -readrate $SPEED — for EDL inspection, not for data generation)"
  fi

  ffmpeg -nostdin -hide_banner -loglevel warning \
    "${rate_args[@]}" \
    -f concat -safe 0 -fflags +genpts -i "$PLAYLIST" \
    -c copy -f rtsp -rtsp_transport tcp "$RTSP_URL" &
  FFMPEG_PID=$!
  wait "$FFMPEG_PID" && local status=0 || local status=$?
  FFMPEG_PID=""
  return "$status"
}

echo "timeline : $TIMELINE"
echo "url      : $RTSP_URL"
echo "start    : $START_AT   until: $UNTIL   speed: ${SPEED}x"
echo

attempt_at="$START_AT"
while :; do
  status=0
  push_once "$attempt_at" || status=$?

  (( SHUTTING_DOWN )) && break
  if (( ONCE )); then
    exit "$status"
  fi

  if (( status == 0 )); then
    echo "playlist finished — re-anchoring to the current wall clock"
  else
    echo "ffmpeg exited with status $status — restarting in 3s" >&2
    sleep 3
  fi
  # Every relaunch re-derives the offset from the real clock, so drift from the
  # previous run is discarded rather than accumulated.
  attempt_at="now"
done
