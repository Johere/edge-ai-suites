# Development Status — Jiaojiao's Tasks

## SmartBuilding Video MCP Server

| # | Task | Effort | Schedule | Status |
|---|------|--------|----------|--------|
| 1 | MCP Server structure dev | 2W | WW24–WW25 | In progress |
| 2 | TypeScript library (tools) | 1W | WW26 | Not started |
| 3 | MCP resource subscription | 1W | WW27 | Not started |
| 4 | Support DB schema customization | 1W | WW28 | Not started |

## Agent Framework Adapter

| # | Task | Effort | Schedule | Status |
|---|------|--------|----------|--------|
| 5 | Agent framework adapter wrapper | 1W | WW29 | Not started |
| 6 | OpenClaw adapter: plugin | 1W | WW30 | Not started |

## SmartBuilding Video Skills and Agent Workspace

| # | Task | Effort | Schedule | Status |
|---|------|--------|----------|--------|
| 7 | Skill tuning: smartbuilding-toolkit, video-understanding | 1W | WW31 | Not started |
| 8 | Agent Workspace tuning: child-safety-assistant, elder-wakeup-assistant, refrigerator-assistant (migrate from demo) | 1W | WW32 | Not started |

## Multi-level Video Understanding Microservice

| # | Task | Effort | Schedule | Status |
|---|------|--------|----------|--------|
| 9 | Caption only | 1W | WW25 | Not started |
| 10 | Dynamic Task | 1W | WW27 | Not started |

## Integration & Documents

| # | Task | Effort | Schedule | Status |
|---|------|--------|----------|--------|
| 11 | Integration and bug fix | 1W | WW31 | Not started |
| 12 | User guide, Get-started-guide, Developer's guide | 2W | WW31–WW32 | Not started |

---

## Integration Milestones (with other owners)

| Time | Integration Point | Collaborators |
|------|-------------------|---------------|
| WW27 | MCP resource subscription + Use case adapter wrapper (Jie) ready → 联调 MCP Server 与 Use Case Adapter 的事件/告警通道 | Jiaojiao + Jie |
| WW28 | DB schema customization + Register new use case (Jie) → 联调用例注册流程端到端 | Jiaojiao + Jie |
| WW30 | OpenClaw adapter: plugin 依赖 Video Stream Analytics microservice (Jie WW25–WW27 完成) → 联调 adapter 调用 microservice API | Jiaojiao + Jie |
| WW31 | Skill tuning + Integration bug fix；依赖 Use Case Adapter post-proc (Jie) + Dynamic video source (Jie) → 端到端用例验证 | Jiaojiao + Jie |
| WW31–WW32 | Integration and bug fix + E2E Validation (Zhonghua) + Documents → 全员联调 | Jiaojiao + Jie + Zhonghua |

---

## Development Tracing

### Done (WW24)

- [x] Repo 初始化：README.md、.gitignore、LICENSE
- [x] Monorepo 结构搭建：root `package.json` with npm workspaces
- [x] `packages/mcp-server/` 骨架
  - `src/index.ts` — MCP Server entry，stdio transport，加载 config → 注册 tools → 注册 resources → connect
  - `src/tools.ts` — 8 个 MCP tools 注册（alert_query, state_query, scene_query, daily_report, monitor_ctl, rule_eval, video_db, use_case_validate）
  - `src/resources.ts` — 4 个 MCP resources（monitors, latest-frame, stats, alerts）
  - `src/config.ts` — ServerConfig 接口 + loadConfig
  - `src/events-endpoint.ts` — EventsEndpoint webhook receiver 接口
  - `src/video-worker/` — WorkerService, TaskPoller, VlmClient, ClipExtractor, VllmYield
- [x] `packages/tools/` 骨架 — 8 个 tool 实现 stub（接口 + 类型定义）
- [x] `packages/db/` 骨架 — Database, SchemaManager, types (Monitor, Alert, VideoSummaryTask)
- [x] `packages/rule-engine/` 骨架 — defaultRuleEvaluator + RuleContext/RuleResult types

### Done (WW24 cont.)

- [x] `packages/db/` 完整实现：better-sqlite3 集成，WAL 模式，建表 migration（monitors, alerts, video_summary_tasks, monitor_state），完整 CRUD 方法
- [x] `packages/db/` SchemaManager 实现：YAML 声明式 schema 扩展，ALTER TABLE ADD COLUMN，类型检查警告，prompt ↔ schema 校验
- [x] `packages/mcp-server/src/config.ts`：YAML 配置解析（yaml 库），完整 ServerConfig 接口
- [x] `packages/mcp-server/src/tools.ts`：8 个 tools 全部接通 DB 层（alert_query 支持 ack，state_query 读写，daily_report 生成统计，monitor_ctl CRUD+启停，video_db 原始 SQL，use_case_validate 字段校验）
- [x] `packages/mcp-server/src/resources.ts`：4 个 resources 接通 DB（ResourceTemplate 用于参数化 URI）
- [x] `packages/mcp-server/src/video-worker/`：完整 task-poller → vllm-yield → vlm-client 链路，处理结果写 DB + 创建 alert + 触发 MCP notification
- [x] `packages/mcp-server/src/events-endpoint.ts`：原生 HTTP webhook server（POST /events + GET /health），接收 videostream-analytics 事件 → 创建 pending task
- [x] `packages/mcp-server/src/index.ts`：完整 wiring（DB init → schema apply → worker service → events endpoint → MCP transport → graceful shutdown）
- [x] `packages/rule-engine/`：defaultRuleEvaluator + Python callback override 机制（execFile 调用 use-cases/ 下 .py，失败自动 fallback 到默认）
- [x] npm install + 全部 4 个 package TypeScript 编译通过
- [x] 添加 `config.yaml.example` 示例配置

### Done (WW24 cont. — testing)

- [x] 创建 Python 测试框架：`tests/dev-mcp-server/`（conftest.py: TestResult, init_test_db, temp dir helpers）
- [x] test_db.py — DB CRUD 全流程（22 assertions）：Monitor/Alert/Task 增删改查、State 读写、Stats、Raw Query
- [x] test_schema.py — Schema 定制化（16 assertions）：ALTER TABLE ADD COLUMN、幂等性、type mismatch 检测、prompt ↔ schema 校验
- [x] test_tools_mcp.py — MCP 协议端到端（16 assertions）：启动 MCP Server subprocess → JSON-RPC initialize → tools/list → resources/list → 逐个 tool call 验证
- [x] test_events_webhook.py — Events Webhook（9 assertions）：Node.js mock → POST /events → DB task 创建、错误处理
- [x] test_video_worker.py — Video Worker 链路（8 assertions）：Python mock VLM HTTP server → Node.js worker → task 完成 → alert 写入
- [x] test_rule_engine.py — Rule Engine（11 assertions）：默认规则 + Python override 成功/失败 fallback
- [x] run_all.py — 全部 6 suites，82/82 assertions 通过

### Next Steps (WW25)

- [ ] 本地 MCP Inspector smoke test：启动完整 MCP Server（stdio），验证 tools/resources 列表 + 交互
- [ ] 集成 rule-engine 到 video-worker（task 完成后自动触发 evaluateWithOverride）
- [ ] 补充 use-cases/ 示例：child_safety/evaluate_rules.py、elder_wakeup/evaluate_rules.py
- [ ] 端到端集成测试：events webhook → pending task → VLM mock → rule eval → alert → MCP notification
