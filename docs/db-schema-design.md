# DB Schema Design — SmartBuilding Video Toolkit

## 1. 设计原则

- **固定表 + 可定制扩展列/表**：核心表结构跨 use case 通用，用户通过 schema YAML 声明扩展字段
- **所有写入由 MCP server 统一完成**：videostream-analytics 微服务不直接写 DB，通过 webhook 传递事件元数据
- **大小写不敏感**：schema 字段名与 VLM 输出 key 匹配时忽略大小写
- **video summary prompt 与 schema 联动**：LOCAL_PROMPT 的输出格式必须覆盖 schema 中所有 required 扩展字段

---

## 2. 表结构总览

| 表 | 类型 | 写入方 | 用途 |
|---|---|---|---|
| `events` | 固定 | MCP server（从 videostream-analytics microservice 发送的 webhook 提取） | 流处理触发事件（motion/static） |
| `recordings` | 固定 | MCP server（从 videostream-analytics microservice 发送的 webhook 提取） | 录制段文件元数据 |
| `video_summary_tasks` | 固定 + 扩展列 | MCP server video-worker | multilevel-video-understanding 视频片段分析任务及结果 |
| `alerts` | 固定 + 扩展列 | MCP server rule-engine | 告警记录 |
| `reports` | 固定 | MCP server（daily_report tool） | 定期报告（日/周/月报） |
| `monitor_state` | 固定 | MCP server（rule-engine / tools） | 运行时状态（JSON） |
| *用户自定义表* | 可选 | MCP server（按 schema 声明创建） | use case 特有数据（如 plans） |

---

## 3. 固定表定义

### 3.1 events（流处理触发事件）

```sql
CREATE TABLE events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    monitor_id          TEXT NOT NULL,
    motion_type         TEXT NOT NULL,       -- "motion" / "static"
    start_time          TEXT NOT NULL,
    end_time            TEXT,
    duration_seconds    REAL,
    -- prefilter 状态（MCP server 从 webhook payload 提取写入，可选）
    prefilter_passed    INTEGER,             -- 0/1
    prefilter_classes   TEXT,                -- JSON array: ["person","knife"]
    prefilter_confidence REAL,               -- 最高置信度
    trajectory_region   TEXT,                -- 归一化 bbox "x0,y0,x1,y1"
    created_at          TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_events_monitor_time ON events(monitor_id, start_time);
```

`motion_type` 记录运动状态（motion/static），与 use case 层面的事件类型（fall/escape 等）是不同层级的概念。

### 3.2 recordings（录制段元数据）

```sql
CREATE TABLE recordings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    monitor_id          TEXT NOT NULL,
    file_path           TEXT NOT NULL,
    start_time          TEXT NOT NULL,
    end_time            TEXT NOT NULL,
    duration_seconds    REAL,
    file_size_bytes     INTEGER,
    created_at          TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_recordings_monitor_time ON recordings(monitor_id, start_time, end_time);
```

### 3.3 video_summary_tasks（VLM 分析任务）

此表记录每一个发送给 multilevel-video-understanding 服务分析的视频片段及结果。

```sql
CREATE TABLE video_summary_tasks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    monitor_id          TEXT NOT NULL,
    event_id            INTEGER REFERENCES events(id),
    clip_start_time     TEXT NOT NULL,
    clip_end_time       TEXT NOT NULL,
    clip_duration       REAL,
    clip_file_path      TEXT,
    summary_text        TEXT,                
    -- pending / processing / completed / failed
    status              TEXT DEFAULT 'pending', 
    error_message       TEXT,
    latency_seconds     REAL,
    prompt_tokens       INTEGER,
    image_tokens        INTEGER,
    completion_tokens   INTEGER,
    started_at          TEXT,
    completed_at        TEXT,
    created_at          TEXT DEFAULT (datetime('now', 'localtime'))
    -- User Customize: ALTER TABLE ADD COLUMN
);
CREATE INDEX idx_vst_status ON video_summary_tasks(status);
CREATE INDEX idx_vst_monitor ON video_summary_tasks(monitor_id);
```

### 3.4 alerts（告警）

```sql
CREATE TABLE alerts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    monitor_id          TEXT NOT NULL,
    task_id             INTEGER REFERENCES video_summary_tasks(id),
    event_id            INTEGER REFERENCES events(id),
    use_case            TEXT NOT NULL,
    alert_type          TEXT NOT NULL,       -- use case 事件语义（如 fall, escape, late_wakeup）
    severity            TEXT NOT NULL,       -- critical / warn / info
    description         TEXT,               -- 人可读告警描述
    created_at          TEXT NOT NULL,
    ack_at              TEXT,
    ack_by              TEXT
    -- 用户可定制扩展列在此处 ALTER TABLE ADD COLUMN
);
CREATE INDEX idx_alerts_monitor_time ON alerts(monitor_id, created_at);
CREATE INDEX idx_alerts_ack ON alerts(ack_at);
```

`alert_type` + `monitor_id` 组合构成 cooldown key（同一组合在 cooldown 期内不重复告警）。

### 3.5 reports（定期报告）

```sql
CREATE TABLE reports (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    monitor_id          TEXT NOT NULL,
    use_case            TEXT NOT NULL,
    period_start        TEXT NOT NULL,       -- 报告覆盖起始时间
    period_end          TEXT NOT NULL,       -- 报告覆盖结束时间
    report_text         TEXT,
    event_count         INTEGER,
    motion_count        INTEGER,
    latency_seconds     REAL,
    prompt_tokens       INTEGER,
    image_tokens        INTEGER,
    completion_tokens   INTEGER,
    status              TEXT DEFAULT 'pending', -- pending / completed / failed
    report_type         TEXT DEFAULT 'raw',    -- raw / polished
    created_at          TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_reports_monitor_period ON reports(monitor_id, period_start);
```

`period_start` / `period_end` 支持日报（1天）、周报（7天）、月报等任意时间范围。MCP tool `daily_report` 的输入参数即为 `period_start` + `period_end`。

### 3.6 monitor_state（运行时状态）

```sql
CREATE TABLE monitor_state (
    monitor_id          TEXT PRIMARY KEY,
    use_case            TEXT,
    state_json          TEXT,               -- 任意 JSON，各 use case 自定义内容
    updated_at          TEXT NOT NULL
);
```

---

## 4. 扩展机制

### 4.1 Use Case Schema YAML

用户通过 YAML 声明扩展字段。schema 文件与 use case 注册时一并提交。

```yaml
# 默认 schema（大多数 use case 使用这三个字段即可）
schema:
  video_summary_tasks:
    extensions:
      - name: event
        type: text
        description: "事件类型"
        required: true
      - name: severity
        type: text
        description: "严重程度 (critical/warn/info)"
        required: true
      - name: desc
        type: text
        description: "事件描述"
        required: true

  alerts:
    extensions: []

  custom_tables: []
```

### 4.2 扩展字段写入流程

```
VLM 返回 summary_text:
  "SEVERITY: warn\nEVENT: jump\nDESC: 儿童从沙发上跳下"
      │
      ▼ MCP server default parser（按 schema 字段名匹配，大小写不敏感）
  parsed = { event: "jump", severity: "warn", desc: "儿童从沙发上跳下" }
      │
      ▼ 写入 video_summary_tasks 表 (满足过滤条件)
  UPDATE video_summary_tasks SET
    summary_text = <原文>,
    event = "jump",
    severity = "warn",
    desc = "儿童从沙发上跳下",
    status = "completed"
  WHERE id = ?
```

### 4.3 高级 Schema 示例（elder_wakeup）

```yaml
schema:
  video_summary_tasks:
    extensions:
      - name: event
        type: text
        required: true
      - name: severity
        type: text
        required: true
      - name: desc
        type: text
        required: true
      - name: wakeup_time_s
        type: real
        description: "起床时间（秒，从视频开始计）"
        required: false

  alerts:
    extensions:
      - name: wakeup_time
        type: real
        description: "实际起床时间戳"

  custom_tables:
    - name: plans
      columns:
        - { name: monitor_id, type: text, not_null: true }
        - { name: use_case, type: text, not_null: true }
        - { name: plan_date, type: text, not_null: true }
        - { name: plan_json, type: text, not_null: true }
        - { name: active, type: integer, default: 1 }
        - { name: created_at, type: text, not_null: true }
      unique: [monitor_id, plan_date]
```

---

## 5. Schema 变更策略

用户运行一段时间后修改 schema 的处理方式：

| 变更类型 | 处理方式 | 风险 |
|---------|---------|------|
| **新增列** | `ALTER TABLE ADD COLUMN`（SQLite 原生支持） | 无。历史行新列值为 NULL |
| **删除列** | 标记为 deprecated，停止写入，旧数据保留 | 低。不丢数据 |
| **修改列类型** | 新增列（新类型） + 标记旧列 deprecated | 低 |
| **新增自定义表** | `CREATE TABLE IF NOT EXISTS` | 无 |
| **删除自定义表** | 需用户显式确认 → `DROP TABLE` | 高。数据不可恢复 |

**实现方式**：MCP server 启动时对比 schema YAML 与实际 DB：
1. 发现新列 → 自动 `ALTER TABLE ADD COLUMN`
2. 发现 schema 中删除了列 → 警告日志，不自动删除
3. 发现新表 → `CREATE TABLE IF NOT EXISTS`

用户修改 schema 后重启 MCP server 即可生效。

---

## 6. db_manager MCP Tool / CLI

所有 DB schema 操作通过 `smartbuilding_db_manager` MCP tool 完成：

```bash
# 注册 use case（创建 schema，自动 ALTER TABLE）
smartbuilding_db_manager action=register_use_case \
  name=pet_safety \
  schema='<schema YAML or JSON>'

# 查看表结构
smartbuilding_db_manager action=list_schema table=video_summary_tasks
smartbuilding_db_manager action=list_schema table=alerts

# 新增扩展列
smartbuilding_db_manager action=add_column \
  table=video_summary_tasks name=confidence type=real

# 标记列 deprecated（停止写入，数据保留）
smartbuilding_db_manager action=deprecate_column \
  table=video_summary_tasks name=old_field

# 创建自定义表
smartbuilding_db_manager action=create_table \
  name=plans \
  columns='[{"name":"monitor_id","type":"text","not_null":true},...]' \
  unique='["monitor_id","plan_date"]'

# 删除自定义表（需确认）
smartbuilding_db_manager action=drop_table name=plans confirm=true

# 查看所有已注册 use case
smartbuilding_db_manager action=list_use_cases
```

---

## 7. 大小写不敏感匹配规则

VLM 输出中的 key 与 schema 字段名匹配时：
- `EVENT:` / `event:` / `Event:` 均匹配 schema 中的 `event` 字段
- 匹配算法：`field.name.toLowerCase() === outputKey.toLowerCase()`
- 如果 VLM 输出中同一字段出现多次，取第一次出现的值

---

## 8. 与 Video Summary Prompt 的联动校验

### 校验规则

schema 中所有 `required: true` 的扩展字段名必须出现在 LOCAL_PROMPT 的输出格式说明中。

### 校验工具

```bash
smartbuilding_use_case_validate task_name=pet_safety_monitor schema=pet_safety
```

校验逻辑：
1. 读取已注册 task 的 LOCAL_PROMPT 文本
2. 读取 schema 中所有 required 扩展字段名
3. 检查 LOCAL_PROMPT 中是否包含每个字段名（大小写不敏感搜索）
4. 通过 → 返回 `{ valid: true }`
5. 失败 → 返回 `{ valid: false, missing: ["field1", "field2"] }`

### 自动生成时的联动

agent 向导调用 `smartbuilding_video_summary_task action=autogen` 时，自动将 schema 字段注入生成约束：

```
生成 LOCAL_PROMPT 的指令:
  "输出格式必须包含以下字段（每行一个 KEY: value）：
   EVENT: <事件类型>
   SEVERITY: critical | warn | info
   DESC: <一句话描述>
   严格遵守此格式，不要添加其他输出。"
```

---

## 9. 数据流全景

```
videostream-analytics 微服务 (:8999)
  │ webhook POST /events
  │ payload: { monitor_id, motion_type, start_time, end_time, 
  │            clip_file_path, prefilter_*, recording_path, ... }
  ▼
MCP Server /events endpoint
  │ 写入 events 表（motion_type, prefilter 字段）
  │ 写入 recordings 表（如果 payload 含 recording 信息）
  │ 写入 video_summary_tasks 表（status=pending, clip_file_path）
  ▼
MCP Server video-worker 模块
  │ poll pending tasks → fetch multilevel-video-understanding
  │ multilevel-video-understanding 返回 summary_text
  │ default parser 按 schema 提取字段 → 写入扩展列
  │ UPDATE video_summary_tasks SET status=completed, event=?, severity=?, desc=?, ...
  ▼
MCP Server rule-engine
  │ evaluate_rules（内置默认 or Python override）
  │ 如果触发 → INSERT INTO alerts (monitor_id, alert_type, severity, desc, ...)
  │ MCP Resource Subscription 广播
  ▼
订阅方（OpenClaw / Hermes / Claude Desktop）
```
