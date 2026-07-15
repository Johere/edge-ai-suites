# smartbuilding-alerts — OpenClaw framework adapter (reference)

A production-ready OpenClaw plugin that subscribes to the SmartBuilding MCP server's per-monitor
alert resources and injects each new alert into the routed OpenClaw session(s). It is the reference
implementation of a **framework adapter** built on
[`@smartbuilding-video/framework-adapter-sdk`](../../).

This is the light **MCP-subscribe + raw pass-through** path: the SDK owns the protocol (subscribe,
cursor dedup, ordering, reconnect) and the plugin just routes each alert into a session — no
embedded rule engine, no persona polish.

## Install

```bash
bash install.sh
```

That fully installs the adapter — no manual `openclaw.json` editing required. It:

1. builds the SDK and installs the plugin's deps,
2. registers the plugin entry in `openclaw.json` (`openclaw config patch`, object-merge — leaves other plugins untouched),
3. merges the demo agents into `agents.list[]` (merge-by-id — never clobbers agents you added),
4. links the plugin into `~/.openclaw/extensions/smartbuilding-alerts`,
5. seeds the bundled agent personas into `~/.openclaw/agents/` (`cp -n` — never clobbers your edits),
6. restarts the OpenClaw gateway (`openclaw gateway restart`),
7. wakes the demo agents (`openclaw agent -m hi`) so their sessions exist.

**Order matters (steps 2–4):** the plugin declares a required-field config schema and activates
`onStartup`, so OpenClaw enforces that schema the instant the plugin is *discovered* (symlinked).
The config is therefore written *before* the symlink — otherwise a linked-but-unconfigured plugin
makes the whole `openclaw.json` invalid and `config patch` refuses to run. The script also unlinks
first, so a half-finished run self-heals on the next invocation.

It is idempotent — safe to re-run; existing personas, plugin config, and agents are preserved.

Env overrides: `OPENCLAW_HOME` (target home, default `~/.openclaw`), `MCP_URL` (default
`http://localhost:3100/mcp`), `AGENT_MODEL` (default `Qwen3.5`), `SKIP_RESTART=1`, `SKIP_WAKEUP=1`.

## Configure

`install.sh` writes this into `plugins.entries.smartbuilding-alerts` of
`~/.openclaw/openclaw.json` — you normally don't edit it by hand:

```json
"smartbuilding-alerts": {
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
      },
      "cam_elder_bedroom_2": {
        "alerts": [
          { "agentId": "elder-wakeup-agent", "sessionKey": "agent:elder-wakeup-agent:cam_elder_bedroom_2", "deliver": false }
        ]
      }
    }
  }
}
```

| Field | Meaning |
|-------|---------|
| `mcpServer.url` | SmartBuilding MCP endpoint (Streamable HTTP). `mcpServer.headers` for auth if needed. |
| `monitors.<id>.alerts[]` | Where this monitor's alerts go. `<id>` maps to `smartbuilding://monitor/<id>/alerts`. |
| `agentId` | Agent owning the target session (resolves the JSONL path for FS-append). |
| `sessionKey` | Target OpenClaw session key, `agent:<agentId>:<session>`. The examples route each monitor into its own session (`…:cam_child`), so alerts don't mix with the agent's `main` chat. |
| `deliver` | `false` (default) → raw FS-append into the session, zero LLM. `true` → channel delivery via `subagent.run` (e.g. a Feishu group session) — *not yet verified end-to-end*. |
| `cursorFile` | *(optional)* delivery cursor path. Default `<OPENCLAW_HOME>/smartbuilding-alerts-cursor.json`. |
| `pollFallbackMs` | *(optional)* safety-net poll (ms) against a lost notification. Default `0` (off). |

## How it works

```
MCP server  --notifications/resources/updated-->  SDK adapter (this plugin)
                                                     │  read alerts since cursor
                                                     ▼
                                                  AlertSink
                                            ┌────────────────────┐
                             deliver:false  │ FS-append user +   │  (raw, zero LLM)
                                            │ assistant JSONL    │
                                            ├────────────────────┤
                             deliver:true   │ subagent.run,      │  (one relay LLM hop)
                                            │ verbatim relay     │
                                            └────────────────────┘
```

- The SDK owns the protocol layer (subscribe, cursor dedup, per-monitor ordering, reconnect).
- `src/sink.ts` owns the OpenClaw injection layer.
- `src/session-append.ts` is the raw-append path. **See its `TODO(migrate)`**: OpenClaw v2026.6.9
  has no first-class raw-append API, so it writes directly to the session JSONL. It writes *both* a
  user separator line and an assistant line because ControlUI merges consecutive same-role turns
  into one timestamped block.

## Files

| Path | Role |
|------|------|
| `index.ts` | plugin entry: parse config → build adapter → `registerService` |
| `openclaw.plugin.json` | plugin metadata + config schema |
| `src/config.ts` | validate/normalize `api.pluginConfig` |
| `src/sink.ts` | OpenClaw `AlertSink` (deliver:false FS-append / deliver:true channel) |
| `src/format.ts` | `formatSeparator` + `formatAlert` (raw, no persona) |
| `src/session-append.ts` | vendored raw-append helper (with migration TODO) |
| `agents/` | hard-copied agent personas (self-contained; seeded by `install.sh`) |
| `scripts/` | dev helpers (`fire_models.sh` — re-apply this machine's model providers after a reinstall) |

## Adding another monitor or agent

Add a `monitors.<id>` entry and (if new) seed the agent's personas under `~/.openclaw/agents/<id>/`.
No code change is needed — the adapter subscribes to whatever monitor ids appear in config.
