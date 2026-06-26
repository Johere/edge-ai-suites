# DB Schema Design — SmartBuilding Video Toolkit

本文档对应 [packages/db/src/database.ts](../../packages/db/src/database.ts) 中 `MIGRATIONS` 的实际定义，字段释义按当前实现描述。运行时 DB 文件位于 `$SMARTBUILDING_DATA_DIR/smartbuilding.db`（默认 `~/.mcp-smartbuilding/smartbuilding.db`），使用 WAL 模式，开启 `foreign_keys`。

---

## 更新历史

| 版本 | 日期 | 更新人 | Commit | 说明 |
|------|------|--------|--------|------|
| v0.2 | 2026-06-26 | Lin, Jiaojiao | [`5396b66`](https://github.com/) — "Take code reviews and fix: MCP tools & rule-engine" | 与当前 `MIGRATIONS` 完全对齐：移除 `monitor_state` 表（运行时状态走 `monitors.status`）；移除 `alerts.severity` / `alerts.alert_type` 列（属用户自定义字段，挪到 `video_summary_tasks` 扩展列）；新增 `monitors` / `plans` 表的字段释义；补充扩展列动态写入机制说明 |
| v0.1 | — | Lin, Jiaojiao | — | 初版表结构设计（含 `monitor_state`、`alerts.severity` / `alerts.alert_type`） |

---

## 目录

- [1. 设计原则](#1-设计原则)
- [2. 表结构总览](#2-表结构总览)
- [3. 固定表定义](#3-固定表定义)
  - [3.1 `monitors` — 已注册的 monitor 实例](#31-monitors--已注册的-monitor-实例)
  - [3.2 `events` — 流处理触发事件](#32-events--流处理触发事件)
  - [3.3 `recordings` — 录制段文件元数据](#33-recordings--录制段文件元数据)
  - [3.4 `video_summary_tasks` — multilevel-video-understanding 分析任务（含扩展列）](#34-video_summary_tasks--multilevel-video-understanding-分析任务含扩展列)
  - [3.5 `alerts` — 告警（最小固定结构，无扩展列）](#35-alerts--告警最小固定结构无扩展列)
  - [3.6 `reports` — 定期报告](#36-reports--定期报告)
  - [3.7 `plans` — per-monitor 任意 JSON 计划](#37-plans--per-monitor-任意-json-计划)
- [4. 扩展机制（仅 `video_summary_tasks` 支持）](#4-扩展机制仅-video_summary_tasks-支持)
- [5. Schema 变更策略](#5-schema-变更策略)
- [6. Schema 与 LOCAL_PROMPT 联动校验](#6-schema-与-local_prompt-联动校验)
- [7. 数据流全景](#7-数据流全景)
- [8. 索引一览](#8-索引一览)
- [9. 关键文件索引](#9-关键文件索引)

---

## 1. 设计原则

- **固定表 + 用户声明的扩展列**：核心表结构跨 use case 通用，**只有 `video_summary_tasks` 允许通过 schema YAML 声明扩展字段**，其余表保持固定结构
- **`alerts` 表 use-case-agnostic**：不含任何用户自定义列，所有 use-case 语义字段（severity / event / desc / confidence …）都落在 `video_summary_tasks` 的扩展列里，alerts 表通过 `task_id` JOIN 追溯
- **写入路径单点**：videostream-analytics 微服务**不直接写 DB**，所有写入都由 MCP server 完成（webhook 接收事件元数据 → 写库；video-worker 完成 summary → 写库；rule-engine 命中规则 → 写 alerts）
- **schema 与 prompt 联动**：用户在 `config.yaml > schema.video_summary_tasks.extensions` 声明的 `required:true` 字段名，必须出现在 multilevel-video-understanding 的 LOCAL_PROMPT 里；由 `smartbuilding_use_case_validate` 工具校验
- **大小写不敏感**：summary-parser 在 schema 字段名 ↔ multilevel-video-understanding 输出 key 之间做大小写不敏感匹配

---

## 2. 表结构总览

| 表 | 类型 | 写入方 | 用途 |
|---|---|---|---|
| `monitors` | 固定 | `monitor_ctl` / `monitors_compose` / `autoRegisterMonitors` | 已注册的 monitor 实例及其使用的 use_case |
| `events` | 固定 | MCP server EventsEndpoint（webhook） | 视频流处理触发事件（motion / static） |
| `recordings` | 固定 | MCP server EventsEndpoint（webhook） | 录制段文件元数据 |
| `video_summary_tasks` | 固定 + **扩展列** | MCP server video-worker | multilevel-video-understanding 分析任务 + 解析后的 schema 字段 |
| `alerts` | 固定 | MCP server rule-engine | 告警记录（最小固定结构） |
| `reports` | 固定 | `generate_report` tool | 日 / 周 / 月报 |
| `plans` | 固定 | `plan_ctl` tool | per-monitor 任意 JSON 计划（按 name 唯一） |

---

## 3. 固定表定义

### 3.1 `monitors` — 已注册的 monitor 实例

```sql
CREATE TABLE IF NOT EXISTS monitors (
  id                  TEXT PRIMARY KEY,
  name                TEXT NOT NULL,
  source_url          TEXT NOT NULL,
  status              TEXT NOT NULL DEFAULT 'offline',
  use_case            TEXT NOT NULL,
  video_summary_task  TEXT NOT NULL,
  created_at          TEXT DEFAULT (datetime('now'))
);
```

| 字段 | 类型 | 释义 |
|------|------|------|
| `id` | TEXT PK | monitor 标识（如 `cam_fridge`、`cam_child`）；同时也是 segments 目录名 |
| `name` | TEXT | 人类可读名称，UI 展示用 |
| `source_url` | TEXT | 任意 videostream-analytics 支持的协议地址（RTSP / 文件 / HTTP 流），不再限定 rtsp:// |
| `status` | TEXT | `online` / `offline` / `error`；启动时 reconcile 会把残留 `online` 重置为 `offline` |
| `use_case` | TEXT | 引用 `config.yaml > use_case_dict` 的 key（如 `fridge` / `child_safety` / `elder_wakeup`） |
| `video_summary_task` | TEXT | 写入时从 `useCaseDict[use_case].video_summary_task` 派生而来，缓存进表方便 video-worker 直接读取，无需每次回查 useCaseDict |
| `created_at` | TEXT | UTC 时间（注意：此表用的是 `datetime('now')`，无 `localtime` 修饰） |

**写入路径**：
- `smartbuilding_monitor_ctl action=register_source` — 单次手动注册
- `smartbuilding_monitors_compose action=up` / `autoRegisterMonitors` — 启动时批量从 `monitors.yaml` 创建

---

### 3.2 `events` — 流处理触发事件

```sql
CREATE TABLE IF NOT EXISTS events (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  monitor_id            TEXT NOT NULL,
  motion_type           TEXT NOT NULL,
  start_time            TEXT NOT NULL,
  end_time              TEXT,
  duration_seconds      REAL,
  event_file_path       TEXT,
  prefilter_passed      INTEGER,
  prefilter_classes     TEXT,
  prefilter_confidence  REAL,
  trajectory_region     TEXT,
  created_at            TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_events_monitor_time ON events(monitor_id, start_time);
```

| 字段 | 类型 | 释义 |
|------|------|------|
| `id` | INTEGER PK | 自增主键，被 `video_summary_tasks.event_id` / `alerts.event_id` 引用 |
| `monitor_id` | TEXT | 关联 `monitors.id`（运行时未加 FK 约束，靠应用保证） |
| `motion_type` | TEXT | `motion` / `static`。注意：这是**运动状态**层级，**不是** use-case 语义事件（如 `fall`/`escape`），后者写在 `video_summary_tasks.event` 扩展列 |
| `start_time` | TEXT | webhook 上报的事件起始时刻字符串，原样存储 |
| `end_time` | TEXT? | 事件结束时刻（可空，static 事件可能无明确终点） |
| `duration_seconds` | REAL? | 事件时长 |
| `event_file_path` | TEXT? | 原始 motion segment 视频文件路径（`*.mp4`），仅 motion 类型有 |
| `prefilter_passed` | INTEGER? | 0/1；YOLO/NPU 类预过滤结果，可空（未配置 prefilter 的 monitor 不写入） |
| `prefilter_classes` | TEXT? | JSON array 字符串，如 `["person","knife"]` |
| `prefilter_confidence` | REAL? | 预过滤最高置信度 |
| `trajectory_region` | TEXT? | 归一化轨迹 bbox，格式 `"x0,y0,x1,y1"` |
| `created_at` | TEXT | 默认本地时间 |

**写入路径**：`EventsEndpoint.handleEvent()` 处理 `POST /events`，type 为 `motion` 或 `static` 时写入。

---

### 3.3 `recordings` — 录制段文件元数据

```sql
CREATE TABLE IF NOT EXISTS recordings (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  monitor_id        TEXT NOT NULL,
  file_path         TEXT NOT NULL,
  start_time        TEXT NOT NULL,
  end_time          TEXT NOT NULL,
  duration_seconds  REAL,
  file_size_bytes   INTEGER,
  created_at        TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_recordings_monitor_time ON recordings(monitor_id, start_time, end_time);
```

| 字段 | 类型 | 释义 |
|------|------|------|
| `id` | INTEGER PK | 自增 |
| `monitor_id` | TEXT | 关联 `monitors.id` |
| `file_path` | TEXT | 录制文件的绝对路径（落在 `$SMARTBUILDING_DATA_DIR/segments/<monitor_id>/recordings/<YYYY-MM-DD>/...`） |
| `start_time` | TEXT | 录制起始时刻 |
| `end_time` | TEXT | 录制结束时刻 |
| `duration_seconds` | REAL? | 时长 |
| `file_size_bytes` | INTEGER? | 文件大小 |
| `created_at` | TEXT | 默认本地时间 |

**写入路径**：`EventsEndpoint.handleEvent()` 中 type 为 `recording` 时写入；与 `events` 表分离（一段录制不一定对应一次 motion event）。

---

### 3.4 `video_summary_tasks` — multilevel-video-understanding 分析任务（含扩展列）

```sql
CREATE TABLE IF NOT EXISTS video_summary_tasks (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  monitor_id          TEXT NOT NULL,
  event_id            INTEGER REFERENCES events(id),
  clip_start_time     TEXT,
  clip_end_time       TEXT,
  clip_duration       REAL,
  summary_clip_input  TEXT,
  summary_text        TEXT,
  status              TEXT NOT NULL DEFAULT 'pending',
  error_message       TEXT,
  latency_seconds     REAL,
  prompt_tokens       INTEGER,
  image_tokens        INTEGER,
  completion_tokens   INTEGER,
  started_at          TEXT,
  completed_at        TEXT,
  created_at          TEXT DEFAULT (datetime('now', 'localtime'))
  -- user-declared extension columns appended here at runtime via ALTER TABLE
);
CREATE INDEX IF NOT EXISTS idx_vst_status ON video_summary_tasks(status);
CREATE INDEX IF NOT EXISTS idx_vst_monitor ON video_summary_tasks(monitor_id);
CREATE INDEX IF NOT EXISTS idx_vst_event ON video_summary_tasks(event_id);
```

| 字段 | 类型 | 释义 |
|------|------|------|
| `id` | INTEGER PK | 自增；被 `alerts.task_id` 引用 |
| `monitor_id` | TEXT | 关联 `monitors.id` |
| `event_id` | INTEGER? FK→events.id | 触发本次 summary 任务的 motion event；无 event 的任务（如手动触发）可空 |
| `clip_start_time` | TEXT? | 待 summary 的视频片段起始时刻（人类可读字符串，主要用于 SRT 报告生成对齐） |
| `clip_end_time` | TEXT? | 片段结束时刻 |
| `clip_duration` | REAL? | 片段时长（秒） |
| `summary_clip_input` | TEXT? | 实际送给 multilevel-video-understanding 的视频文件路径（通常是 `_input.mp4`，可能经过裁剪/降采样） |
| `summary_text` | TEXT? | multilevel-video-understanding 返回的完整文本（schema-aware parser 读它，提取扩展列） |
| `status` | TEXT | `pending` / `processing` / `completed` / `failed` / `ignored`（prefilter_passed=0 时为 `ignored`，video-worker 跳过 multilevel-video-understanding 调用） |
| `error_message` | TEXT? | 失败时的错误描述 |
| `latency_seconds` | REAL? | multilevel-video-understanding 调用耗时 |
| `prompt_tokens` / `image_tokens` / `completion_tokens` | INTEGER? | LLM 用量统计 |
| `started_at` | TEXT? | 进入 `processing` 状态的时刻（注意：当前 `updateTaskStatus` 在 pending→processing 转换时**未写** `started_at`，留作未来扩展） |
| `completed_at` | TEXT? | 进入 `completed`/`failed` 状态的时刻（由 `updateTaskStatus` 写入 `datetime('now')`，UTC） |
| `created_at` | TEXT | 默认本地时间 |
| **扩展列** | 用户声明 | 由 `SchemaManager.applySchema()` 启动时 `ALTER TABLE ADD COLUMN` 添加；由 `updateTaskStatus(..., extensionFields)` 写入 |

**扩展列写入机制**（[database.ts:521-572](../../packages/db/src/database.ts)）：
```typescript
// PRAGMA table_info(video_summary_tasks) → 当前真实列名集合
// 对 extensionFields 中的每个 key：
//   1. 通过正则校验是合法 SQL identifier
//   2. 通过 PRAGMA 校验列确实存在
//   3. 加入 SET 子句一并 UPDATE
// 不存在的列直接跳过（防止 schema 未应用就 SQL 错误）
```

**典型扩展列**（来自 `config.yaml.example`）：
- `event` TEXT — use-case 语义事件类型（`jumping` / `fall` / `wakeup` …）
- `severity` TEXT — `critical` / `warn` / `info`
- `desc` TEXT — multilevel-video-understanding 输出的一句话描述
- `confidence` REAL — multilevel-video-understanding 自报置信度（optional）

---

### 3.5 `alerts` — 告警（最小固定结构，无扩展列）

```sql
CREATE TABLE IF NOT EXISTS alerts (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  monitor_id   TEXT NOT NULL,
  task_id      INTEGER REFERENCES video_summary_tasks(id),
  event_id     INTEGER REFERENCES events(id),
  use_case     TEXT NOT NULL DEFAULT '',
  description  TEXT,
  created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
  ack_at       TEXT,
  ack_by       TEXT,
  FOREIGN KEY (monitor_id) REFERENCES monitors(id)
);
CREATE INDEX IF NOT EXISTS idx_alerts_monitor_time ON alerts(monitor_id, created_at);
CREATE INDEX IF NOT EXISTS idx_alerts_ack ON alerts(ack_at);
CREATE INDEX IF NOT EXISTS idx_alerts_task ON alerts(task_id);
CREATE INDEX IF NOT EXISTS idx_alerts_event ON alerts(event_id);
```

| 字段 | 类型 | 释义 |
|------|------|------|
| `id` | INTEGER PK | 自增 |
| `monitor_id` | TEXT FK→monitors.id | 告警归属 monitor |
| `task_id` | INTEGER? FK→video_summary_tasks.id | 告警的源 task；通过此 JOIN 取扩展列（severity / event / desc / ...） |
| `event_id` | INTEGER? FK→events.id | 告警的源 motion event |
| `use_case` | TEXT | 写入时从 `monitors.use_case` 派生，便于按 use_case 直接过滤而无需 JOIN |
| `description` | TEXT? | 人类可读告警描述（rule engine 的 `alertMessage` 直落本列） |
| `created_at` | TEXT | 告警创建时刻（本地时间） |
| `ack_at` | TEXT? | 确认时刻；`NULL` 表示未确认 |
| `ack_by` | TEXT? | 确认人标识 |

**为什么 alerts 没有扩展列**：

- `severity` / `event` / `alert_type` 这些字段是**用户自定义的**——不同 use case 的告警字段集完全不同（fridge use case 可能根本没有 severity，elder_wakeup 可能有 `wakeup_time`）
- alerts 表保持**最小固定结构**就能跨所有 use case 通用，新 use case 加列时只需在 `video_summary_tasks` 上扩展，不动 alerts
- 查询时通过 `alerts.task_id → video_summary_tasks.id` JOIN 拿到所有用户字段（见 `queryAlertsWithDetails` 实现）

**写入路径**：`task-poller.ts` 在 task 完成后调 `evaluateWithOverride()`，rule engine 返回 `shouldAlert: true` 时调 `db.createAlert()`。

---

### 3.6 `reports` — 定期报告

```sql
CREATE TABLE IF NOT EXISTS reports (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  monitor_id        TEXT NOT NULL,
  use_case          TEXT NOT NULL DEFAULT '',
  period_start      TEXT NOT NULL,
  period_end        TEXT NOT NULL,
  report_text       TEXT,
  event_count       INTEGER,
  motion_count      INTEGER,
  latency_seconds   REAL,
  prompt_tokens     INTEGER,
  image_tokens      INTEGER,
  completion_tokens INTEGER,
  status            TEXT DEFAULT 'pending',
  report_type       TEXT DEFAULT 'raw',
  created_at        TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_reports_monitor_period ON reports(monitor_id, period_start);
```

| 字段 | 类型 | 释义 |
|------|------|------|
| `id` | INTEGER PK | 自增 |
| `monitor_id` | TEXT | 关联 `monitors.id` |
| `use_case` | TEXT | 写入时从 `monitors.use_case` 派生 |
| `period_start` / `period_end` | TEXT | 报告覆盖的时间区间；日报为 1 天、周报为 7 天，由 `generate_report` 调用方决定 |
| `report_text` | TEXT? | multilevel-video-understanding caption-only 模式返回的报告文本（SRT 拼接后送进去 summarize） |
| `event_count` | INTEGER? | 报告覆盖区间内的 events 总数 |
| `motion_count` | INTEGER? | 其中 `motion_type='motion'` 的数量 |
| `latency_seconds` / `*_tokens` | — | summary 模型用量 |
| `status` | TEXT | `pending` / `completed` / `failed` |
| `report_type` | TEXT | `raw`（原始生成）/ `polished`（被 agent 二次润色） |
| `created_at` | TEXT | 创建时刻（本地时间） |

**写入路径**：`generate_report` MCP tool；data_source / filter / default_type 默认从 `config.useCaseDict[use_case].reports` 派生，tool 参数可覆盖。

---

### 3.7 `plans` — per-monitor 任意 JSON 计划

```sql
CREATE TABLE IF NOT EXISTS plans (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  monitor_id  TEXT NOT NULL,
  name        TEXT NOT NULL,
  plan_date   TEXT,
  plan_json   TEXT NOT NULL,
  active      INTEGER NOT NULL DEFAULT 1,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(monitor_id, name)
);
CREATE INDEX IF NOT EXISTS idx_plans_monitor ON plans(monitor_id);
```

| 字段 | 类型 | 释义 |
|------|------|------|
| `id` | INTEGER PK | 自增 |
| `monitor_id` | TEXT | 关联 `monitors.id` |
| `name` | TEXT | plan 名称；与 `monitor_id` 组成 UNIQUE 唯一键，重名 upsert |
| `plan_date` | TEXT? | 计划日期（可空，按需使用，例如冰箱日报对应日期） |
| `plan_json` | TEXT | 任意 JSON payload，由调用方序列化；MCP server 不解析其结构 |
| `active` | INTEGER | 1=有效；删除时设为 0（**软删除**，调用 `deletePlanByName` 实际只置 0，不 DELETE 物理行） |
| `created_at` | TEXT | 首次插入时刻；upsert 时不更新此字段 |

**写入路径**：`plan_ctl` MCP tool（`list` / `upsert` / `delete`）。

> **设计取舍**：`plans` 是有意通用的——既可以放冰箱每日采购清单，也可以放 elder_wakeup 的每日起床基线，甚至可以放 child_safety 的"今天父母外出"标记。`plan_json` 字段不限定结构，由调用方约定。

---

## 4. 扩展机制（仅 `video_summary_tasks` 支持）

### 4.1 用户在 `config.yaml` 声明 schema

```yaml
schema:
  video_summary_tasks:
    extensions:
      - { name: "event",      type: "text", required: true }
      - { name: "severity",   type: "text", required: true }
      - { name: "desc",       type: "text", required: true }
      - { name: "confidence", type: "real", required: false }
  custom_tables: []
```

类型 enum（`SchemaExtension.type`）：`text` / `integer` / `real`。`required` 决定 `parseSummaryFields` 是否在字段缺失时打 warn。

### 4.2 启动时 `ALTER TABLE`

[SchemaManager.applySchema()](../../packages/db/src/schema-manager.ts) 在 MCP server 启动时调用：

1. `PRAGMA table_info(video_summary_tasks)` 拿当前列
2. 对每个 extension：
   - 列不存在 → `ALTER TABLE video_summary_tasks ADD COLUMN <name> <type>`
   - 列已存在且类型匹配 → 跳过
   - 列已存在但类型不同 → 收集 warning，不自动改类型（需要人工迁移）

### 4.3 解析时写入扩展列

[task-poller.ts](../../packages/mcp-server/src/video-worker/task-poller.ts) → [parseSummaryFields()](../../packages/rule-engine/src/summary-parser.ts) → [updateTaskStatus(..., extensionFields)](../../packages/db/src/database.ts)：

```
multilevel-video-understanding 输出: schema 声明:                  落库:
  EVENT: jumping                      extensions:                    UPDATE video_summary_tasks SET
  SEVERITY: warn                        - event (required)            summary_text = "EVENT: ...",
  DESC: 儿童从沙发跳下                  - severity (required)         event = "jumping",
  TIME_OF_DAY: morning  ← schema 没声明 - desc (required)             severity = "warn",
                                        - confidence (optional)       desc = "儿童从沙发跳下"
                                                                      -- TIME_OF_DAY 被丢弃（schema 无）
                                                                      -- confidence 缺失 → 不写
                                                                      WHERE id = ?
```

### 4.4 `alerts` 不接受扩展

`schema.alerts.extensions` 在 [SchemaManager](../../packages/db/src/schema-manager.ts) 中虽然接口仍存在，但**`config.yaml.example` 中已不再展示该块**——alerts 表保持最小固定结构是约定。如果用户硬塞 `schema.alerts.extensions`，`applySchema()` 仍会执行 ALTER TABLE，但下游代码不会读这些列；强烈建议把 use-case 字段放在 `video_summary_tasks` 一侧。

### 4.5 `custom_tables`（自定义表，留作扩展点）

```yaml
schema:
  custom_tables:
    - name: medications
      columns:
        - { name: monitor_id,  type: text }
        - { name: schedule,    type: text }
```

[`SchemaManager.createCustomTable`](../../packages/db/src/schema-manager.ts) 实现了 `CREATE TABLE IF NOT EXISTS <name> (id INTEGER PRIMARY KEY AUTOINCREMENT, ...)`，但**当前没有内置 tool 读写这类表**，需要通过 `smartbuilding_video_db` 工具的 raw SQL 接口操作。

---

## 5. Schema 变更策略

| 变更 | 处理 | 风险 |
|------|------|------|
| 新增扩展列 | 启动时 `ALTER TABLE ADD COLUMN`，历史行该列为 NULL | 无 |
| 修改扩展列类型 | 收集 warning，**不自动改**，需手工迁移 | 数据一致性自己保 |
| 从 schema YAML 中删除扩展列 | 不做任何事；旧列保留，停止写入 | 历史数据保留 |
| 新增 custom_tables | `CREATE TABLE IF NOT EXISTS` | 无 |
| 删除 custom_tables | 不自动 DROP；需通过 `smartbuilding_video_db` 手动执行 | DROP 数据不可恢复 |

用户改 schema 后**重启 MCP server** 生效。

---

## 6. Schema 与 LOCAL_PROMPT 联动校验

`schema.video_summary_tasks.extensions` 中 `required:true` 的字段名，必须出现在 multilevel-video-understanding 的 LOCAL_PROMPT 中（大小写不敏感子串匹配），否则 multilevel-video-understanding 的输出里不会有这些 key，落库为 NULL。

校验由 `smartbuilding_use_case_validate` 工具统一负责，详见 [schema-usecase-parser-alerts-pipeline.md §4](./schema-usecase-parser-alerts-pipeline.md#4-mcp-tool-use_case_validateuse-case--video-summary-服务一站式校验)。

两种触发场景：
- **被动**：`monitor_ctl register_source` 注册前自动调用，失败拒绝注册
- **主动**：agent / CI 可以独立调用做 dry-check

---

## 7. 数据流全景

```
videostream-analytics 微服务 (:8999)
  │
  │ POST /events  (webhook payload)
  ▼
EventsEndpoint (:3101 in MCP server)
  ├─ type=motion    → INSERT events + INSERT video_summary_tasks(status=pending)
  ├─ type=static    → INSERT events
  └─ type=recording → INSERT recordings
  
video-worker (in MCP server)
  │
  │ poll: SELECT * FROM video_summary_tasks WHERE status='pending'
  ▼
multilevel-video-understanding (:8192)
  │
  │ 返回 summary_text
  ▼
parseSummaryFields(text, schema.extensions)
  │
  │ 解析出 { event, severity, desc, confidence, ... }
  ▼
updateTaskStatus(taskId, "completed", summaryText, meta, extensionFields)
  │  (PRAGMA-filtered 动态 UPDATE，写 summary_text + 扩展列)
  ▼
evaluateWithOverride(ctx, useCaseDict[use_case].evaluate_rules_path)
  │  (default 规则 or Python override)
  │
  │ shouldAlert=true?
  ▼
createAlert({ monitorId, taskId, eventId, useCase, description })
  │
  ▼
MCP resource subscription → notifications/resources/updated  (WW27 待实现)
  │
  ▼
订阅方（OpenClaw / Claude Desktop / agent）
```

---

## 8. 索引一览

| 索引 | 表 | 列 | 用途 |
|------|----|----|------|
| `idx_events_monitor_time` | events | (monitor_id, start_time) | 按 monitor 拉时间窗事件（用于报告生成） |
| `idx_recordings_monitor_time` | recordings | (monitor_id, start_time, end_time) | 录制段时间窗检索 |
| `idx_vst_status` | video_summary_tasks | (status) | video-worker poll pending |
| `idx_vst_monitor` | video_summary_tasks | (monitor_id) | per-monitor 任务列表 |
| `idx_vst_event` | video_summary_tasks | (event_id) | 反向找 event 对应的 task |
| `idx_alerts_monitor_time` | alerts | (monitor_id, created_at) | alert_query 主索引 |
| `idx_alerts_ack` | alerts | (ack_at) | 未确认告警快速过滤 |
| `idx_alerts_task` | alerts | (task_id) | JOIN 拿扩展列 |
| `idx_alerts_event` | alerts | (event_id) | JOIN 拿 event |
| `idx_reports_monitor_period` | reports | (monitor_id, period_start) | 按 monitor + 时间区间查报告 |
| `idx_plans_monitor` | plans | (monitor_id) | per-monitor 计划列表 |

---

## 9. 关键文件索引

| 文件 | 职责 |
|------|------|
| [packages/db/src/database.ts](../../packages/db/src/database.ts) | `MIGRATIONS` SQL + 所有 CRUD（`updateTaskStatus` 含动态扩展列写入） |
| [packages/db/src/schema-manager.ts](../../packages/db/src/schema-manager.ts) | `applySchema()` 启动时 ALTER TABLE；`validatePromptSchema()` prompt↔schema 校验 |
| [packages/db/src/types.ts](../../packages/db/src/types.ts) | TS 接口（`Monitor` / `Event` / `Recording` / `VideoSummaryTask` / `Alert` / `Report` / `AlertWithTask`） |
| [config.yaml.example](../../config.yaml.example) | `schema` + `use_case_dict` 示例 |
| [docs/implements/schema-usecase-parser-alerts-pipeline.md](./schema-usecase-parser-alerts-pipeline.md) | schema → use_case → parser → alerts 端到端链路 |
