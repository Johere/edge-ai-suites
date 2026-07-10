#!/usr/bin/env bash
#
# Zero-cost install for the smartbuilding-alerts OpenClaw framework adapter.
#
#   1. build the framework-adapter-sdk (this plugin imports its built dist)
#   2. install the plugin's own deps (links the SDK into node_modules)
#   3. symlink the plugin into ~/.openclaw/extensions/
#   4. copy the bundled agent personas into ~/.openclaw/agents/  (cp -n: never clobbers)
#   5. print the openclaw.json snippet to paste + the restart reminder
#
# Idempotent: safe to re-run. Step 4 preserves any persona edits you've made.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SDK_DIR="$(cd "$HERE/../.." && pwd)"                 # packages/framework-adapter-sdk
REPO_ROOT="$(cd "$SDK_DIR/../.." && pwd)"            # repo root
OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
PLUGIN_ID="smartbuilding-alerts"

echo "==> Building framework-adapter-sdk"
npm --prefix "$REPO_ROOT" -w @smartbuilding-video/framework-adapter-sdk run build

echo "==> Installing plugin dependencies"
npm --prefix "$HERE" install

echo "==> Symlinking plugin into $OPENCLAW_HOME/extensions/$PLUGIN_ID"
mkdir -p "$OPENCLAW_HOME/extensions"
ln -sfn "$HERE" "$OPENCLAW_HOME/extensions/$PLUGIN_ID"

echo "==> Seeding agent personas into $OPENCLAW_HOME/agents (cp -n, non-destructive)"
for agent_dir in "$HERE"/agents/*/; do
  agent_id="$(basename "$agent_dir")"
  dst="$OPENCLAW_HOME/agents/$agent_id/workspace"
  mkdir -p "$dst"
  cp -n "$agent_dir/workspace/"*.md "$dst/" 2>/dev/null || true
  echo "    - $agent_id"
done
# TODO: add agents in openclaw.json

cat <<EOF

==> Done. Two manual steps remain:

1) Add this under "extensions" (or the plugin section) in $OPENCLAW_HOME/openclaw.json:

  "plugins": {
    "entries": {
      ..,
      "$PLUGIN_ID": {
        "enabled": true,
        "config": {
          "mcpServer": { "url": "http://localhost:3100/mcp" },
          "monitors": {
            "cam_child": {
              "alerts": [
                { "agentId": "child-safety-agent", "sessionKey": "agent:child-safety-agent:cam_child", "deliver": false }
              ]
            },
            "cam_elder_bedroom": {
              "alerts": [
                { "agentId": "elder-wakeup-agent", "sessionKey": "agent:elder-wakeup-agent:cam_elder_bedroom", "deliver": false }
              ]
            }
          }
        }
      }
    }
  },

2) Restart the OpenClaw gateway.

The adapter will subscribe to the configured monitors on the SmartBuilding MCP server
(default http://localhost:3100/mcp) and inject each new alert into the routed session(s).

3) Wakup agents
openclaw agent -m "hi" --agent "child-safety-agent"
EOF
