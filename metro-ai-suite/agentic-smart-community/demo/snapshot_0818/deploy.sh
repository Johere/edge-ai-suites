#!/usr/bin/env bash
# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# Deploy an extracted 0818 snapshot. The package contains the demo-specific
# assets; its open-source runtime is cloned from the public edge-ai-suites repo.
#
# Environment overrides:
#   EDGE_AI_SUITES_DIR  checkout location (default: ~/edge-ai-suites)
#   COMPONENT_ROOT      Agentic Smart Community source directory
#   SKIP_START=1        clone/validate only; do not start the demo
set -euo pipefail

SNAPSHOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EDGE_AI_SUITES_DIR="${EDGE_AI_SUITES_DIR:-$HOME/edge-ai-suites}"
COMPONENT_ROOT="${COMPONENT_ROOT:-$EDGE_AI_SUITES_DIR/metro-ai-suite/agentic-smart-community}"
REPOSITORY_URL="https://github.com/open-edge-platform/edge-ai-suites"

command -v git >/dev/null 2>&1 || { echo "ERROR: 'git' not found on PATH." >&2; exit 1; }

if [[ ! -d "$EDGE_AI_SUITES_DIR/.git" ]]; then
  if [[ -e "$EDGE_AI_SUITES_DIR" ]]; then
    echo "ERROR: checkout path exists but is not a git clone: $EDGE_AI_SUITES_DIR" >&2
    exit 1
  fi
  echo "==> Cloning Edge AI Suites into $EDGE_AI_SUITES_DIR"
  git clone "$REPOSITORY_URL" "$EDGE_AI_SUITES_DIR"
fi

[[ -f "$COMPONENT_ROOT/setup_docker.sh" ]] || {
  echo "ERROR: Agentic Smart Community source not found: $COMPONENT_ROOT" >&2
  echo "       Set COMPONENT_ROOT if this checkout uses a different location." >&2
  exit 1
}

echo "==> Using source checkout: $COMPONENT_ROOT"
if [[ "${SKIP_START:-0}" == "1" ]]; then
  echo "==> SKIP_START=1; clone and source validation complete"
  exit 0
fi

exec env COMPONENT_ROOT="$COMPONENT_ROOT" bash "$SNAPSHOT_DIR/start-demo.sh"