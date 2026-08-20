#!/usr/bin/env bash
# Compose child-safety demo video from individual clips + background image.
#
# Output: child_safety_demo.mp4 (~9m15s, 1280x720, 30fps, h264/yuv420p)
# Usage: bash compose_demo.sh
#
# Requires ffmpeg in PATH.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$SCRIPT_DIR/.."           # videos/phase2/child-care/
TMP="$SCRIPT_DIR/tmp"
OUT="$SCRIPT_DIR/child_safety_demo.mp4"
LIST="$TMP/concat_list.txt"
BG="$SRC/child-care-bg.png"

# Normalize: 1280x720, 30fps, yuv420p, libx264 crf=18
V_OPTS=(-vf "fps=30,scale=1280:720,format=yuv420p" -c:v libx264 -crf 18 -preset fast -an)

mkdir -p "$TMP"
echo "Working in $TMP ..."

# ── 1. Generate background image clips (one per distinct duration) ──────────
make_bg() {
  local dur=$1
  local out="$TMP/bg_${dur}s.mp4"
  if [[ ! -f "$out" ]]; then
    echo "  BG ${dur}s ..."
    ffmpeg -y -loop 1 -t "$dur" -i "$BG" "${V_OPTS[@]}" "$out" -loglevel warning
  fi
}

make_bg 45
make_bg 40
make_bg 35

# ── 2. Normalize each event clip ─────────────────────────────────────────────
norm() {
  local name=$1
  local src="$SRC/${name}.mp4"
  local out="$TMP/${name}_norm.mp4"
  if [[ ! -f "$out" ]]; then
    echo "  Normalize $name ..."
    ffmpeg -y -i "$src" "${V_OPTS[@]}" "$out" -loglevel warning
  fi
}

norm child-care-003-reading
norm child-care-003-jump
norm child-care-003-eating-candidate
norm child-care-003-falldown
norm child-care-003-safe-playing
norm child-care-003-scissors
norm child-care-003-fire
norm child-care-003-climb-window
norm child-care-003-climb-window_2
norm child-care-003-climb-window_3

# ── 3. Write concat list ──────────────────────────────────────────────────────
# Sequence (matches groundtruth.srt timestamps):
#   BG45 | reading | BG40 | jump | BG35 | eating | BG35 | falldown |
#   BG40 | safe-playing | BG35 | scissors | BG40 | reading | BG35 | fire |
#   BG35 | eating | BG40 | climb×3 | BG45

cat > "$LIST" << 'EOF'
file 'bg_45s.mp4'
file 'child-care-003-reading_norm.mp4'
file 'bg_40s.mp4'
file 'child-care-003-jump_norm.mp4'
file 'bg_35s.mp4'
file 'child-care-003-eating-candidate_norm.mp4'
file 'bg_35s.mp4'
file 'child-care-003-falldown_norm.mp4'
file 'bg_40s.mp4'
file 'child-care-003-safe-playing_norm.mp4'
file 'bg_35s.mp4'
file 'child-care-003-scissors_norm.mp4'
file 'bg_40s.mp4'
file 'child-care-003-reading_norm.mp4'
file 'bg_35s.mp4'
file 'child-care-003-fire_norm.mp4'
file 'bg_35s.mp4'
file 'child-care-003-eating-candidate_norm.mp4'
file 'bg_40s.mp4'
file 'child-care-003-climb-window_norm.mp4'
file 'child-care-003-climb-window_2_norm.mp4'
file 'child-care-003-climb-window_3_norm.mp4'
file 'bg_45s.mp4'
EOF

# ── 4. Concat ─────────────────────────────────────────────────────────────────
echo "Concatenating → $OUT ..."
ffmpeg -y -f concat -safe 0 -i "$LIST" -c copy "$OUT" -loglevel warning

DURATION=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$OUT" 2>/dev/null)
echo "Done. Duration=${DURATION}s  →  $OUT"

# ── 5. Clean up tmp ───────────────────────────────────────────────────────────
rm -rf "$TMP"
echo "Tmp cleaned."
