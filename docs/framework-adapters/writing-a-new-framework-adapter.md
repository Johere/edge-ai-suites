# Writing a new framework adapter

You need an adapter when a new agent framework should receive SmartBuilding alerts. The generic MCP-client half is done for you by [`@smartbuilding-video/framework-adapter-sdk`](../../packages/framework-adapter-sdk); you write the injection half — usually ~50 lines.

## 1. Install

```bash
npm i @smartbuilding-video/framework-adapter-sdk
```

## 2. Implement `AlertSink`

One method. Deliver the alert into your framework's session/channel. **Be idempotent on `alert.id`** — the SDK guarantees at-least-once, so the same alert may arrive twice after a retry or restart.

```ts
import type { AlertSink } from "@smartbuilding-video/framework-adapter-sdk";

const sink: AlertSink = {
  async push({ monitorId, alert }) {
    const targets = routeTable[monitorId] ?? [];   // your monitor → session map
    for (const t of targets) {
      await myFramework.deliver(t.session, `[${alert.useCase}] ${alert.description ?? ""}`);
    }
  },
};
```

`alert` is the DB row: `{ id, monitorId, useCase, description?, createdAt, taskId?, eventId?, ... }`. It's use-case-agnostic — severity/event fields, if any, live on the JOIN'd task, not here.

## 3. Provide `AdapterConfig`

```ts
import { SmartBuildingAdapter, FileCursorStore } from "@smartbuilding-video/framework-adapter-sdk";

const adapter = new SmartBuildingAdapter(
  {
    transport: { kind: "http", url: "http://localhost:3100/mcp" },  // or { kind: "stdio", command, args }
    monitorIds: Object.keys(routeTable),
    cursorStore: new FileCursorStore("/var/lib/my-adapter/cursor.json"),  // omit → in-memory
    pollFallbackMs: 0,   // set e.g. 60000 to guard against a lost notification
    logger: console,     // any { debug, info, warn, error }
  },
  sink,
);
```

## 4. Own a long-lived process

Call `start()` when your host boots and `stop()` on shutdown. Inside a plugin, tie these to the plugin's service lifecycle; as a daemon, wire them to `SIGTERM`.

```ts
await adapter.start();                 // connect + subscribe + seed/resume cursors
process.on("SIGTERM", () => adapter.stop());
```

`start()` subscribes to each monitor, then seeds the cursor to the current latest (no history replay) or, if a persisted cursor exists, delivers anything missed while you were down.

## 5. Verify

Point the adapter at a mock MCP server, fire a fake alert, assert the sink saw it. The SDK's own tests do exactly this — see [`tests/framework-adapter-sdk/`](../../tests/framework-adapter-sdk) (`fixtures/mock-mcp-server.ts` + `adapter.test.ts`) for a copy-paste-able harness covering seeding, ordering, reconnect, poll fallback, and at-least-once replay.

## What you get for free

Cursor dedup (never push an id twice), per-monitor ordering (serialized reads + ascending push), cross-monitor isolation, reconnect with backoff, and optional poll fallback. You only decide *where the alert goes* and *how to deliver it*.

## When NOT to write an adapter

If your host can't run a resident process or has no session concept, skip the SDK and take an **outbound webhook** instead: have the MCP server (or a tiny relay) POST to an endpoint your host owns. You lose subscribe-based push and cursor dedup, but you don't need a long-lived client.

## Reference implementation

[`packages/framework-adapter-sdk/examples/openclaw/`](../../packages/framework-adapter-sdk/examples/openclaw) is a complete, production-usable OpenClaw adapter — read its `src/sink.ts` for a real injection layer (FS-append + channel-delivery branches) and see [openclaw.md](openclaw.md) for the walkthrough.
