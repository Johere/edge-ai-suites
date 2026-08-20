#!/usr/bin/env bash
# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# Turn the raw child-safety clips into the normalized clip library that
# child_safety_timeline.yaml references.
#
# Three things happen here that normalize_clips_for_concat.sh cannot do itself:
#
#   1. Renaming. The raw files are `child-care-003-<action>.mp4`, which
#      `clip_id_of` would turn into whole-basename IDs. They are staged as
#      `<ID>.mp4` instead, where ID is `<slot>_<event>` (A1_normal, C1_climb, …)
#      so the timeline reads legibly. The ID may contain exactly ONE underscore:
#      `clip_id_of`'s `^[A-Za-z0-9]+_([A-Za-z0-9]+)_` needs two to match, so
#      `A1_normal.mp4` falls through to the whole-basename branch (what we want)
#      while `A1_normal_reading.mp4` would collapse to the ID `normal` and make
#      all three A-clips collide.
#
#   2. Filler synthesis. The only "empty living room" asset is a still image, so
#      the day and night filler clips are generated from it. A still is the ideal
#      filler: zero motion, so the pipeline's motion gate drops it and it costs
#      no VLM work at all.
#
#   3. CLIP_SECONDS=10, not the elder library's 15. `-frames:v` only ever
#      truncates, so a 15s target against a 10.05s source would emit 300 frames
#      instead of 450 and normalize's own concat-compatibility assert would fail.
#      10 also divides 86400 evenly (8640 slots/day).
#
# Usage:
#   bash prepare_child_clips.sh [src_dir]
#
# `src_dir` defaults to this script's directory. Staging and normalized output
# always land next to this script regardless of where the sources came from,
# because the timeline's `clips_dir` is resolved relative to the timeline file.
#
# Environment:
#   FORCE=1   re-encode even when outputs look up to date

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="${1:-$SCRIPT_DIR}"
STAGING="$SCRIPT_DIR/staging"
OUT_DIR="$SCRIPT_DIR/normalized"
BG="$SRC_DIR/child-care-bg.png"
NORMALIZE="$SCRIPT_DIR/../normalize_clips_for_concat.sh"

CLIP_SECONDS=10
FPS=30
WIDTH=1280
HEIGHT=720

command -v ffmpeg >/dev/null || { echo "error: ffmpeg not found in PATH" >&2; exit 1; }
[[ -d "$SRC_DIR" ]] || { echo "error: not a directory: $SRC_DIR" >&2; exit 1; }
[[ -f "$NORMALIZE" ]] || { echo "error: normalize_clips_for_concat.sh not found: $NORMALIZE" >&2; exit 1; }
SRC_DIR="$(cd "$SRC_DIR" && pwd -P)"

# ID -> source basename. Exactly the ten clips compose_demo.sh uses; the 40s
# climb-window-all is the concatenation of C1..C3 and is deliberately unused.
CLIP_MAP=(
  "A1_normal:child-care-003-reading"
  "A2_normal:child-care-003-eating-candidate"
  "A3_normal:child-care-003-safe-playing"
  "J1_jump:child-care-003-jump"
  "F1_fall:child-care-003-falldown"
  "K1_knife:child-care-003-scissors"
  "R1_fire:child-care-003-fire"
  "C1_climb:child-care-003-climb-window"
  "C2_climb:child-care-003-climb-window_2"
  "C3_climb:child-care-003-climb-window_3"
)

echo "source   : $SRC_DIR"
echo "staging  : $STAGING"
echo "output   : $OUT_DIR"
echo

# ── 1. Stage the event clips under their timeline IDs ────────────────────────
# Symlinks rather than copies: normalize reads them once and compares mtimes
# against the real source, so a replaced source clip still triggers a re-encode.
#
# Only the symlinks are refreshed, never the whole directory: wiping it would give
# the synthesized filler clips a new mtime on every run, and normalize's
# "output newer than input" check would re-encode them every time.
mkdir -p "$STAGING"

missing=()
staged=()
for entry in "${CLIP_MAP[@]}"; do
  id="${entry%%:*}"
  src="$SRC_DIR/${entry#*:}.mp4"
  if [[ ! -f "$src" ]]; then
    missing+=("${entry#*:}.mp4")
    continue
  fi
  ln -sfn "$src" "$STAGING/$id.mp4"
  staged+=("$id")
done

if (( ${#missing[@]} )); then
  echo "error: missing source clip(s) in $SRC_DIR:" >&2
  printf '  %s\n' "${missing[@]}" >&2
  exit 1
fi
echo "staged ${#CLIP_MAP[@]} event clip(s)"

# ── 2. Synthesize the two filler clips from the background still ─────────────
[[ -f "$BG" ]] || { echo "error: background image not found: $BG" >&2; exit 1; }

make_filler() {
  local id="$1" filter="$2"
  local dst="$STAGING/$id.mp4"

  # Keep an up-to-date filler as-is so its mtime stays older than the normalized
  # output — otherwise every run re-encodes it downstream.
  if (( ! ${FORCE:-0} )) && [[ -f "$dst" && "$dst" -nt "$BG" ]]; then
    echo "  keep $id (up to date)"
    return 0
  fi

  # The still is 1916x1073 — an odd height that libx264 rejects outright, so
  # scale here rather than leaving it to normalize.
  local vf="scale=${WIDTH}:${HEIGHT},fps=${FPS},format=yuv420p"
  [[ -n "$filter" ]] && vf="${filter},${vf}"
  ffmpeg -y -nostdin -hide_banner -loglevel error \
    -loop 1 -t "$CLIP_SECONDS" -i "$BG" \
    -vf "$vf" -c:v libx264 -preset fast -crf 23 -an "$dst"
  echo "  synthesized $id"
}

echo "filler clips from ${BG##*/} …"
make_filler "E1_empty" ""
# Night: the same living room with the lights off. Darkening the still keeps the
# geometry identical, so day/night transitions do not read as a camera cut.
make_filler "E2_empty" "eq=brightness=-0.35:saturation=0.4"

# ── 3. Normalize everything to one concat-safe profile ──────────────────────
echo
if (( ${FORCE:-0} )) || [[ ! -d "$OUT_DIR" ]]; then
  echo "encoding ${#CLIP_MAP[@]} + 2 clips (~10s; reruns skip up-to-date outputs)"
fi
CLIP_SECONDS="$CLIP_SECONDS" FPS="$FPS" WIDTH="$WIDTH" HEIGHT="$HEIGHT" \
  FORCE="${FORCE:-0}" \
  bash "$NORMALIZE" "$STAGING" "$OUT_DIR"
