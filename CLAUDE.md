# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo orientation

`smart-community-ai-automation` is an AI Agent-native video analysis platform designed for MCP (Model Context Protocol) integration. It provides a universal, framework-agnostic toolkit for video surveillance and analysis — agents can autonomously create, manage, and respond to custom use cases without modifying core components.

**Architecture**: MCP Server (Node.js/TypeScript) + Video Worker (task polling, VLM integration) + Rule Engine (Python override mechanism) + SQLite database layer.

The repository is structured as an npm workspace monorepo:

- `packages/mcp-server/` — MCP Server implementation (stdio/HTTP transport, tools, resources, video-worker orchestration, events webhook)
- `packages/db/` — SQLite database layer (better-sqlite3, schema manager, CRUD operations)
- `packages/tools/` — Tool implementation stubs (alert-query, scene-query, daily-report, monitor-ctl, etc.)
- `packages/rule-engine/` — Rule evaluation engine with Python callback override mechanism
- `tests/dev-mcp-server/` — Python test suite (pytest) for DB, schema, MCP protocol, webhook, worker, rule engine
- `examples/` — Example MCP integrations
- `docs/` — Developer documentation (MCP ramp-up guide, dev status tracking)

## Common commands

From the repo root:

```bash
npm install                           # install all workspace dependencies
npm run build                         # build all packages (tsc)
npm run dev                           # start MCP server in stdio mode (default)
npm run dev --workspace=packages/mcp-server  # explicit workspace target

# Run MCP server with config
cd packages/mcp-server
tsx src/index.ts                      # stdio mode (for MCP clients)
tsx src/index.ts --http               # HTTP mode (port from config.yaml)
tsx src/index.ts --config ../../config.yaml
```

Testing (Python):

```bash
cd tests/dev-mcp-server
pytest test_db.py -v                  # individual test suite
python run_all.py                     # run all 6 test suites (82 assertions)
```

MCP Inspector (smoke test):

```bash
npx @modelcontextprotocol/inspector node packages/mcp-server/dist/index.js
```

## Configuration

Copy `config.yaml.example` to `config.yaml` and edit:

```yaml
db:
  path: ./data/smartbuilding.db

summary_service:
  url: http://localhost:8192          # VLM service (multilevel-video-understanding)

videostream_analytics:
  url: http://localhost:8999          # video stream microservice (not yet implemented)

segments_dir: ./segments
poll_interval_ms: 5000
video_summary_max_concurrent: 2

mcp:
  port: 3100                          # MCP Server HTTP port (stdio mode ignores this)

events_webhook:
  port: 3101                          # Webhook port for external events

schema:                               # DB schema customization (optional)
  video_summary_tasks:
    extensions:
      - { name: "event", type: "text", required: true }
      - { name: "severity", type: "text", required: true }
```

The `schema` section is optional — use it to add custom columns to core tables (`video_summary_tasks`, `alerts`) or define entirely new tables via `custom_tables`. The SchemaManager validates types and ensures idempotency.

## Architecture

### MCP Server entry flow

`packages/mcp-server/src/index.ts`:
1. Load `config.yaml` via `loadConfig()`
2. Initialize SQLite DB (`SmartBuildingDB`) + apply schema customization (`SchemaManager`)
3. Start `WorkerService` (task poller + VLM client)
4. Start `EventsEndpoint` (HTTP webhook receiver on `:3101`)
5. Create `McpServer` instance, register tools + resources
6. Connect transport: stdio (default) or HTTP (SSE via Express)
7. Graceful shutdown on SIGINT/SIGTERM

### Video processing pipeline

```
External microservice (videostream-analytics)
  │ POST /events (motion / static / recording)
  ▼
EventsEndpoint (:3101)
  │ create pending video_summary_task
  ▼
SQLite (video_summary_tasks table)
  ▲
  │ poll (default 5s interval)
  ▼
WorkerService (TaskPoller)
  ├─ VllmYield (throttle if vllm queue full)
  ├─ ClipExtractor (ffmpeg cut segment)
  └─ VlmClient (POST /v1/summary → VLM service)
       │ write summary_text to task
       │ call rule engine (defaultRuleEvaluator + optional Python override)
       ▼
     Alert creation (if rule fires)
       │
       └─ MCP notification (notifications/resources/updated)
```

### Database schema

Core tables (created by `SmartBuildingDB.initialize()`):

- `monitors` — video source registry (`id`, `name`, `source_url`, `use_case`, `status`, timestamps)
- `alerts` — triggered alerts (`id`, `source_id`, `event`, `severity`, `desc`, `acked`, `clip_path`, timestamps)
- `video_summary_tasks` — VLM processing queue (`id`, `source_id`, `clip_path`, `status`, `summary_text`, `latency_seconds`, tokens, timestamps)
- `monitor_state` — per-monitor key-value state (JSON blob)

Schema customization: add columns to existing tables or define new tables via `config.yaml` → `schema:` section. The SchemaManager applies `ALTER TABLE ADD COLUMN` (idempotent) at server startup.

### MCP tools

Registered in `packages/mcp-server/src/tools.ts`:

| Tool | Purpose | Key params |
|------|---------|-----------|
| `smartbuilding_alert_query` | Query or acknowledge alerts | `monitor_id`, `status`, `limit`, `ack_id` |
| `smartbuilding_state_query` | Read or write monitor state (JSON) | `monitor_id`, `action` (get/set), `state` |
| `smartbuilding_scene_query` | Real-time scene analysis | `monitor_id`, `question` (not yet implemented) |
| `smartbuilding_daily_report` | Generate daily summary | `monitor_id`, `date` (YYYY-MM-DD) |
| `smartbuilding_monitor_ctl` | Start/stop/register video sources | `action`, `monitor_id`, `source_url`, `use_case` |
| `smartbuilding_rule_eval` | Manually trigger rule evaluation | `monitor_id`, `task_id` (optional) |
| `smartbuilding_video_db` | Raw SQL query (read-only SELECT) | `query` |
| `smartbuilding_use_case_validate` | Validate use-case schema | `use_case`, `example_summary` |

### MCP resources

Registered in `packages/mcp-server/src/resources.ts`:

- `smartbuilding://monitors` — list all monitors
- `smartbuilding://monitor/{id}/latest-frame` — latest frame snapshot (not yet implemented)
- `smartbuilding://monitor/{id}/stats` — event/alert counters
- `smartbuilding://monitor/{id}/alerts` — recent alerts (subscribable)

Resource URIs support template parameters (`{id}`). Clients can subscribe to resources and receive `notifications/resources/updated` when data changes.

### Rule Engine

`packages/rule-engine/src/index.ts`: `defaultRuleEvaluator(result: RuleContext) → RuleResult`

Default rule: if `result.event === "critical_alert"`, fire alert with `severity: "critical"`.

**Python override mechanism**: place `use-cases/<use_case>/evaluate_rules.py` in the project root. If present, the rule engine spawns it via `execFile`, passes `RuleContext` as JSON stdin, expects `RuleResult` JSON stdout. On failure (script error, timeout), falls back to `defaultRuleEvaluator`.

## TypeScript conventions

- **ESM modules**: all packages use `"type": "module"` in `package.json`. Imports must include `.js` extension even for `.ts` source files (TypeScript convention for ESM).
- **Build**: `tsc` compiles `src/` → `dist/` in each package. No bundler (esbuild/webpack) is used — raw tsc output is the artifact.
- **Dev workflow**: use `tsx` to run TypeScript directly without pre-compiling: `tsx src/index.ts`. Production: compile first (`npm run build`), then `node dist/index.js`.
- **Workspace dependencies**: internal package refs like `"@smartbuilding-video/db": "*"` resolve via npm workspaces. Run `npm install` at the root to link them.

## Testing

Test suite is Python-based (pytest), located in `tests/dev-mcp-server/`:

- `test_db.py` — DB CRUD operations (22 assertions)
- `test_schema.py` — Schema customization (16 assertions)
- `test_tools_mcp.py` — MCP protocol end-to-end (16 assertions, spawns MCP server subprocess)
- `test_events_webhook.py` — Webhook receiver (9 assertions)
- `test_video_worker.py` — Video worker chain (8 assertions, mocks VLM service)
- `test_rule_engine.py` — Rule engine + Python override (11 assertions)

Run `python run_all.py` to execute all suites. Each test uses isolated temp DB (`conftest.py` fixtures).

No TypeScript/Jest tests exist yet. The plugin TS has no test suite.

## Ports

| Port | Service | Access |
|------|---------|--------|
| `:3100` | MCP Server (HTTP mode) | `http://localhost:3100` (SSE endpoint) |
| `:3101` | Events Webhook | `POST http://localhost:3101/events` |
| `:8192` | VLM service (multilevel-video-understanding) | `POST /v1/summary` |
| `:8999` | videostream-analytics microservice | (not yet implemented) |

## Development status

See [docs/dev_status.md](docs/dev_status.md) for task tracking. Key milestones:

- **WW24 (done)**: repo structure, MCP server, DB layer, tools, resources, video-worker, rule engine, 82/82 test assertions pass
- **WW25 (in progress)**: MCP Server structure dev
- **WW26–WW28**: TypeScript library, resource subscription, DB schema customization
- **WW29–WW32**: agent framework adapter, skills, integration, documentation

## Use cases

Three use cases are defined (see [README.md](README.md)):

| ID | Description | Status |
|----|-------------|--------|
| `Fridge_monitor` | Refrigerator monitoring — shortage alerts, diet suggestions, Q&A | Planned |
| `Child_safety` | Child danger alert — real-time risky behavior detection, immediate alerts, summaries | Planned |
| `Elder_wakeup` | Elder care wake-up tracking — daily wake-up monitoring, deviation alerts, reports | Planned |

Each use case should define a Python override script under `use-cases/<use_case>/evaluate_rules.py` to customize alert logic.

## Debugging

- **MCP Server logs**: stderr output (use `console.error()` in TypeScript, appears in client logs)
- **Database inspection**: `sqlite3 data/smartbuilding.db` → `.tables`, `SELECT * FROM alerts LIMIT 10;`
- **Worker state**: check `video_summary_tasks` table — `status` column shows `pending` / `completed` / `failed`
- **VLM service health**: `curl http://localhost:8192/v1/health`
- **Webhook health**: `curl http://localhost:3101/health`
- **MCP Inspector**: `npx @modelcontextprotocol/inspector node packages/mcp-server/dist/index.js` — interactive tool explorer

## Key dependencies

- `@modelcontextprotocol/sdk` — MCP protocol implementation (server, transports, tool/resource registration)
- `better-sqlite3` — synchronous SQLite3 bindings (native module)
- `zod` — TypeScript schema validation (used for tool input schemas)
- `yaml` — YAML config parsing
- `express` — HTTP server for events webhook + MCP HTTP transport
- `tsx` — TypeScript executor (dev-time only, replaces `ts-node`)
- `typescript` — TypeScript compiler

## Related documentation

- **MCP ramp-up guide**: [docs/mcp-server-rampup-guide.md](docs/mcp-server-rampup-guide.md) — explains MCP vs OpenClaw plugin, Node.js toolchain for Python/C++ developers, transport modes, JSON-RPC protocol
- **MCP Getting Started**: [docs/smart_community_mcp_gsg.md](docs/smart_community_mcp_gsg.md)
- **Dev status**: [docs/dev_status.md](docs/dev_status.md) — task tracking, integration milestones

## Conventions

- **Monitor ID**: string identifier for video sources (e.g., `cam_fridge`, `cam_child_01`). Used across all tables as `source_id` or `monitor_id`.
- **Use case**: string identifier for behavior profile (e.g., `Fridge_monitor`, `Child_safety`, `Elder_wakeup`). Determines which rule script is invoked.
- **Timestamps**: all DB timestamps are ISO 8601 strings (e.g., `2026-06-23T14:30:00.123Z`). Use `new Date().toISOString()` in TS, `datetime.now(timezone.utc).isoformat()` in Python.
- **Task status**: `pending` (created, awaiting worker) → `completed` (VLM processing done) or `failed` (error).
- **Alert severity**: arbitrary string (e.g., `info`, `warn`, `critical`). Defined by rule engine output.
- **Config placeholders**: none yet (unlike the smarthome repo, no `${HOME}` or `~/` expansion is implemented).
