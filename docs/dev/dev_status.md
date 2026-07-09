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
| 1 | MCP Server structure dev | 2W | WW24–WW25 | Done |
| 2 | TypeScript library (tools) | 1W | WW26 | Done |
| 3 | MCP resource subscription | 1W | WW27 | In progress (alert subscription pending) |
| 4 | Support DB schema customization | 1W | WW28 | Done (delivered together with WW26 use_case_dict refactor) |

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

### Done (WW26)

**Tools & Pipeline 重构 — 对齐 finalized design + use-case-agnostic 原则**

- [x] MCP tools 对照 finalized design 重写（alert_query / plan_ctl / scene_query / generate_report / monitor_ctl / monitors_compose / video_db / use_case_validate）
  - `alert_query`：action 枚举（latest/by_date/ack/stats），LEFT JOIN 返回 task+event 详情，stats 聚合避免拉全表
  - `plan_ctl`：per-monitor 任意 JSON plan（list/upsert/delete），按 name 唯一
  - `scene_query`：vllm-serving-ipex 集成，ffmpeg `scale` resize（无额外依赖），帧归档至 `queries/<date>/`
  - `generate_report`：SRT 时间线构建 + multilevel-video-understanding caption-only；dataSource / filter / defaultType 从 `useCaseDict.reports` 派生
  - `monitor_ctl`：原子化三层协调（DB + videostream-analytics + video-worker），8 场景幂等矩阵；register_source 内联调 use_case_validate 做前置校验
  - `monitors_compose`：docker-compose 风格（validate/up/down/restart/ps），管理一份 monitors.yaml；启动时 autoRegisterMonitors 走同一逻辑
  - `use_case_validate`：三步检查（use_case 存在 / summary service + task 存在 / prompt ↔ schema 一致性）；既被 register_source 前置调用，也支持独立 dry-check
- [x] **rule-engine 集成 task-poller**：task 完成后自动 `parseSummaryFields` → `evaluateWithOverride`，shouldAlert → `db.createAlert`
- [x] **schema-aware summary parser**：parser 只解析 `config.schema.video_summary_tasks.extensions` 声明的字段，required 缺失 → logger.warn；解析结果直接落 video_summary_tasks 扩展列
- [x] **alerts 表瘦身**：删除 `severity` / `alert_type` 列（属于扩展字段，alerts 表保持 use-case-agnostic 最小固定结构）；severity 通过 task_id JOIN video_summary_tasks 追溯
- [x] **DB updateTaskStatus 写扩展列**：PRAGMA table_info 过滤 + SQL identifier 校验，动态 UPDATE 实际存在的扩展列
- [x] **SchemaManager.validatePromptSchema 复用**：use_case_validate 真正调用此静态方法，不再各自手写校验

**配置文件重构 — 职责分离 + use_case 复用**

- [x] `config.yaml`：新增顶层 `use_case_dict`（video_summary_task / evaluate_rules_path / reports 集中声明），一个 use_case 可被多 monitor 引用
- [x] `monitors.yaml`：独立配置文件，通过 `--monitors <path>` CLI 加载；monitor 用 `use_case` 字段引用 use_case_dict key
- [x] 启动时引用一致性校验：monitor.use_case 必须存在于 use_case_dict，否则启动报错退出
- [x] use_case agnostic 收尾：`rtsp_url` → `source_url`（任意 analytics 支持协议）、`use_case_id` / `use_case_name` 统一为 `use_case`

**运行时基础设施**

- [x] 自动注册管线：`autoRegisterMonitors` 在 `reconcileOnStartup` 后自动执行；videostream-analytics 不可达只 warn 不阻塞 server 启动
- [x] `--config` / `--monitors` CLI 参数解耦；`SMARTBUILDING_DATA_DIR` 环境变量统一数据根目录
- [x] 数据目录约定：`<data_dir>/{smartbuilding.db, segments/<id>/{latest.jpg,recordings/<date>/,motion_events/<date>/,queries/<date>/}, logs/{reports,monitors/<id>/<date>.log}}`
- [x] `monitor_ctl register_source` payload 加 `data_dir` 字段（`[TODO: analytics-side]` 等 analytics 端实现）
- [x] Per-monitor 日志：`logger.ts` 加 `monitorLogger(id, dir, maxFileMb)` 工厂，按天 rotate + 单文件大小防护
- [x] 自动清理：`storage-cleaner.ts` 启动 + 每 24h 清理过期日志和 segments 子目录（按 `logging.retention_days` / `storage.retention_days`）
- [x] 删除 EventsEndpoint 的 onEvent 通知路径（噪音大，alert subscription 应走 task-poller onAlert）

**Schema/DB 完整对齐 db-schema-design.md**

- [x] 加 `events` + `recordings` 表（webhook 写入）
- [x] `video_summary_tasks` 补全所有字段（`event_id`, `clip_*`, `summary_clip_input`, `summary_text`, latency, tokens）
- [x] `reports` 表加 use_case / motion_count / image_tokens 等完整字段
- [x] `monitor_state` 加 use_case 列
- [x] migrateSchema 函数（一次性已对齐，后续按需新增）

**Docs**

- [x] `docs/implements/tools_list.md` — 全 8 工具清单（参数、actions、返回值）
- [x] `docs/implements/monitor-ctl-analytics-integration.md` — analytics 服务端集成契约（含 `data_dir` 字段 TODO）
- [x] `docs/implements/schema-usecase-parser-alerts-pipeline.md` — schema → use_case → parser → alerts → DB 端到端链路说明

### Next Steps (WW27)

**MCP resource subscription — alert 推送**

- [x] `resources.ts` 暴露 `smartbuilding://monitor/<id>/alerts` 资源（+ `?since` 游标增量读，返回 `latestId`）
- [x] `index.ts` 的 `onAlert` 实际推送 `notifications/resources/updated`（stateful HTTP + `McpSubscriberRegistry` 广播；原只 logger.debug）
- [x] 联调 resource subscribe 流程（curl smoke + 对真实运行实例 subscribe → 自然触发 3 条 alert → SSE 收到 → `?since` 拉增量，全链路通过）

**Framework adapter SDK + OpenClaw 参考实现**（详见 [mcp_subscription_status.md](mcp_subscription_status.md) + [framework-adapters/](../framework-adapters/README.md)）

- [x] `packages/framework-adapter-sdk/` — 通用 MCP client SDK（subscribe / cursor dedup / per-monitor 保序 / 断连重连 / poll fallback）
- [x] `tests/framework-adapter-sdk/` — 7 个单测全绿（`npm run test:sdk`，跑真实 Streamable-HTTP mock server）
- [x] `packages/framework-adapter-sdk/examples/openclaw/` — 开箱即用 OpenClaw plugin（sink FS-append / channel deliver + install.sh + 硬拷贝 personas）
- [x] `docs/framework-adapters/*.md` — README / deployment / writing-a-new-framework-adapter / openclaw 四篇
- [ ] 端到端：install.sh 干净环境跑通 → openclaw.json 配路由 → 重启 gateway → 真实 alert 落到目标 session（待在实机验证）
- [ ] **运行时新增 monitor 的动态订阅（已知缺口，以后再做）**：adapter 的 `monitorIds` 是插件启动时从 openclaw.json `Object.keys(config.monitors)` 一次性读定的（[adapter.ts](../../packages/framework-adapter-sdk/src/adapter.ts) 构造函数 + `connect()` 只 subscribe 这批），无动态发现。用户通过 monitor compose（`applyMonitors`→`register_source`，[monitor-bootstrap.ts](../../packages/mcp-server/src/monitor-bootstrap.ts)）在运行时起的新 monitor **不会被自动订阅** —— MCP server 侧 `onAlert` 虽会 `findSubscribers(uri)` 广播，但 adapter 从没 subscribe 过新 uri，通知命中 `no subscribers, dropped`。当前解法：openclaw.json 加路由 + 重启 gateway。缺口有两半：(a) 订阅到新 monitor 的 alert；(b) 新 monitor 没有路由表条目→不知道投给谁（会 `no route` 丢弃）。推荐方案：adapter 订阅 `smartbuilding://monitors` 列表资源的变更 → 动态 `subscribeResource` + 一个按 useCase 的默认路由约定（需 SDK 加 `addMonitor()` + server 在 monitor 上线时对 `smartbuilding://monitors` 发 `resources/updated`）。

**Monitor ctl integration with videostream-analytics wrapper（与 Jie 联调）**

- [ ] 接口清单核对: docs/implements/monitor-ctl-analytics-integration.md
- [ ] 端到端集成测试：webhook → pending task → multilevel-video-understanding → rule eval (含 Python override) → alert → MCP notification

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
