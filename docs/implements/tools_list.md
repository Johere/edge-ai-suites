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

## 5. `smartbuilding_monitor_ctl` ✅

**功能**：原子化管理 monitor 生命周期，三层协调（DB + videostream-analytics + video-worker）在一次调用中完成。

**前置校验（register_source）**：
1. `use_case` / `source_url` 必填；`use_case` 必须是 `config.yaml` 中 `use_case_dict` 的 key
2. 内部调用 `smartbuilding_use_case_validate`：检查 use_case 存在、`video_summary_task` 在 multilevel-video-understanding 中注册、LOCAL_PROMPT 覆盖所有 required schema 字段。任一失败 → 拒绝注册（不写 DB / 不调 analytics / 不启 worker）

**状态矩阵（register_source）**：根据 DB / analytics / worker 三列当前状态自动选择处理路径，无需调用方判断。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `action` | enum | ✅ | 见下表 |
| `monitor_id` | string | — | Monitor ID（除 `list` 外均必填） |
| `source_url` | string | — | 视频源 URL（任意 videostream-analytics 支持的协议：rtsp / http / onvif / file / ...）（for `register_source`，必填） |
| `name` | string | — | 显示名（for `register_source`，可选） |
| `use_case` | string | — | `config.yaml` `use_case_dict` 中的 key（for `register_source`，**必填**） |
| `pipeline_config` | object | — | Analytics pipeline 配置（for `register_source`，默认启用 motion + recording） |
| `webhook_url` | string | — | 事件 Webhook URL（for `register_source`，默认从 `config.eventsWebhook.port` 派生） |

**注意**：`video_summary_task` 不再作为 tool 参数 — 由 use_case 派生（从 `config.useCaseDict[use_case].video_summary_task`）。

**Actions**：

| action | 功能 | 返回值 |
|--------|------|--------|
| `list` | 列出所有已注册 monitors；附加 analytics 实时状态（不可达时 `analyticsReachable=false` + 错误信息） | Monitor 数组（含 `analyticsReachable`, `analyticsStatus`） |
| `register_source` | 原子注册：按状态矩阵处理 DB / analytics / worker，graceful stop 残留 worker 后重建 | `{ success, monitor_id }` 或 `{ status: "already_running" }` |
| `unregister` | 注销：graceful stop worker → analytics DELETE（失败静默）→ 删除 DB 记录 | `{ success, monitor_id }` |
| `start` | 恢复推流：analytics `/resume` + start worker + DB status=online | `{ success, monitor_id, status }` |
| `stop` | 暂停推流：graceful stop worker → analytics `/pause` → DB status=offline | `{ success, monitor_id, status }` |
| `status` | 查询状态：DB 记录 + analytics 实时状态（不可达时 `analyticsReachable=false`） | Monitor + `analyticsReachable` + `analyticsStatus` |

---

## 5a. `smartbuilding_monitors_compose` ✅

**功能**：以 docker-compose 风格批量管理一个 `monitors.yaml` 文件中声明的全部 monitor。工具**每次都直接读盘**（不依赖 MCP server 启动时加载的 `config.monitors`），可针对任意路径的 yaml 文件操作。

**与 `monitor_ctl` 的区别**：
- `monitor_ctl` 操作**单个** monitor，参数全部通过 tool 调用传入
- `monitors_compose` 操作**一个 yaml 内的全部**（或指定 id 的）monitor，配置来自文件

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `action` | enum | ✅ | `validate` \| `up` \| `down` \| `restart` \| `ps` |
| `file` | string | ✅ | monitors.yaml 路径（绝对或相对 cwd） |
| `monitor_id` | string | — | 仅对单个 monitor 执行（不传 = yaml 内所有 monitor） |

**Actions**：

| action | 类比 docker compose | 行为 |
|--------|----|------|
| `validate` | `compose config` | 仅校验字段合法性（source_url / use_case 必填；use_case 必须存在于 `config.useCaseDict`），不修改任何状态 |
| `up` | `compose up -d` | 对每个 `enabled !== false` 的 monitor：若 DB+analytics+worker 三层状态全一致 → 跳过（`already_running`）；否则调 `monitor_ctl register_source` |
| `down` | `compose down` | 对 yaml 内每个 monitor：调 `monitor_ctl unregister`（DB + analytics + worker 全清理） |
| `restart` | `compose restart` | 等价于 `down` → `up` |
| `ps` | `compose ps` | 列出每个 monitor 的 DB / analytics / worker 三层运行状态，不修改 |

**幂等检查（up）**：三步全 true 才算 already_running：
1. DB 存在该 monitor 且 `status=online`
2. analytics `GET /sources/<id>/status` 返回 200
3. workerService 内存中有该 monitor 的 poller

**返回结构**：
```typescript
{
  action: "validate" | "up" | "down" | "restart" | "ps";
  file: string;                  // 解析后的绝对路径
  valid: boolean;                // 任何 action 都会先校验
  errors: { monitor_id, field, reason }[];
  results: {
    monitor_id: string;
    status: "ok" | "already_running" | "skipped" | "failed";
    reason?: string;
    state?: {                    // 仅 ps 填充
      db: { exists, status? };
      analytics: { reachable, status?, error? };
      worker: { running };
    };
  }[];
}
```

**使用场景**：
- `validate`：部署前 CI 检查 yaml 合法性
- `up`：MCP server 启动时 videostream-analytics 不可达 → 修复后手动触发补救式注册
- `down`：维护窗口暂停 yaml 内所有 monitor
- `restart`：yaml 改了 source_url / pipeline_config 后强制重新注册
- `ps`：快速看哪些 cam 跑着、状态对不对

**Per-monitor 日志**：每次 compose 操作的详细 trace（包括 analytics 响应、错误堆栈）写入 `$SMARTBUILDING_DATA_DIR/logs/monitors/<monitor_id>/<YYYY-MM-DD>.log`。

---

## 6. `smartbuilding_video_db` ✅

> **实时告警架构说明**：告警由 video-worker 内部的 rule engine callback 驱动——每当 summary task 完成，立刻调用 `defaultRuleEvaluator`（或 use-case Python override）决定是否写入 alert。Agent 通过 `smartbuilding_alert_query` 查询告警，不需要专门的 rule_eval 工具。

**功能**：只读 SQL 查询，直接访问 SQLite 数据库的所有表（`monitors` / `alerts` / `video_summary_tasks` / `events` / `recordings` / `reports` / `plans` / `monitor_state`）。仅允许 `SELECT` 语句。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | ✅ | SELECT SQL（非 SELECT 语句会被拒绝） |
| `params` | array | — | 位置参数（`?` 占位符对应值） |

**返回值**：查询结果数组

**安全限制**：`INSERT` / `UPDATE` / `DELETE` 等修改语句被拒绝，返回错误。

---

## 7. `smartbuilding_use_case_validate` ✅

**功能**：一站式校验 use_case 与 multilevel-video-understanding 服务的连通性、存在性、合法性。任何想验证 use_case 是否可用的代码路径都走它（已被 `monitor_ctl register_source` 内联为前置 step）。

**三步检查**（顺序，任一失败即整体失败）：

1. **use_case 存在性**：`use_case` 是否在 `config.yaml` 的 `use_case_dict` 中
2. **summary service + task 存在性**：GET `<summaryService.url>/v1/tasks/<video_summary_task>`（task 名从 `use_case_dict[use_case].video_summary_task` 取）
3. **schema 一致性**：`config.schema.video_summary_tasks.extensions` 中所有 `required:true` 字段必须出现在 task 的 LOCAL_PROMPT 中（大小写不敏感子串）

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `use_case` | string | ✅ | use_case_dict 中的 key |

**返回值**：
```json
{
  "valid": true | false,
  "use_case": "child_safety",
  "video_summary_task": "child_safety_monitor",
  "checks": {
    "use_case_known": true,
    "task_registered": true,
    "schema_consistent": false
  },
  "required_fields": ["event", "severity", "desc"],
  "optional_fields": ["confidence"],
  "missing_required_in_prompt": ["desc"],
  "missing_optional_in_prompt": ["confidence"],
  "prompt_tail": "...output format: EVENT: <type>\nSEVERITY: critical|warn|info",
  "suggestion": "Append the following required fields to LOCAL_PROMPT of `child_safety_monitor`: desc"
}
```

`valid` 仅由 required 字段决定；optional 字段缺失只作信息提示。失败时 `prompt_tail` 给 LOCAL_PROMPT 的末尾 200 字符（输出格式约定通常在 prompt 末尾），方便用户定位修改位置。

---

## 工具对照表

| Tool | 实现状态 | 关键特性 |
|------|----------|---------|
| `alert_query` | ✅ | action 枚举；stats 聚合；LEFT JOIN 返回 task+event 详情；severity 通过 task 字段追溯 |
| `plan_ctl` | ✅ | per-monitor plans CRUD（list/upsert/delete）；任意 JSON，rule engine 可在触发前查询 |
| `scene_query` | ✅ | vllm-serving-ipex 集成；ffmpeg resize；帧归档；`<think>` 过滤 |
| `generate_report` | ✅ | SRT 构建；multilevel-video-understanding caption-only；reports 表写入；debug SRT 持久化 |
| `monitor_ctl` | ✅ | DB + videostream-analytics 两层管理；RTSP 校验 |
| `monitors_compose` | ✅ | docker-compose 风格批量管理 monitors.yaml；validate/up/down/restart/ps；三层幂等检查 |
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
├── smartbuilding.db                       — SQLite 数据库
├── segments/                              — videostream-analytics 写入区（由 register_source 的 data_dir 字段约定）
│   └── <monitor_id>/
│       ├── latest.jpg                     — 最新帧（scene_query 读取，每帧 overwrite）
│       ├── recordings/<YYYY-MM-DD>/       — 录像片段（按天 rotate，超过 storage.retention_days 自动清理）
│       ├── motion_events/<YYYY-MM-DD>/    — 运动事件帧（按天 rotate，超过 storage.retention_days 自动清理）
│       └── queries/<YYYY-MM-DD>/          — scene_query 帧归档（按天 rotate，自动清理）
└── logs/
    ├── reports/                           — generate_report SRT 调试文件
    └── monitors/<monitor_id>/<YYYY-MM-DD>.log  — per-monitor 详细日志（按天 rotate，超过 logging.retention_days 自动清理；单文件超过 logging.max_file_mb 暂停 append）
```

**自动清理**：MCP server 启动时 + 每 24h 周期执行：
- `logs/monitors/<id>/` 下日期早于 `today - logging.retention_days`（默认 14）的 `.log` 删除
- `segments/<id>/{motion_events,recordings,queries}/` 下日期早于 `today - storage.retention_days`（默认 7）的整个日期目录删除
- 跳过 `latest.jpg`、`pipeline.db`、非日期格式的子目录名（防止误删）

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
