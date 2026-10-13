#!/bin/bash

# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# Tests for videostream-analytics/setup_vsa.sh: seed idempotency (the core
# contract), dual-mode sourcing, symlink lifecycle, and the rename guard.
# A stub IR pair stands in for the real model so no download/conversion runs.
#
# Run: bash videostream-analytics/tests/test_setup_vsa.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VSA_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SETUP="${VSA_DIR}/setup_vsa.sh"
LINK="${VSA_DIR}/config/config.yaml"

WORK="$(mktemp -d)"
MODEL_DIR_T="${WORK}/models"
CACHE_T="${WORK}/cache"
mkdir -p "${MODEL_DIR_T}/yolo11s/FP16"
printf 'x' > "${MODEL_DIR_T}/yolo11s/FP16/yolo11s.xml"
printf 'x' > "${MODEL_DIR_T}/yolo11s/FP16/yolo11s.bin"

export MODEL_DIR="$MODEL_DIR_T"
export PREFILTER_MODEL="${MODEL_DIR_T}/yolo11s/FP16/yolo11s.xml"
export VIDEOSTREAM_CACHE_HOST="$CACHE_T"

fail() { echo "[FAIL] $*" >&2; exit 1; }
ok()   { echo "[ ok ] $*"; }

# Preserve any pre-existing symlink the user's real setup created; restore on exit.
had_link=0 prev_target=""
if [[ -L "$LINK" ]]; then had_link=1; prev_target="$(readlink "$LINK")"; fi
[[ -f "$LINK" && ! -L "$LINK" ]] && fail "${LINK} is a pre-existing regular file; refusing to test against it"

cleanup() {
  rm -rf "$WORK"
  if [[ -L "$LINK" && "$(readlink "$LINK")" == "${CACHE_T}/config.yaml" ]]; then
    if [[ "$had_link" == 1 ]]; then ln -sfn "$prev_target" "$LINK"; else rm -f "$LINK"; fi
  fi
}
trap cleanup EXIT

# --- 1) sourcing defines functions, no side effects ---------------------------
(
  source "$SETUP"
  declare -F vsa_prepare >/dev/null || exit 1
  declare -F vsa_seed_config >/dev/null || exit 1
  declare -F vsa_prepare_model >/dev/null || exit 1
  [[ ! -e "${CACHE_T}/config.yaml" ]] || exit 1
  [[ ! -e "$LINK" && ! -L "$LINK" ]] || exit 1
) || fail "sourcing produced side effects or is missing functions"
ok "source: functions defined, no files, no symlink"

# --- 2) first run seeds config + creates the symlink --------------------------
bash "$SETUP" >/dev/null || fail "setup_vsa.sh exited non-zero"
[[ -f "${CACHE_T}/config.yaml" ]] || fail "config was not seeded"
[[ -L "$LINK" ]] || fail "symlink not created at ${LINK}"
[[ "$(readlink "$LINK")" == "${CACHE_T}/config.yaml" ]] || fail "symlink target wrong: $(readlink "$LINK")"
grep -q "${MODEL_DIR_T}/yolo11s/FP16/yolo11s.xml" "${CACHE_T}/config.yaml" \
  || fail "seeded config lacks the absolute model path"
ok "first run: seeded config, absolute paths, symlink created"

# --- 3) unknown subcommand rejected -------------------------------------------
bash "$SETUP" bogus >/dev/null 2>&1
[[ $? -eq 2 ]] || fail "unknown subcommand should exit 2"
ok "unknown subcommand exits 2"

# --- 4) core contract: re-running preserves a customized config ---------------
echo "# user-customization-marker" >> "${CACHE_T}/config.yaml"
before_md5="$(md5sum "${CACHE_T}/config.yaml" | awk '{print $1}')"
before_mtime="$(stat -c %Y "${CACHE_T}/config.yaml")"
sleep 1.1
out="$(bash "$SETUP" 2>&1)" || fail "second run exited non-zero"
grep -q "Keeping your existing configuration" <<<"$out" || fail "second run did not say it keeps the config"
after_md5="$(md5sum "${CACHE_T}/config.yaml" | awk '{print $1}')"
after_mtime="$(stat -c %Y "${CACHE_T}/config.yaml")"
[[ "$before_md5" == "$after_md5" ]] || fail "config content changed on re-run"
[[ "$before_mtime" == "$after_mtime" ]] || fail "config mtime changed on re-run"
grep -q "user-customization-marker" "${CACHE_T}/config.yaml" || fail "custom marker lost on re-run"
[[ -L "$LINK" ]] || fail "symlink lost on re-run"
ok "re-run: config preserved (md5 + mtime unchanged), symlink intact"

# --- 5) a regular file at the link path is not clobbered ----------------------
rm -f "$LINK"
printf 'do not touch\n' > "$LINK"
out="$(bash "$SETUP" 2>&1)"
grep -qi "leaving it alone" <<<"$out" || fail "no warning for a regular file at the link path"
[[ "$(cat "$LINK")" == "do not touch" ]] || fail "regular file at link path was clobbered"
rm -f "$LINK"
ok "regular file at link path preserved with warning"

# --- 6) rename guard: no stale references to the old tracked path -------------
stale="$(grep -rn "config/config\.yaml" \
  --include="*.py" --include="*.sh" --include="*.yaml" --include="Dockerfile" \
  "$VSA_DIR" "${VSA_DIR}/../setup_docker.sh" "${VSA_DIR}/../docker" 2>/dev/null \
  | grep -v "config.yaml.example" \
  | grep -v "/app/config/config.yaml" \
  | grep -v "setup_vsa.sh" \
  | grep -v "test_setup_vsa.sh" || true)"
[[ -z "$stale" ]] || fail "stale references to config/config.yaml:\n${stale}"
ok "rename guard: no stale config/config.yaml references"

echo
ok "all setup_vsa.sh tests passed"
