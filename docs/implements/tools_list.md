# MCP Tools 清单

本文档列出 `smartbuilding-video` MCP Server 提供的所有工具，包括每个工具的功能说明、action 枚举、参数列表及返回值结构。

实现状态：✅ 已实现 / ⚠️ 部分实现（TODO 标注）/ ❌ 未实现

---

## 1. `smartbuilding_alert_query` ✅

**功能**：查询告警记录或确认告警。通过 `action` 参数切换模式。

**设计原则**：
- `alerts` 表中的每一条都是 rule engine 筛选后的重要告警，无需再按 severity/type 过滤
- `severity`、`event`、`desc` 等字段**不在 alerts 表存储**，通过 `task_id` JOIN `video_summary_tasks` 追溯（用户自定义扩展字段）
- `task_id` / `event_id` 外键可追溯完整事件上下文
- `stats` 模式直接 COUNT 聚合，避免拉取大数据量

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `monitor_id` | string | ✅ | Monitor ID |
| `action` | enum | ✅ | 见下表 |
| `limit` | number | — | 最大返回条数（默认 20，for `latest`） |
| `start_date` | string | — | YYYY-MM-DD，闭区间起始（`by_date` 必填；`stats` 可选） |
| `end_date` | string | — | YYYY-MM-DD，闭区间结束（`by_date` 必填；`stats` 可选）。`start_date == end_date` = 查当天 |
| `alert_id` | number | — | 要确认的告警 ID（for `ack`） |
| `ack_by` | string | — | 确认人（for `ack`） |

**Actions**：

| action | 功能 | 返回值 |
|--------|------|--------|
| `latest` | 返回最新 N 条告警（`limit` 控制数量，默认 20），每条 alert 通过 LEFT JOIN 携带关联的 task 和 event 详情 | `{ alerts: AlertWithTask[] }` |
| `by_date` | 按日期范围查询告警（`start_date` ~ `end_date`），同样携带 task/event 详情 | `{ alerts: AlertWithTask[] }` |
| `ack` | 确认指定告警，记录确认人（`alert_id` + `ack_by`） | `{ success: true, alert_id }` |
| `stats` | 返回告警统计：总数 + 未确认数，支持日期范围，不拉取完整记录 | `{ total, unacked }` |

**`AlertWithTask` 结构**（`latest` / `by_date` 返回的每条记录）：

```json
{
  "id": 123,
  "monitorId": "cam_child",
  "taskId": 456,
  "eventId": 789,
  "useCase": "child_safety",
  "alertType": "child_climbing",
  "description": "Child climbing bookshelf",
  "createdAt": "2026-06-24T10:30:00",
  "ackAt": null,
  "ackBy": null,
  "taskDetails": {
    "id": 456,
    "clipFilePath": "/segments/cam_child/clip_20260624_103000.mp4",
    "summaryText": "SEVERITY: critical\nEVENT: child_climbing\nDESC: Child climbing bookshelf",
    "status": "completed",
    "event": "child_climbing",
    "severity": "critical",
    "desc": "Child climbing bookshelf"
  },
  "eventDetails": {
    "id": 789,
    "motionType": "motion",
    "startTime": "2026-06-24T10:29:45",
    "endTime": "2026-06-24T10:30:15"
  }
}
```

`task.event` / `task.severity` / `task.desc` 是用户通过 schema 配置的扩展字段，字段名由用户定义。

---

## 2. `smartbuilding_plan_ctl` ✅

**功能**：管理 per-monitor plans（按日期的任意 JSON 记录）。rule engine 在触发前可先查询当日 plan，根据内容调整行为。Plan 内容结构由用户自定义，tool 不关心。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `monitor_id` | string | ✅ | Monitor ID |
| `action` | enum | ✅ | 见下表 |
| `name` | string | — | Plan 名称，在同一 monitor 内唯一（for `upsert` / `delete`） |
| `plan` | object | — | Plan 数据对象（for `upsert`，结构由用户自定义） |
| `plan_date` | string | — | 可选的 YYYY-MM-DD 提示，随 plan 存储但不作为主键 |
| `active_only` | boolean | — | 仅返回 active plans（默认 true，for `list`） |

**Actions**：

| action | 功能 | 返回值 |
|--------|------|--------|
| `list` | 列出指定 monitor 的所有 plans，每条含 `name`、`plan`、`plan_date`（默认只返回 active） | plan 记录数组 |
| `upsert` | 新增或更新指定名称的 plan（`name` 唯一，重复写则覆盖） | `{ success: true, name }` |
| `delete` | 按名称软删除 plan（标记 `active=0`，数据保留） | `{ success: true, name }` |

---

## 3. `smartbuilding_scene_query` ✅

**功能**：读取 monitor 数据目录中的 `latest.jpg`，调用 **vllm-serving-ipex**（`:41091`）进行实时场景分析。

**服务**：vllm-serving-ipex `/v1/chat/completions`（非 multilevel-video-understanding）

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `monitor_id` | string | ✅ | Monitor ID，帧路径固定为 `$SMARTBUILDING_DATA_DIR/segments/<monitor_id>/latest.jpg` |
| `prompt` | string | — | 覆盖 prompt（默认：1-2 句场景描述） |
| `vlm_url` | string | — | VLM base URL（默认来自 `config.vlmService.url`） |
| `model` | string | — | VLM model ID（默认来自 `config.vlmService.model`） |
| `max_edge_px` | number | — | 最长边 px 上限（默认来自 `config.vlmService.maxEdgePx`，全局默认 720） |

**返回值**：`{ scene: string }` — VLM 返回的场景描述（已去除 `<think>` 标签）

**帧处理**：用 ffmpeg `scale` filter resize（无额外依赖），resize 后的帧自动归档至 `$SMARTBUILDING_DATA_DIR/segments/<monitor_id>/queries/<date>/scene_<time>.jpg`

---

## 4. `smartbuilding_generate_report` ✅

**功能**：从 DB 查询数据，构建 SRT 时间线，调用 **multilevel-video-understanding**（`:8192`）caption-only 模式生成报告文本，写入 `reports` 表。

**框架无关设计**：通过 `data_source` + `filter` 参数指定数据源，无硬编码用例逻辑。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `monitor_id` | string | ✅ | Monitor ID |
| `type` | enum | — | `daily` \| `weekly` \| `monthly` \| `custom`（默认 `daily`） |
| `period_start` | string | — | 闭区间起始，`YYYY-MM-DD` 或 `YYYY-MM-DD HH:MM`（for `custom`） |
| `period_end` | string | — | 闭区间结束，`YYYY-MM-DD` 或 `YYYY-MM-DD HH:MM`（for `custom`）。支持半日报，如 `06:00` ~ `12:00` |
| `data_source` | enum | — | `events` \| `alerts` \| `tasks`（默认 `alerts`） |
| `filter` | object | — | key-value 过滤条件，作用于 data_source 表的列（包括用户自定义扩展列） |

**`type` 枚举**：

| type | 时间范围 | 备注 |
|------|----------|------|
| `daily` | 今日 | 默认值 |
| `weekly` | 过去 7 天 | |
| `monthly` | 过去 30 天 | |
| `custom` | `period_start` ~ `period_end` | 需额外提供两个日期参数 |

**返回值**：`{ periodStart, periodEnd, type, dataSource, eventCount, reportText, latencySeconds }`

**SRT 调试文件**：自动持久化至 `$SMARTBUILDING_DATA_DIR/logs/reports/<monitor_id>_<type>_<start>_<end>_<ts>.srt.txt`

---
<!-- TODO: half-job here -->
## 5. `smartbuilding_monitor_ctl` ✅

**功能**：管理 monitor 生命周期，操作两层：
1. DB：create / update / delete monitor 记录
2. videostream-analytics microservice（`:8999`）：RESTful source 管理

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `action` | enum | ✅ | 见下表 |
| `monitor_id` | string | — | Monitor ID（除 `list` 外均必填） |
| `source_url` | string | — | RTSP URL（for `register_source`，必须以 `rtsp://` 开头） |
| `name` | string | — | 显示名（for `register_source`） |
| `use_case_id` | string | — | 用例 ID（for `register_source`） |
| `video_summary_task` | string | — | multilevel-video-understanding 服务中注册的 task 名称（for `register_source`，必填）。per-monitor 配置，存入 DB，`generate_report` 时自动读取 |
| `pipeline_config` | object | — | Pipeline 配置（for `register_source`，默认启用 motion + recording） |
| `webhook_url` | string | — | 事件 Webhook URL（for `register_source`，默认 `http://localhost:3101/events`） |

**Actions**：

| action | 功能 | 返回值 |
|--------|------|--------|
| `list` | 列出所有已注册 monitors；尝试从 analytics 服务附加实时状态，analytics 不可达时静默忽略，只返回 DB 数据 | Monitor 数组 |
| `register_source` | 注册新 monitor：写入 DB + 调用 analytics `/register_source`（analytics 立即开始拉流和运动检测）+ 自动启动 video-worker task poller | `{ success, monitor_id }` |
| `unregister` | 注销 monitor：调用 analytics `DELETE /sources/{id}` + 停止 video-worker + 删除 DB 记录 | `{ success, monitor_id }` |
| `start` | 恢复推流并启动 video-worker：调用 analytics `/sources/{id}/resume` + 启动 task poller + 更新 DB status=online | `{ success, monitor_id, status }` |
| `stop` | 暂停推流并停止 video-worker：调用 analytics `/sources/{id}/pause` + 停止 task poller + 更新 DB status=offline | `{ success, monitor_id, status }` |
| `status` | 查询单个 monitor 状态：DB 记录 + analytics 实时状态（analytics 不可达时 analyticsStatus=null） | Monitor + `analyticsStatus` |

---

## 6. `smartbuilding_rule_eval` ✅

**功能**：手动触发规则评估。扫描近期已完成的 `video_summary_tasks`，从 `summary_text` 中提取 `SEVERITY` 字段，为 `critical` / `warn` 级别的任务创建告警记录。

**通用实现**：正则提取 `SEVERITY: critical|warn|info`，不硬编码用例逻辑。告警只存 `alert_type`（事件标识）和 `description`，severity 留在 `video_summary_tasks` 表，通过 `task_id` 外键追溯。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `monitor_id` | string | ✅ | Monitor ID |
| `since` | string | — | ISO 8601 时间戳（默认：过去 24 小时） |

**返回值**：`{ monitor_id, evaluated: number, triggered: number, alerts_created: number }`

---

## 7. `smartbuilding_video_db` ✅

**功能**：只读 SQL 查询，直接访问 monitor 数据库。仅允许 `SELECT` 语句。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | ✅ | SELECT SQL（非 SELECT 语句会被拒绝） |
| `params` | array | — | 位置参数（`?` 占位符对应值） |

**返回值**：查询结果数组

**安全限制**：`INSERT` / `UPDATE` / `DELETE` 等修改语句被拒绝，返回错误。

---

## 8. `smartbuilding_use_case_validate` ✅

**功能**：验证 video summary prompt 是否覆盖了 schema 中所有必需字段（大小写不敏感子串匹配）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `use_case_name` | string | ✅ | 用例标识符（仅用于标注，不影响逻辑） |
| `prompt` | string | ✅ | 待验证的 video summary prompt 文本 |
| `required_fields` | string[] | ✅ | schema 中标记为 required 的字段名列表 |

**返回值**：
```json
{
  "valid": true | false,
  "use_case_name": "child_safety",
  "missing_fields": ["severity"],
  "checked_fields": ["event", "severity", "desc"]
}
```

---

## 工具对照表

| Tool | 实现状态 | 关键特性 |
|------|----------|---------|
| `alert_query` | ✅ | action 枚举；stats 聚合；LEFT JOIN 返回 task+event 详情；severity 通过 task 字段追溯 |
| `plan_ctl` | ✅ | per-monitor plans CRUD（list/upsert/delete）；任意 JSON，rule engine 可在触发前查询 |
| `scene_query` | ✅ | vllm-serving-ipex 集成；ffmpeg resize；帧归档；`<think>` 过滤 |
| `generate_report` | ✅ | SRT 构建；multilevel-video-understanding caption-only；reports 表写入；debug SRT 持久化 |
| `monitor_ctl` | ✅ | DB + videostream-analytics 两层管理；RTSP 校验 |
| `rule_eval` | ✅ | 通用 SEVERITY 提取；告警不冗余存 severity；通过 task_id 外键追溯 |
| `video_db` | ✅ | 只读 SELECT；防止写操作 |
| `use_case_validate` | ✅ | 大小写不敏感；返回 missing_fields |

---

## 数据目录

所有运行时数据统一存放在一个根目录下，通过环境变量控制：

```
export SMARTBUILDING_DATA_DIR=/path/to/data   # 默认: ~/.mcp-smartbuilding
```

目录结构：

```
$SMARTBUILDING_DATA_DIR/
├── smartbuilding.db               — SQLite 数据库
├── segments/
│   └── <monitor_id>/
│       ├── latest.jpg             — 最新帧（scene_query 读取）
│       └── queries/<date>/        — scene_query 帧归档
└── logs/
    └── reports/                   — generate_report SRT 调试文件
```

---

## 数据流概览

```
videostream-analytics (:8999)
  │ POST /events webhook → MCP events endpoint (:3101)
  │   → INSERT INTO events (motion_type, start_time, prefilter_classes, ...)
  │   → INSERT INTO recordings (file_path, start_time, end_time, ...)
  │   → INSERT INTO video_summary_tasks (event_id, clip_file_path, status=pending)
  │
  ▼
video-worker (MCP internal)
  │ poll pending tasks → summary_service (:8192)
  │ VLM 返回 summary_text（含 SEVERITY/EVENT/DESC 等自定义字段）
  │ SchemaManager 按 config.schema 解析扩展字段
  │ UPDATE video_summary_tasks SET status=completed,
  │   summary_text=..., event=..., severity=..., desc=...
  │
  ▼
rule_eval (manual or scheduled)
  │ scan completed tasks → 提取 SEVERITY
  │ INSERT INTO alerts (monitor_id, task_id, event_id, alert_type, description)
  │ ← severity 不冗余写入 alerts，通过 task_id JOIN 追溯
  │
  ▼
alert_query     — 查询 alerts，LEFT JOIN tasks+events 返回完整上下文
generate_report — 查询 events/alerts/tasks，构建 SRT，调用 VLM 生成报告
scene_query     — 读取 latest.jpg，调用 vllm-serving-ipex 分析当前帧
```
