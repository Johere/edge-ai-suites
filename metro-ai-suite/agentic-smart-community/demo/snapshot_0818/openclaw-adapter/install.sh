# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#!/usr/bin/env bash
#
# Install the snapshot's OpenClaw alert integration without overwriting existing
# plugin routes, agents, skills, or persona files.
#
# Environment overrides:
#   OPENCLAW_HOME   OpenClaw state directory (default: ~/.openclaw)
#   MCP_URL         Smart Community MCP endpoint (default: http://localhost:3100/mcp)
#   AGENT_MODEL     model for newly registered agents (default: OpenClaw default)
#   SKIP_RESTART=1  do not restart the OpenClaw gateway
#   SKIP_WAKEUP=1   do not create the agents' initial sessions
set -euo pipefail

SCRIPT_PATH="$(realpath "${BASH_SOURCE[0]}")"
HERE="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
DEFAULT_COMPONENT_ROOT="$(cd "$HERE/../../.." && pwd)"
if [[ ! -f "$DEFAULT_COMPONENT_ROOT/setup_docker.sh" ]]; then
	DEFAULT_COMPONENT_ROOT="$HOME/edge-ai-suites/metro-ai-suite/agentic-smart-community"
fi
COMPONENT_ROOT="${COMPONENT_ROOT:-$DEFAULT_COMPONENT_ROOT}"
SDK_DIR="$COMPONENT_ROOT/packages/framework-adapter-sdk"
PLUGIN_DIR="$SDK_DIR/examples/openclaw"
PLUGIN_INSTALL_SH="$PLUGIN_DIR/scripts/install_as_openclaw_plugin.sh"
PERSONA_DIR="$HERE/agents"
SOURCE_SKILLS_DIR="$COMPONENT_ROOT/skills"
OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
# The CLI treats OPENCLAW_HOME as a home-directory override, rather than its
# state directory. Pass the selected directory to the delegated installer.
export -n OPENCLAW_HOME
PLUGIN_ID="smart-community-alerts"
MCP_URL_EXPLICIT=false
[[ -n "${MCP_URL+x}" ]] && MCP_URL_EXPLICIT=true
MCP_URL="${MCP_URL:-http://localhost:3100/mcp}"
AGENT_MODEL="${AGENT_MODEL:-}"
PERSONA_AGENTS=(child-safety-agent elder-care-agent)

command -v openclaw >/dev/null 2>&1 || { echo "ERROR: 'openclaw' CLI not found on PATH." >&2; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "ERROR: 'npm' not found on PATH." >&2; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "ERROR: 'jq' not found on PATH." >&2; exit 1; }
[[ -f "$COMPONENT_ROOT/setup_docker.sh" ]] || { echo "ERROR: Agentic Smart Community source not found: $COMPONENT_ROOT" >&2; exit 1; }
[[ -f "$PLUGIN_INSTALL_SH" ]] || { echo "ERROR: plugin installer not found: $PLUGIN_INSTALL_SH" >&2; exit 1; }
[[ -d "$PERSONA_DIR" ]] || { echo "ERROR: snapshot personas not found: $PERSONA_DIR" >&2; exit 1; }

if [[ ! -x "$SDK_DIR/node_modules/.bin/tsc" && ! -x "$COMPONENT_ROOT/node_modules/.bin/tsc" ]]; then
	echo "==> Installing SDK build dependencies"
	npm --prefix "$COMPONENT_ROOT" ci --include=dev
fi

if [[ -z "$AGENT_MODEL" ]]; then
	configured_model="$(openclaw config get agents.defaults.model.primary --json 2>/dev/null || true)"
	AGENT_MODEL="$(jq -r 'if type == "string" then . else empty end' <<<"$configured_model")"
fi
[[ -n "$AGENT_MODEL" ]] || {
	echo "ERROR: No default OpenClaw model is configured. Configure one first or set AGENT_MODEL." >&2
	exit 1
}

echo "==> Preparing the OpenClaw plugin"
bash "$PLUGIN_INSTALL_SH" prepare --openclaw-home "$OPENCLAW_HOME" --plugin-id "$PLUGIN_ID"

echo "==> Registering the plugin entry"
if openclaw config get "plugins.entries.$PLUGIN_ID" --json >/dev/null 2>&1; then
	if [[ "$MCP_URL_EXPLICIT" == "true" ]] || ! openclaw config get "plugins.entries.$PLUGIN_ID.config.mcpServer.url" --json >/dev/null 2>&1; then
		patch_file="$(mktemp)"
		trap 'rm -f "${patch_file:-}"' EXIT
		jq -n --arg id "$PLUGIN_ID" --arg url "$MCP_URL" \
			'{plugins: {entries: {($id): {config: {mcpServer: {url: $url}}}}}}' > "$patch_file"
		openclaw config patch --file "$patch_file"
		rm -f "$patch_file"
		unset patch_file
		echo "    - updated mcpServer.url=$MCP_URL"
	else
		echo "    - existing entry retained (set MCP_URL to change its endpoint)"
	fi
else
	patch_file="$(mktemp)"
	trap 'rm -f "${patch_file:-}"' EXIT
	jq -n --arg id "$PLUGIN_ID" --arg url "$MCP_URL" \
		'{plugins: {entries: {($id): {enabled: true, config: {mcpServer: {url: $url}, monitors: {}}}}}}' > "$patch_file"
	openclaw config patch --file "$patch_file"
	rm -f "$patch_file"
	unset patch_file
	echo "    - registered $PLUGIN_ID"
fi

routes="$(jq -n '{
	cam_child: {
		alerts: [{agentId: "child-safety-agent", sessionKey: "agent:child-safety-agent:cam_child", deliver: false}]
	},
	cam_elder_care: {
		alerts: [{agentId: "elder-care-agent", sessionKey: "agent:elder-care-agent:cam_elder_care", deliver: false}]
	}
}')"

echo "==> Adding snapshot alert routes"
while read -r monitor_id; do
	if openclaw config get "plugins.entries.$PLUGIN_ID.config.monitors.$monitor_id" --json >/dev/null 2>&1; then
		echo "    - $monitor_id already configured; retained"
		continue
	fi
	patch_file="$(mktemp)"
	trap 'rm -f "${patch_file:-}"' EXIT
	jq -n --arg id "$PLUGIN_ID" --arg monitor "$monitor_id" \
		--argjson route "$(jq -c --arg monitor "$monitor_id" '.[$monitor]' <<<"$routes")" \
		'{plugins: {entries: {($id): {config: {monitors: {($monitor): $route}}}}}}' > "$patch_file"
	openclaw config patch --file "$patch_file"
	rm -f "$patch_file"
	unset patch_file
	echo "    - $monitor_id routed"
done < <(jq -r 'keys[]' <<<"$routes")

echo "==> Merging snapshot agents into agents.list"
existing_agents="$(openclaw config get agents.list --json 2>/dev/null || true)"
echo "$existing_agents" | jq -e 'type == "array"' >/dev/null 2>&1 || existing_agents='[]'
desired_agents="$(jq -n --arg model "$AGENT_MODEL" --arg home "$OPENCLAW_HOME" '[
	{id: "child-safety-agent", name: "child-safety-agent", workspace: ($home + "/agents/child-safety-agent/workspace"), agentDir: ($home + "/agents/child-safety-agent/agent"), model: $model, thinkingDefault: "off"},
	{id: "elder-care-agent", name: "elder-care-agent", workspace: ($home + "/agents/elder-care-agent/workspace"), agentDir: ($home + "/agents/elder-care-agent/agent"), model: $model, thinkingDefault: "off"}
]')"
merged_agents="$(jq -n --argjson existing "$existing_agents" --argjson desired "$desired_agents" '
	($existing | map(.id)) as $existing_ids
	| $existing + ($desired | map(select(.id as $id | ($existing_ids | index($id)) | not)))
')"

if [[ "$(jq 'length' <<<"$merged_agents")" -gt "$(jq 'length' <<<"$existing_agents")" ]]; then
	patch_file="$(mktemp)"
	trap 'rm -f "${patch_file:-}"' EXIT
	jq -n --argjson list "$merged_agents" '{agents: {list: $list}}' > "$patch_file"
	openclaw config patch --file "$patch_file"
	rm -f "$patch_file"
	unset patch_file
	echo "    - registered missing snapshot agents"
else
	echo "    - both agents already registered; retained"
fi

if [[ -d "$SOURCE_SKILLS_DIR" ]]; then
	echo "==> Installing shared skills without overwriting local changes"
	mkdir -p "$OPENCLAW_HOME/skills"
	for skill_dir in "$SOURCE_SKILLS_DIR"/*/; do
		[[ -d "$skill_dir" ]] || continue
		destination="$OPENCLAW_HOME/skills/$(basename "${skill_dir%/}")"
		mkdir -p "$destination"
		cp -an "$skill_dir/." "$destination/"
		echo "    - $(basename "${skill_dir%/}")"
	done
fi

echo "==> Installing snapshot personas without overwriting local changes"
for agent_id in "${PERSONA_AGENTS[@]}"; do
	source_workspace="$PERSONA_DIR/$agent_id/workspace"
	destination_workspace="$OPENCLAW_HOME/agents/$agent_id/workspace"
	mkdir -p "$destination_workspace" "$OPENCLAW_HOME/agents/$agent_id/agent"
	cp -an "$source_workspace/." "$destination_workspace/"
	echo "    - $agent_id"
done

echo "==> Finalizing the OpenClaw plugin"
finalize_args=(--openclaw-home "$OPENCLAW_HOME" --plugin-id "$PLUGIN_ID")
[[ "${SKIP_RESTART:-0}" == "1" ]] && finalize_args+=(--skip-restart)
bash "$PLUGIN_INSTALL_SH" finalize "${finalize_args[@]}"

if [[ "${SKIP_WAKEUP:-0}" == "1" ]]; then
	echo "==> SKIP_WAKEUP=1; agent sessions were not created"
else
	echo "==> Creating agent sessions"
	for agent_id in "${PERSONA_AGENTS[@]}"; do
		if openclaw agent -m "hi" --agent "$agent_id" >/dev/null 2>&1; then
			echo "    - $agent_id"
		else
			echo "WARNING: could not wake $agent_id; retry with: openclaw agent -m \"hi\" --agent $agent_id" >&2
		fi
	done
fi

cat <<EOF

==> OpenClaw alert integration is ready.

The script routes alerts from cam_child and cam_elder_care to their matching
agent sessions. Re-running it is safe: existing routes, agents, skills, and
persona files are retained. Open the control UI with: openclaw dashboard
EOF
