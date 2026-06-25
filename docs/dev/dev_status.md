# Development Status

## Global Project Status

| # | Module | Owner | Schedule | Status | Notes |
|---|---|---|---|---|---|
| 1 | SmartBuilding Video MCP Server | Jiaojiao | WW24–WW28 | In progress | WW24 完成 monorepo + 8 tools + 4 resources + DB + 测试框架 (82/82 pass)；WW25 推 MCP Server 主链路 |
| 2 | Agent Framework Adapter | Jiaojiao | WW29–WW30 | Not started | 含 wrapper + OpenClaw plugin |
| 3 | Use Case Adapter | Jie | WW28–WW31 | Not started | wrapper + register new use case + 自定义 post-proc |
| 4 | SmartBuilding Video Skills & Workspace | Jiaojiao | WW31–WW32 | Not started | smartbuilding-toolkit / video-understanding skill 调优 + 3 个 assistant workspace |
| 5 | Video Stream Analytics Microservice | Jie | WW24–WW27 | In progress | 微服务结构、motion + NPU prefilter 已迁移完成；动态视频源管理 WW27 收尾 |
| 6 | Multi-level Video Understanding Microservice | Jiaojiao | WW25, WW27 | Not started | Caption only + Dynamic Task |
| 7 | Integration & Documents | Jiaojiao + Jie + Zhonghua | WW31–WW32 | Not started | 联调 + bug fix + E2E validation + 用户文档 |

---

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

## Jie's Tasks — Video Stream Analytics Microservice

| # | Task | Effort | Schedule | Status |
|---|------|--------|----------|--------|
| 1 | Microservice structure dev | 2W | WW24–WW25 | Done |
| 2 | Motion detection + NPU Prefilter (migrate from demo) | 1W | WW26 | Done |
| 3 | Dynamic video source management | 1W | WW27 | In progress |

## Jie's Tasks — Use Case Adapter

| # | Task | Effort | Schedule | Status |
|---|------|--------|----------|--------|
| 4 | Register new use case | 2W | WW28–WW29 | Not started |
| 5 | Use case adapter wrapper | 1W | WW30 | Not started |
| 6 | Customize post-proc (summary-parser / rule engine) | 1W | WW31 | Not started |

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

- [x] 本地 MCP Inspector smoke test：启动完整 MCP Server（stdio），验证 tools/resources 列表 + 交互

### Next Steps (WW26)

- [ ] MCP tools 对照 finalized design 实现
- [ ] 集成 rule-engine 到 video-worker（task 完成后自动触发 evaluateWithOverride）
- [ ] 补充 use-cases/ 示例：child_safety/evaluate_rules.py、elder_wakeup/evaluate_rules.py
- [ ] 端到端集成测试：events webhook → pending task → VLM mock → rule eval → alert → MCP notification

---

## Development Tracing — Jie

### Done (WW24)

- [x] `videostream-analytics/` 仓库骨架 + `pyproject.toml`（FastAPI + Uvicorn + Pydantic + OpenCV + httpx，可选 `[npu]` extras）
- [x] FastAPI 服务 `service.py` + Uvicorn 入口，监听 `:8999`
- [x] `SourceManager` (`source_worker.py`)：维护 `{source_id: StreamPipeline}` 映射，生命周期管理
- [x] `StreamPipeline` (`stream_monitor/rtsp_monitor.py`)：RTSP → MotionDetector → SegmentExtractor → ContinuousRecorder
- [x] `EventSink` 抽象 (`sinks/`)：WebhookSink / StdoutSink / NullSink
- [x] CLI 三模式 (`cli.py`)：`serve` / `stream` / `health`，pyproject `[project.scripts]` 注册入口
- [x] Docker 化 (`docker/Dockerfile` + `docker/docker-compose.yaml`)：Python 3.11-slim + OpenCV deps，端口 8999，host 网络模式
- [x] 单元测试套件 `tests/unit/`：97 cases，覆盖 motion / prefilter / pipeline / config / health / pause-resume / sinks
- [x] 集成测试套件 `tests/integration/`：mock webhook server、容器健康、源生命周期、动作到 webhook 投递
- [x] 多场景测试脚本 `scripts/test-videostream-analytics.sh`：unit / integration / multi-video 三层测试

### Done (WW25 cont.)

- [x] `BaseMonitor` ABC 抽象，准备多源类型扩展
- [x] `ContinuousRecorder` (`stream_monitor/continuous_recorder.py`)：固定 interval (60s) MP4 录制、retention 管理
- [x] motion `MotionState` + ROI 支持 (`stream_monitor/pipeline/{motion_state.py,roi.py}`)
- [x] 共享 utils：`shared/{logger.py,time_utils.py,webhook_client.py}`
- [x] 重构包结构 + `EventSink` 拆分到独立 `sinks/` 模块

### Done (WW26)

- [x] YOLO 预过滤模块 `stream_monitor/pipeline/prefilter_yolo.py`：OpenVINO 推理、target_classes 过滤、置信度阈值、NPU 优先
- [x] config 中开启 prefilter 默认值（NPU + yolo11s FP16）
- [x] NPU 设备模型 cache，避免重复编译
- [x] Prefilter 评估工具 `tools/`：`eval_prefilter_from_webhook.py` (recall/precision)、`run_eval.sh` (4 场景一键跑)、`render_eval_timeline.py` (ASCII 时间线)
- [x] Prefilter 配置契约测试 `tests/unit/test_prefilter_config_contract.py` (9 cases)：source override 全量替换、坏 model_path 优雅降级
- [x] phase2 dashboard baseline 验证：child 100/100、elder_day1+2 100/100、fridge 75（边界对齐，--tolerance 2.0 后 100）

### In progress (WW27)

- [ ] Dynamic video source management：register/unregister/pause/resume/pipeline hot-update API 已实现并联通 `SourceManager`，剩余 health monitoring + recovery_strategy (retry/pause/remove) 自动恢复路径联调
- [ ] `recovery_strategy: remove` 自动注销 + unhealthy 事件投递（`sources/{id}` 状态变更广播）

### Next Steps (WW28+)

- [ ] WW28–WW29：Use Case Adapter — register new use case 主流程（schema 校验、prompt autogen 入口、持久化到配置）
- [ ] WW30：Use Case Adapter wrapper（统一对外 API，对接 MCP Server `use_case_register` tool）
- [ ] WW31：Customize post-proc — summary parser + rule engine override 路径
- [ ] 与 Jiaojiao 联调 MCP Server 的 events webhook → pending task → VLM → rule eval → alert 链路

