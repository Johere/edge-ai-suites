# Framework adapters

How SmartBuilding alerts reach an agent framework — **host-agnostic** at the MCP server, framework-specific only in a thin adapter.

- The MCP server never knows about OpenClaw, Feishu, or sessions. It only emits the protocol-standard `notifications/resources/updated`.
- Each agent framework runs a **framework adapter**: a long-lived process that holds a generic MCP client (from [`@smartbuilding-video/framework-adapter-sdk`](../../packages/framework-adapter-sdk)) plus a small framework-specific `AlertSink`.
- The **route table** (monitor → session mapping) lives in the adapter, not the server.

## Architecture

```
┌─────────────────────────────┐         ┌─────────────────────────────┐
│  MCP server (host-agnostic) │         │  Framework adapter          │
│  packages/mcp-server        │         │  (one per framework)        │
│                             │◀────────│  long-lived process         │
│  task-poller → createAlert  │  MCP    │  ┌────────────────────────┐ │
│      ↓                      │  over   │  │ SmartBuildingAdapter   │ │
│  onAlert(monitorId)         │  HTTP   │  │  (framework-adapter-sdk)│ │
│      ↓                      │  (SSE)  │  │  - MCP client           │ │
│  sendResourceUpdated({uri}) │────────▶│  │  - subscribe/reconnect  │ │
│                             │         │  │  - dedup by cursor      │ │
│  resources.ts               │◀────────│  └──────────┬─────────────┘ │
│  read alerts (since cursor) │  read   │             │ sink.push()   │
│                             │────────▶│             ▼               │
└─────────────────────────────┘         │  ┌────────────────────────┐ │
                                         │  │ AlertSink (framework)  │ │
                                         │  │  - reads route table   │ │
                                         │  │  - injects into session│ │
                                         │  └────────────────────────┘ │
                                         └─────────────────────────────┘
```

## Protocol flow

1. `task-poller` matches a rule → `db.createAlert()` → `onAlert(monitorId)`.
2. The MCP server broadcasts `notifications/resources/updated { uri: "smartbuilding://monitor/<id>/alerts" }` to every MCP session subscribed to that uri. **The notification carries only the uri — no payload.**
3. The adapter's SDK client receives the notification, looks up its per-monitor cursor, and reads `smartbuilding://monitor/<id>/alerts?since=<cursor>`.
4. For each new alert (id > cursor, ascending) the SDK calls `sink.push({ monitorId, alert })`.
5. After all pushes for the batch succeed, the SDK advances the cursor. A mid-batch failure leaves the cursor put → the batch replays (at-least-once).

## Two layers

| Layer | Who provides it | Responsibility |
|-------|-----------------|----------------|
| **Protocol layer** | the SDK (`SmartBuildingAdapter`) | connect, subscribe, cursor dedup, per-monitor ordering, reconnect, optional poll fallback |
| **Injection layer** | your framework's `AlertSink` | route the alert to the right session/channel and deliver it |

## Cooldown is layered (the SDK does *not* throttle)

| Level | Where | What |
|-------|-------|------|
| L1 business cooldown | MCP server rule engine | "does this event even become an alert" |
| L2 delivery dedup | SDK cursor | "never push the same alert id twice" (automatic) |
| L3 channel throttle | your `AlertSink` (optional) | "already pushed 3 to this Feishu group in 5 min → coalesce" |

The SDK deliberately adds no time-window suppression: it would break at-least-once and the "what's noisy" decision depends on channel context the SDK can't see.

## When to write an adapter vs. an outbound webhook

- **Write an adapter** when the host can run a long-lived process *and* has a session concept to inject into (OpenClaw, a daemon bridging to a chat backend, etc.). You get subscribe-based push, cursor dedup, and ordering for free.
- **Fall back to an outbound webhook** when the host can't stay resident or has no session concept. Point the MCP server (or a tiny relay) at an HTTP endpoint the host owns.

## See also

- [writing-a-new-framework-adapter.md](writing-a-new-framework-adapter.md) — 5-step guide to a new framework.
- [deployment.md](deployment.md) — MCP-server-side setup, adapter deployment shapes, cursor/troubleshooting.
- [openclaw.md](openclaw.md) — walkthrough of the OpenClaw reference implementation.
