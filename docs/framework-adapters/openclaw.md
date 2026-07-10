# OpenClaw reference adapter

The reference framework adapter lives at
[`packages/framework-adapter-sdk/examples/openclaw/`](../../packages/framework-adapter-sdk/examples/openclaw)
(`smartbuilding-alerts`). This page explains *how it works*; for install/config steps see the
example's own [README](../../packages/framework-adapter-sdk/examples/openclaw/README.md) — don't
duplicate them here.

## Shape

```
index.ts            definePluginEntry → parse config → build SmartBuildingAdapter → registerService
openclaw.plugin.json plugin metadata + config schema
src/config.ts       validate api.pluginConfig → { mcpServer, monitors: { <id>: { alerts: [...] } } }
src/sink.ts         the OpenClaw AlertSink (the injection layer)
src/format.ts       formatSeparator + formatAlert (raw, no persona)
src/session-append.ts vendored raw-append helper (with migration TODO)
agents/             hard-copied agent personas (self-contained)
install.sh          build + symlink + cp -n personas + print openclaw.json snippet
```

`index.ts` builds the adapter from config and registers it as an OpenClaw service, so `adapter.start()`
runs when the gateway boots and `adapter.stop()` on shutdown. The cursor is a `FileCursorStore` at
`<OPENCLAW_HOME>/smartbuilding-alerts-cursor.json` so a gateway restart resumes without replay.

## The sink — two delivery branches

`src/sink.ts` reads the per-monitor route table and, for each target, chooses by `deliver`:

- **`deliver: false` (default) → raw FS-append.** Zero LLM. `appendAlertTurns()` writes a user
  "separator" line plus an assistant line straight into the agent's session JSONL. The agent sees
  the alert as context on its next turn and decides whether to react.
- **`deliver: true` → `api.runtime.subagent.run({ deliver: true, extraSystemPrompt: <verbatim relay> })`.**
  For channel-bound sessions (Feishu/WeChat groups). The channel adapter runs one LLM hop, pinned by
  the relay prompt to pass the raw alert through unrewritten. An `idempotencyKey` (`sb-alert:<monitor>:<id>`)
  lets the gateway suppress a duplicate run.

There is deliberately **no persona polish** here — that's the difference from `smarthome-video`.

## Why FS-append, and why two lines

OpenClaw v2026.6.9 exposes no first-class raw-append API: `api.runtime.subagent.run` always drives an
LLM, and the lower-level `patchSessionEntry` isn't surfaced through the plugin SDK. So the adapter
appends directly to `~/.openclaw/agents/<id>/sessions/<sessionId>.jsonl` — the same fact-path
`smarthome-video` uses in production (`src/session-delete.ts::appendAlertGroupToMainSession`).

It writes **both** a user line and an assistant line because ControlUI groups consecutive same-role
messages into one visual block headed by the *first* message's timestamp; assistant-only appends
would glue every alert together and freeze the displayed time. Both lines are synthesized by the
plugin (no LLM). `src/session-append.ts` carries the `TODO(migrate)`: swap the `appendFileSync` for
`api.runtime.session.append(...)` once OpenClaw ships it.

## `auth: "gateway"` for subagent routes

If you extend this adapter with an HTTP route that calls `api.runtime.subagent.run()`, that route
must declare `auth: "gateway"` (not `"plugin"`). A `"plugin"` route gets an empty-scope client and
`subagent.run` fails with `missing scope: operator.write`. (The reference adapter drives `subagent.run`
from its service, not a route, so this only matters if you add one.)

## Relationship to smarthome-video

Complementary, not competing:

| | smarthome-video | smartbuilding-alerts (this) |
|---|---|---|
| Rules | embedded in the plugin | in the MCP server's rule engine |
| Delivery | persona-polished, ephemeral subagent + FS-append | raw pass-through |
| Transport | in-process callback | MCP `resources/subscribe` over HTTP |
| Reuse across frameworks | OpenClaw-specific | SDK reusable; only the sink is OpenClaw-specific |

A possible future migration: refactor smarthome-video's notifier onto the adapter model so its rules
publish alerts that any framework adapter can consume.

## Personas

`agents/` is hard-copied from the smarthome runtime workspace (`child-safety-agent`,
`elder-wakeup-agent`, `fridge-agent-en`) so the example is self-contained. It's now an independent
asset — if the smarthome personas change, re-sync manually (infrequent). `install.sh` seeds them with
`cp -n`, so re-running never clobbers a persona you've edited.
