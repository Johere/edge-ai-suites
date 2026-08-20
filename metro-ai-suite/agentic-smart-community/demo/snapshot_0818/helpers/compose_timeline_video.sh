#!/usr/bin/env bash
# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# Compose the on-disk validation videos for a timeline, each with its
# groundtruth SRT.
#
# Both videos are stream-copied from the normalized clips, so this takes minutes
# rather than hours and stays bit-identical to what the RTSP stream serves.
#
#   <id>__showcase.mp4  every clip once, separated by empty-room filler (~14min)
#   <id>__validate.mp4  4h with events spread evenly, day->night light arc
#
# The 24h RTSP groundtruth SRT is generated too — it has no video of its own,
# it describes the live stream.
#
# Usage:
#   bash scripts/helpers/compose_timeline_video.sh --timeline PATH [options]
#
# Options:
#   --timeline PATH   timeline EDL (required)
#   --out-dir DIR     output directory (default: <timeline_dir>/<id>_composed)
#   --modes "a b"     which layouts to compose (default: "showcase validate")
#   --force           overwrite existing mp4s instead of skipping
#   -h, --help
#
# Environment:
#   PYTHON=python3

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILDER="$SCRIPT_DIR/build_timeline.py"
PYTHON="${PYTHON:-python3}"

TIMELINE=""
OUT_DIR=""
MODES="showcase validate"
FORCE=0

usage() { sed -n '4,29p' "$0"; }

while (( $# )); do
  case "$1" in
    --timeline) TIMELINE="${2:-}"; shift 2 ;;
    --out-dir)  OUT_DIR="${2:-}";  shift 2 ;;
    --modes)    MODES="${2:-}";    shift 2 ;;
    --force)    FORCE=1;           shift ;;
    -h|--help)  usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

[[ -n "$TIMELINE" ]] || { echo "error: --timeline is required" >&2; usage; exit 1; }
[[ -f "$TIMELINE" ]] || { echo "error: timeline not found: $TIMELINE" >&2; exit 1; }
[[ -f "$BUILDER" ]]  || { echo "error: build_timeline.py not found: $BUILDER" >&2; exit 1; }
command -v ffmpeg  >/dev/null || { echo "ffmpeg not found in PATH" >&2; exit 1; }
command -v ffprobe >/dev/null || { echo "ffprobe not found in PATH" >&2; exit 1; }

# Resolve the timeline id and clip length straight from the EDL so the naming
# here can never disagree with what build_timeline.py writes.
read -r TIMELINE_ID CLIP_SECONDS < <(
  "$PYTHON" - "$TIMELINE" <<'PY'
import sys, yaml
with open(sys.argv[1], encoding="utf-8") as handle:
    cfg = yaml.safe_load(handle) or {}
print(cfg.get("id", ""), int(cfg.get("clip_seconds", 15)))
PY
)
[[ -n "$TIMELINE_ID" ]] || { echo "error: timeline has no 'id'" >&2; exit 1; }

if [[ -z "$OUT_DIR" ]]; then
  OUT_DIR="$(cd "$(dirname "$TIMELINE")" && pwd -P)/${TIMELINE_ID}_composed"
fi
mkdir -p "$OUT_DIR"

builder_args=(--timeline "$TIMELINE" --out-dir "$OUT_DIR")

compose_one() {
  local mode="$1"
  local stem="$OUT_DIR/${TIMELINE_ID}__${mode}"
  local playlist="$stem.ffconcat"
  local target="$stem.mp4"

  echo "── $mode ─────────────────────────────────────────────"
  "$PYTHON" "$BUILDER" "${builder_args[@]}" --mode "$mode" | sed 's/^/  /'

  [[ -f "$playlist" ]] || { echo "  error: builder produced no playlist" >&2; return 1; }

  local slots
  slots="$(grep -c "^file " "$playlist")"
  local expected=$(( slots * CLIP_SECONDS ))

  if (( ! FORCE )) && [[ -f "$target" && "$target" -nt "$playlist" ]]; then
    echo "  skip  $(basename "$target") is up to date (--force to rebuild)"
    return 0
  fi

  local tmp="$stem.part.$$.mp4"
  echo "  muxing $slots slots -> $(basename "$target") …"
  if ! ffmpeg -y -nostdin -hide_banner -loglevel error \
        -f concat -safe 0 -i "$playlist" -c copy -movflags +faststart \
        -f mp4 "$tmp"; then
    rm -f "$tmp"
    echo "  error: concat failed for $mode" >&2
    return 1
  fi
  mv -f "$tmp" "$target"

  # Duration is the honest check that every clip really was normalized: a clip
  # that slipped through at the wrong frame rate shows up as drift here.
  local actual
  actual="$(ffprobe -v error -show_entries format=duration \
            -of default=nw=1:nk=1 "$target")"
  printf '  done  %s  duration=%.2fs expected=%ds\n' \
    "$(basename "$target")" "$actual" "$expected"

  "$PYTHON" - "$actual" "$expected" <<'PY'
import sys
actual, expected = float(sys.argv[1]), int(sys.argv[2])
drift = abs(actual - expected)
tolerance = max(2.0, expected * 0.001)
if drift > tolerance:
    print(f"  error: duration drifted {drift:.2f}s (tolerance {tolerance:.2f}s) — "
          "some clip is not normalized", file=sys.stderr)
    sys.exit(1)
PY
}

echo "timeline : $TIMELINE"
echo "id       : $TIMELINE_ID"
echo "out dir  : $OUT_DIR"
echo

failed=0
for mode in $MODES; do
  compose_one "$mode" || failed=$((failed+1))
  echo
done

# The live-stream groundtruth has no video of its own; emit it alongside so the
# whole set of SRTs shares one id and one build.
echo "── rtsp24h groundtruth SRT ───────────────────────────"
"$PYTHON" "$BUILDER" "${builder_args[@]}" --mode rtsp24h | sed 's/^/  /'
echo

if (( failed )); then
  echo "summary: $failed mode(s) failed" >&2
  exit 1
fi

echo "summary: composed [$MODES] + rtsp24h SRT in $OUT_DIR"
ls -la "$OUT_DIR"
