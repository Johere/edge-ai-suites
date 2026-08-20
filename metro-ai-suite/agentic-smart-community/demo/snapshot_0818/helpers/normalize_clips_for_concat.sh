#!/usr/bin/env bash
# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# Normalize demo clips so they can be concatenated with `-c copy`.
#
# The ffmpeg concat demuxer requires every input to share the same codec, size,
# frame rate, pixel format and time base. A mismatch is *silent corruption* —
# the join either garbles or the downstream decoder rejects the stream — so this
# script re-encodes every clip to one canonical profile and then asserts that
# the outputs really are identical before exiting.
#
# Usage:
#   bash scripts/helpers/normalize_clips_for_concat.sh <src_dir> [out_dir]
#   bash scripts/helpers/normalize_clips_for_concat.sh --help
#
# Input file names may be either `<ID>.mp4` or `<prefix>_<ID>_<words>.mp4`
# (e.g. `elder_D5_restless_sitstand.mp4` -> ID `D5`). Output is `<ID>.mp4`.
#
# Environment:
#   CLIP_SECONDS=15     # exact output duration; every clip is trimmed to it
#   FPS=30              # output frame rate
#   WIDTH=1920
#   HEIGHT=1080
#   CRF=23              # x264 quality, matches transcode-to-h264.sh default
#   PRESET=medium
#   FORCE=0             # 1 = re-encode even if the output looks up to date
#
# This script only normalizes: one input clip in, one normalized clip out. Filler
# footage such as an empty night-time room must be a real clip — synthesizing it by
# looping the tail of another clip does not work, because whatever motion is in
# that tail repeats instead of holding still.

set -euo pipefail

CLIP_SECONDS="${CLIP_SECONDS:-15}"
FPS="${FPS:-30}"
WIDTH="${WIDTH:-1920}"
HEIGHT="${HEIGHT:-1080}"
CRF="${CRF:-23}"
PRESET="${PRESET:-medium}"
FORCE="${FORCE:-0}"

usage() { sed -n '4,28p' "$0"; }

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
esac

command -v ffmpeg  >/dev/null || { echo "ffmpeg not found in PATH" >&2; exit 1; }
command -v ffprobe >/dev/null || { echo "ffprobe not found in PATH" >&2; exit 1; }

SRC_DIR="${1:-}"
[[ -n "$SRC_DIR" ]] || { echo "error: no source directory given" >&2; usage; exit 1; }
[[ -d "$SRC_DIR" ]] || { echo "error: not a directory: $SRC_DIR" >&2; exit 1; }
SRC_DIR="$(cd "$SRC_DIR" && pwd -P)"
OUT_DIR="${2:-$SRC_DIR/normalized}"
mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd -P)"

# Canonical encode profile. Closed GOP with a keyframe every FPS frames and
# scenecut disabled, so frame 0 of every clip is an IDR and the clips stay
# safe to reorder arbitrarily in a playlist.
EXACT_FRAMES=$(( CLIP_SECONDS * FPS ))
V_OPTS=(
  -vf "scale=${WIDTH}:${HEIGHT}:force_original_aspect_ratio=decrease,pad=${WIDTH}:${HEIGHT}:(ow-iw)/2:(oh-ih)/2,fps=${FPS},format=yuv420p"
  -frames:v "$EXACT_FRAMES"
  -c:v libx264 -preset "$PRESET" -crf "$CRF"
  -g "$FPS" -keyint_min "$FPS"
  -x264-params "scenecut=0:open-gop=0"
  -an
  -video_track_timescale 90000
  -movflags +faststart
)

# Derive the clip ID from a file name: `<ID>.mp4` or `<prefix>_<ID>_<rest>.mp4`.
clip_id_of() {
  local base="${1##*/}"
  base="${base%.*}"
  if [[ "$base" =~ ^[A-Za-z0-9]+_([A-Za-z0-9]+)_ ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
  else
    printf '%s\n' "$base"
  fi
}

normalize_one() {
  local src="$1" id="$2"
  local dst="$OUT_DIR/$id.mp4"

  if (( ! FORCE )) && [[ -f "$dst" && "$dst" -nt "$src" ]]; then
    echo "  skip  $id (up to date)"
    return 0
  fi

  local tmp="$dst.part.$$.mp4"
  local err
  if err="$(ffmpeg -y -nostdin -hide_banner -loglevel error -i "$src" \
        "${V_OPTS[@]}" -f mp4 "$tmp" 2>&1)"; then
    mv -f "$tmp" "$dst"
    echo "  ok    $id  <- ${src##*/}"
  else
    rm -f "$tmp"
    echo "  FAIL  $id  <- ${src##*/} — ${err##*$'\n'}" >&2
    return 1
  fi
}

# ── 1. Normalize every source clip ───────────────────────────────────────────
echo "normalizing $SRC_DIR -> $OUT_DIR"
echo "  profile: ${WIDTH}x${HEIGHT} ${FPS}fps yuv420p h264 crf${CRF} ${CLIP_SECONDS}s (${EXACT_FRAMES} frames) no-audio"

shopt -s nullglob
declare -a SRC_FILES=("$SRC_DIR"/*.mp4 "$SRC_DIR"/*.MP4)
(( ${#SRC_FILES[@]} > 0 )) || { echo "error: no .mp4 files in $SRC_DIR" >&2; exit 1; }

failed=0
declare -A SEEN_IDS=()
for src in "${SRC_FILES[@]}"; do
  id="$(clip_id_of "$src")"
  if [[ -n "${SEEN_IDS[$id]:-}" ]]; then
    echo "error: duplicate clip ID '$id' from ${src##*/} and ${SEEN_IDS[$id]}" >&2
    exit 1
  fi
  SEEN_IDS["$id"]="${src##*/}"
  normalize_one "$src" "$id" || failed=$((failed+1))
done

(( failed == 0 )) || { echo "error: $failed clip(s) failed to normalize" >&2; exit 1; }

# ── 2. Assert the outputs really are concat-compatible ───────────────────────
# This is the whole point of the script: catch a mismatch here rather than as a
# garbled join hours later.
echo
echo "verifying stream parameters are identical across all outputs…"

probe_signature() {
  ffprobe -v error -select_streams v:0 \
    -show_entries stream=width,height,r_frame_rate,codec_name,pix_fmt,time_base,nb_frames \
    -of default=nw=1:nk=1 "$1" | tr '\n' '|'
}

declare -a OUT_FILES=("$OUT_DIR"/*.mp4)
(( ${#OUT_FILES[@]} > 0 )) || { echo "error: no outputs produced" >&2; exit 1; }

reference=""
reference_file=""
mismatch=0
for out in "${OUT_FILES[@]}"; do
  sig="$(probe_signature "$out")"
  streams="$(ffprobe -v error -show_entries format=nb_streams -of default=nw=1:nk=1 "$out")"
  if [[ "$streams" != "1" ]]; then
    echo "  MISMATCH ${out##*/}: expected 1 stream (video only), got $streams" >&2
    mismatch=$((mismatch+1))
    continue
  fi
  if [[ -z "$reference" ]]; then
    reference="$sig"
    reference_file="${out##*/}"
    echo "  reference ${out##*/}: $sig"
    continue
  fi
  if [[ "$sig" != "$reference" ]]; then
    echo "  MISMATCH ${out##*/}: $sig" >&2
    echo "            vs $reference_file: $reference" >&2
    mismatch=$((mismatch+1))
  fi
done

if (( mismatch > 0 )); then
  echo >&2
  echo "error: $mismatch output(s) do not match the reference profile — concat with -c copy would corrupt" >&2
  exit 1
fi

echo "  all ${#OUT_FILES[@]} outputs match"
echo
echo "summary: ${#OUT_FILES[@]} clip(s) normalized -> $OUT_DIR"
