# Deploying framework adapters

## MCP server side

The subscription path requires the MCP server to run in **stateful Streamable-HTTP** mode (stdio works too, but a stdio client is a single resident session). Stateful HTTP is the default when started with `--http`:

```bash
node packages/mcp-server/dist/index.js --http --config config.yaml --monitors monitors.yaml
```

Checklist:

- **One McpServer + transport per `mcp-session-id`.** A subscription only persists if the session persists across requests — a stateless per-request server can't broadcast later. `packages/mcp-server/src/index.ts` handles this.
- **Subscribe capability advertised.** `resources.ts` calls `registerCapabilities({ resources: { subscribe: true } })`. Verify with an `initialize` response that lists it.
- **Idle sessions are swept.** `session-sweeper.ts` evicts sessions with no open SSE stream past the idle timeout, so abandoned subscriptions don't leak the registry. A live adapter holds an SSE GET open, which exempts it.

Quick manual verification (curl) is documented in `docs/dev/mcp_subscription_status.md` — `initialize` → `notifications/initialized` → `resources/subscribe` → open `GET /mcp` → observe `notifications/resources/updated` → `resources/read?since=`.

## Adapter side — deployment shapes

- **Embedded in the gateway** (OpenClaw reference): the plugin's `registerService({ start, stop })` ties the adapter lifecycle to the gateway. No separate process to supervise.
- **Standalone daemon / systemd unit**: construct `SmartBuildingAdapter`, call `start()` on boot and `stop()` on `SIGTERM`. Use a `FileCursorStore` so restarts resume.
- **Multiple adapters, disjoint monitor subsets**: several adapters can subscribe to the same MCP server, each with its own `monitorIds`. Each gets its own SSE session and cursor file.

## Cursor persistence

- Default location is adapter-chosen; the OpenClaw reference uses `<OPENCLAW_HOME>/smartbuilding-alerts-cursor.json`.
- Format: `{ "<monitorId>": <lastDeliveredAlertId> }`.
- **Reset**: delete the cursor file (or a monitor's key) → on next start the adapter re-seeds that monitor to the current latest, skipping history.
- **In-memory** (`MemoryCursorStore`, the default when none is given): a restart re-seeds to latest — fine for ephemeral daemons, not for "must not miss alerts across restarts."
- **Id regression / self-heal**: if the source db is recreated and alert ids restart lower, a persisted cursor can end up *ahead* of the server's max id and would silently swallow every new alert. The adapter detects this (`latestId < cursor`), resets the cursor down to the new latest, and warns — no manual step needed. Deleting the cursor file also recovers it.

## Reconnect & robustness

- The SDK reconnects with exponential backoff (default 1000 / 30000 / ×2) on transport failure. The MCP client transport also retries its SSE stream internally; when it exhausts those, the SDK rebuilds the whole session (re-`initialize`, re-subscribe, resync from cursor).
- Optional `pollFallbackMs` (default `0` = off) re-reads each subscribed uri on an interval — a safety net against a permanently-lost notification. A minute (`60000`) is a reasonable value when enabled.

## Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| Subscribe seems accepted but no notifications arrive | server not in stateful HTTP, or the session was swept — confirm the adapter holds an SSE GET open |
| Alerts missed across a restart | expected with `MemoryCursorStore` (re-seeds to latest on restart, skipping anything that arrived while down) — use `FileCursorStore` if restarts must not lose alerts |
| No alerts at all after recreating the source db | id regression — the persisted cursor is stranded above the new max id. The adapter auto-resets on the next sync (`latestId < cursor` → warn); or delete the cursor file/key to force a re-seed |
| Alerts stop after a server bounce | ensure you're on an SDK version whose adapter reconnects on transport `onerror` (not just `onclose`) |
| Duplicate deliveries | at-least-once is by design — make the sink idempotent on `alert.id` |
