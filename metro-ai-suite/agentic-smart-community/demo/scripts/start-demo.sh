#!/usr/bin/env bash
# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# One-shot demo launcher: push the bundled clips as RTSP streams, then start the
# MCP server with the demo bundle (demo/config.demo.yaml + demo/monitors.demo.yaml)
# so the three validated example monitors (fridge / child / elder) come up.
#
#   demo/scripts/start-demo.sh          # start streams + demo MCP server
#   demo/scripts/stop-demo.sh           # stop both
#
# For a clean, use-case-free server instead, use scripts/mcp-server/start.sh.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# 1. Push the demo RTSP streams (backgrounded + idempotent inside the script).
echo "starting demo RTSP streams…"
bash "$REPO_DIR/demo/videos/start-streams.sh"

# 2. Start the MCP server pointed at the demo bundle.
export MCP_CONFIG="$REPO_DIR/demo/config.demo.yaml"
export MCP_MONITORS="$REPO_DIR/demo/monitors.demo.yaml"
exec "$REPO_DIR/scripts/mcp-server/start.sh" "$@"
