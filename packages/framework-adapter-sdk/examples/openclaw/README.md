# smartbuilding-alerts — OpenClaw framework adapter (reference)

A production-ready OpenClaw plugin that subscribes to the SmartBuilding MCP server's per-monitor
alert resources and injects each new alert into the routed OpenClaw session(s). It is the reference
implementation of a **framework adapter** built on
[`@smartbuilding-video/framework-adapter-sdk`](../../).

This is the light **MCP-subscribe + raw pass-through** path. It complements (does not replace) the
`smarthome-video` plugin's heavier embedded-rule + persona-polish path.

## Install

```bash
bash install.sh
```

That builds the SDK, links the plugin into `~/.openclaw/extensions/smartbuilding-alerts`, seeds the
bundled agent personas into `~/.openclaw/agents/` (`cp -n` — never clobbers your edits), and prints
the `openclaw.json` snippet to paste. Then restart the OpenClaw gateway.

`OPENCLAW_HOME` overrides the target home (defaults to `~/.openclaw`).

## Configure

Under the plugin's config in `~/.openclaw/openclaw.json`:

```json
{
  "mcpServer": { "url": "http://localhost:3100/mcp" },
  "monitors": {
    "cam_child": {
      "alerts": [
        { "agentId": "child-safety-agent", "sessionKey": "agent:child-safety-agent:main", "deliver": false },
        { "agentId": "child-safety-agent", "sessionKey": "agent:child-safety-agent:feishu:group:oc_xxx", "deliver": true }
      ]
    },
    "cam_elder_bedroom": {
      "alerts": [
        { "agentId": "elder-wakeup-agent", "sessionKey": "agent:elder-wakeup-agent:main", "deliver": false }
      ]
    }
  }
}
```

| Field | Meaning |
|-------|---------|
| `mcpServer.url` | SmartBuilding MCP endpoint (Streamable HTTP). `mcpServer.headers` for auth if needed. |
| `monitors.<id>.alerts[]` | Where this monitor's alerts go. `<id>` maps to `smartbuilding://monitor/<id>/alerts`. |
| `agentId` | Agent owning the target session (resolves the JSONL path for FS-append). |
| `sessionKey` | OpenClaw session key to deliver into. |
| `deliver` | `false` (default) → raw FS-append into the session, zero LLM. `true` → channel delivery via `subagent.run` (Feishu/WeChat groups). |
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
  has no first-class raw-append API, so — like `smarthome-video` in production — it writes directly
  to the session JSONL. It writes *both* a user separator line and an assistant line because
  ControlUI merges consecutive same-role turns into one timestamped block.

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

## Adding another monitor or agent

Add a `monitors.<id>` entry and (if new) seed the agent's personas under `~/.openclaw/agents/<id>/`.
No code change is needed — the adapter subscribes to whatever monitor ids appear in config.
