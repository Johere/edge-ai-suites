#!/usr/bin/env bash
# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# Seed seven days of history for both 0818 demo cameras in one shot.
#
# Without this the demo can only answer questions about today: "how many times
# this week", "compare with the same period last week" and the weekly reports all
# need days that no longer exist unless the stream ran for a week.
#
# Each camera gets its own row targets, because their timelines have different
# candidate pools. Both land at the same density as their live stream (~10
# observations per waking hour), so today never reads as an outlier next to the
# seeded week.
#
#   cam_child       117 -> 150 rows/day, danger 14 -> 30
#   cam_elder_care  143 -> 169 rows/day, alerts  2 ->  5
#
# Usage:
#   bash seed_demo_history.sh                 # dry run — prints the plan only
#   bash seed_demo_history.sh --commit        # write
#   bash seed_demo_history.sh --reset --commit
#   bash seed_demo_history.sh --commit --days 10 --jitter 30
#
# --reset is DESTRUCTIVE: it drops every events/tasks/alerts/reports row for both
# demo monitors, real ones included, before seeding. It is not the default because
# this script ships in the repo and nobody's data should vanish for running it.
# Use it to clear a polluted history — for instance the pre-timeline cam_child
# data, which recorded six danger alerts every hour around the clock and would
# skew any weekly comparison.
#
# Anything else is forwarded to seed_history.py untouched.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEED="$SCRIPT_DIR/seed_history.py"

DEFAULT_DAYS=7
CHILD_CALM="103,106,110,113,116,118,120"
CHILD_DANGER="14,17,20,23,26,28,30"
ELDER_CALM="141,144,149,153,157,161,164"
ELDER_DANGER="2,2,3,3,4,4,5"

[[ -f "$SEED" ]] || { echo "error: seed_history.py not found: $SEED" >&2; exit 1; }

# --purge (seeded rows only) is the default; --reset escalates to wiping
# everything for the monitor, so the two must not both be passed.
MODE=(--purge)
FORWARD=()
for arg in "$@"; do
  case "$arg" in
    --reset) MODE=(--reset-monitor) ;;
    *) FORWARD+=("$arg") ;;
  esac
done

run_one() {
  local monitor="$1" use_case="$2" timeline="$3" calm="$4" danger="$5"
  echo "══ $monitor ($use_case) ═══════════════════════════════════════════"
  python3 "$SEED" \
    --monitor "$monitor" \
    --use-case "$use_case" \
    --timeline "$SCRIPT_DIR/$timeline" \
    --days "$DEFAULT_DAYS" \
    --calm-targets "$calm" \
    --danger-targets "$danger" \
    "${MODE[@]}" \
    ${FORWARD[@]+"${FORWARD[@]}"}
  echo
}

if [[ "${MODE[0]}" == "--reset-monitor" ]]; then
  echo "!! --reset: ALL history for cam_child and cam_elder_care will be deleted"
  echo "   (each run below prints the per-table row counts it removes)"
  echo
fi

run_one cam_child      child_safety child_safety_timeline.yaml "$CHILD_CALM" "$CHILD_DANGER"
run_one cam_elder_care elder_care   elder_care_timeline.yaml   "$ELDER_CALM" "$ELDER_DANGER"
