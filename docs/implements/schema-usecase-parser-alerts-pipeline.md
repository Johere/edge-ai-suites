# Schema → Use Case → Parser → Alerts → DB 端到端链路

本文档串联说明从用户在 `config.yaml` 声明 schema 开始，到 video-summary 输出落库为 alert 的完整数据流。所有环节都是 **use-case-agnostic** 的——加新用例只需改 yaml 配置，无需写 TypeScript 代码。

---

## 0. 概览

```
config.yaml schema ──┐
                     ├── (a) SchemaManager 建表 (ALTER TABLE)
config.yaml          │
use_case_dict ───────┼── (b) monitor 注册时校验 prompt ↔ schema 一致性
                     │       (smartbuilding_use_case_validate)
monitors.yaml ───────┘
                       │
                       ▼
                 monitor 在线，开始接收事件
                       │
       ┌───────────────┴───────────────┐
       │  videostream-analytics (:8999)│
       │  motion event → webhook       │
       └───────────────┬───────────────┘
                       ▼
              events + video_summary_tasks
              (status=pending, summary_clip_input)
                       │
                       ▼  video-worker poll
              multilevel-video-understanding (:8192)
                       │
                       ▼  video-summary 返回 summary_text
              (c) schema-aware parser
                  解析 schema.extensions 中声明的字段
                       │
              ┌────────┴────────┐
              ▼                 ▼
   (d) 扩展列写库          (e) rule engine 评估
   video_summary_tasks         severity ∈ {critical,warn}?
   .event = "..."              (或 Python override)
   .severity = "..."                │
   .desc = "..."                    ▼ shouldAlert
   .confidence = ...        (f) 写 alerts 表
                            (alerts.description)
```

---

## 1. 用户在 config.yaml 声明 schema

```yaml
schema:
  video_summary_tasks:
    extensions:
      - { name: "event",      type: "text", required: true }
      - { name: "severity",   type: "text", required: true }
      - { name: "desc",       type: "text", required: true }
      - { name: "confidence", type: "real", required: false }
```

**这是金标准**：

- 用户希望从 video-summary 输出里抓哪些字段，就在这里声明
- `required: true` 的字段必须出现在 video-summary 输出中，否则 parser 会 warn
- 字段名完全由用户定义，MCP server 对名称无任何假设
- `alerts` 表**不**接受 extensions（保持 use-case-agnostic）

参考：[config.yaml.example](../../config.yaml.example) 顶部 `schema:` 块。

---

## 2. SchemaManager 启动时 ALTER TABLE

MCP server 启动时（`packages/mcp-server/src/index.ts`）：

```typescript
const schemaManager = new SchemaManager((db as any).db);
const result = schemaManager.applySchema(config.schema);
```

`SchemaManager.applySchema()`（[packages/db/src/schema-manager.ts](../../packages/db/src/schema-manager.ts)）：

- 对每个 extension 调用 `addColumnIfMissing(table, ext)`
- 列不存在 → `ALTER TABLE video_summary_tasks ADD COLUMN <name> <type>`
- 列已存在但类型不同 → 收集到 warnings（不自动改类型，需要手工迁移）
- 已存在且类型匹配 → 跳过

`SchemaManager.validatePromptSchema()` 同时提供 prompt ↔ schema 一致性校验，被下面的 `use_case_validate` 复用。

---

## 3. 用户在 use_case_dict 声明用例

```yaml
use_case_dict:
  child_safety:
    description: "Child safety monitoring"
    video_summary_task: child_safety_monitor       # multilevel 服务里的 task 名
    evaluate_rules_path: /path/to/use-cases/child_safety/evaluate_rules.py  # 可选
    reports:
      data_source: alerts
      default_type: daily
```

参考：[config.yaml.example](../../config.yaml.example) `use_case_dict:` 块。

monitors.yaml 通过 `use_case` 字段引用 dict key：

```yaml
monitors:
  cam_child:
    enabled: true
    source_url: rtsp://...
    use_case: child_safety            # 引用 use_case_dict 的 key
```

启动时引用一致性校验在 `index.ts` 完成：monitor 的 `use_case` 必须存在于 `config.useCaseDict`，否则启动报错退出。

---

## 4. [MCP tool] use_case_validate：use case ↔ video-summary 服务一站式校验

`smartbuilding_use_case_validate`（[packages/tools/src/use-case-validate.ts](../../packages/tools/src/use-case-validate.ts)）是验证一个 use case 是否可用的唯一入口，三步检查：

1. **use_case 存在性**：`use_case` 是否在 `config.useCaseDict` 中
2. **summary service + task 存在性**：`GET <summaryService.url>/v1/tasks/<video_summary_task>`，必须返回 200
3. **schema 一致性**：取 `config.schema.video_summary_tasks.extensions` 中 `required:true` 的字段名，验证它们都出现在 task 的 LOCAL_PROMPT 中（复用 `SchemaManager.validatePromptSchema`，大小写不敏感子串）

任一失败 → 返回 `{ valid: false, ... }`，错误信息附 LOCAL_PROMPT 末尾 200 字符 + 修复建议。

**两种调用场景**：

- **被动校验**（monitor 注册时）：`smartbuilding_monitor_ctl action=register_source` 内联调用本工具，失败 → 拒绝注册（不写 DB、不调 analytics、不启动 worker）
- **主动校验**（独立 dry-check）：直接调用 `smartbuilding_use_case_validate`，**不依赖任何 monitor**。适合：
  - 刚在 `config.yaml` 添加新 use_case 后立即验证配置是否完整
  - 改了 multilevel-video-understanding 的 LOCAL_PROMPT 后验证仍覆盖 schema 字段
  - 改了 `config.schema.extensions` 后验证已有 task 的 prompt 是否需要同步更新
  - CI 流水线里跑一遍所有 use_case，确保部署前不会因配置错误而启动失败

**此校验保证**：Multilvel-video-understanding 真正运行时，输出格式与 parser 期望的 schema 字段名匹配，避免 "schema 声明的字段但 prompt 不出"导致整条流水线静默断裂。

---

## 5. 事件触发：events → video_summary_tasks（status=pending）

videostream-analytics（:8999，独立服务）检测到运动事件，POST 到 MCP server 的 `:3101/events` webhook：

```json
{
  "sourceId": "cam_child",
  "type": "motion",
  "payload": {
    "event_file_path":    "/.../cam_child/motion_events/2026-06-26/seg_00001.mp4",
    "summary_clip_input": "/.../cam_child/motion_events/2026-06-26/seg_00001_input.mp4",
    "start_time": "...",
    "duration_seconds": 15.2,
    "prefilter_passed": 1
  }
}
```

[packages/mcp-server/src/events-endpoint.ts](../../packages/mcp-server/src/events-endpoint.ts) 处理 webhook：
- 写 `events` 表（motion_type, prefilter_*, start_time, ...）
- 写 `video_summary_tasks` 表（status=pending, event_id, summary_clip_input, ...）

**注意**：扩展列（`event` / `severity` / `desc`）此时**为空**，等 video-worker 完成 summary 后才填。

---

## 6. video-worker 完成 task + schema-aware 解析

[packages/mcp-server/src/video-worker/task-poller.ts](../../packages/mcp-server/src/video-worker/task-poller.ts) 主循环：

```typescript
// 1. 拉 pending task
const task = this.db.getPendingTasks(monitorId, 1)[0];
this.db.updateTaskStatus(task.id, "processing");

// 2. 调 multilevel-video-understanding 拿 summary_text
const result = await this.videoSummaryClient.summarize({
  videoUrl: task.summaryClipInput, taskId: String(task.id),
});

// 3. schema-aware parse — 只抓 config.schema.extensions 声明的字段
const extensions = this.config.schema?.video_summary_tasks?.extensions ?? [];
const parsed = parseSummaryFields(result.summary ?? "", extensions);

if (parsed.missingRequired.length > 0) {
  logger.warn(`task ${task.id} missing required schema fields: ${parsed.missingRequired.join(", ")}`);
}

// 4. 一条 UPDATE 同时写 summary_text + 扩展列
this.db.updateTaskStatus(task.id, "completed", result.summary, undefined, parsed.fields);
```

**`parseSummaryFields(text, extensions)`**（[packages/rule-engine/src/summary-parser.ts](../../packages/rule-engine/src/summary-parser.ts)）：

- 只解析 `extensions` 中声明的 key（schema 中没有的行直接跳过）
- 大小写不敏感（schema `event` 匹配 `EVENT:` / `Event:` / `event:`）
- 第一次出现的值胜出
- 返回 `{ fields: Record<key, value>, missingRequired: string[] }`

`fields` 直接传给 `updateTaskStatus` 的第 5 个参数 `extensionFields`。

---

## 7. updateTaskStatus 写扩展列（动态 SQL）

[packages/db/src/database.ts](../../packages/db/src/database.ts) `updateTaskStatus()`：

```typescript
updateTaskStatus(id, status, summaryText?, meta?, extensionFields?) {
  // 基础 UPDATE：status, summary_text, completed_at, latency, tokens, error
  const sets = [...];
  const values = [...];

  // 动态加扩展列：先 PRAGMA 拿当前实际列名，过滤后只 UPDATE 真实存在的列
  if (extensionFields) {
    const existingCols = new Set(
      this.db.prepare("PRAGMA table_info(video_summary_tasks)").all().map(r => r.name)
    );
    for (const [col, val] of Object.entries(extensionFields)) {
      if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(col)) continue;  // SQL identifier safety
      if (!existingCols.has(col)) continue;                  // SchemaManager 未跑则跳过
      sets.push(`${col} = ?`);
      values.push(val ?? null);
    }
  }

  this.db.prepare(`UPDATE video_summary_tasks SET ${sets.join(", ")} WHERE id = ?`).run(...values, id);
}
```

**关键设计**：
- 用 `PRAGMA table_info` 过滤后只写真正存在的列 — 即使 SchemaManager 没跑或用户中途改了 schema，也不会 SQL 错误
- 用正则做 SQL identifier 校验，防止注入
- 不在代码中硬编码扩展字段名，谁存在就写谁

---

## 8. rule engine 判断是否 alert

```typescript
const overridePath = this.config.useCaseDict[useCase]?.evaluate_rules_path ?? null;
const ruleCtx = {
  monitorId, useCase, taskId: task.id,
  summaryText: result.summary ?? "",
  payload: { fields: parsed.fields },   // ← 已解析的 schema 字段，rule engine 不用再 parse
};
const ruleResult = await evaluateWithOverride(ruleCtx, overridePath);
```

**`evaluateWithOverride(ctx, path)`**（[packages/rule-engine/src/index.ts](../../packages/rule-engine/src/index.ts)）：

- `path` 不存在 → 跑 `defaultRuleEvaluator`
- `path` 存在 → 执行 `python3 <path> <ctx-json>`，解析 stdout 为 `{ should_alert, alert_message }`
- 用户的 Python 脚本可以做任意复杂判断（时间窗、统计、调外部服务）

**`defaultRuleEvaluator`** 最简单：

```typescript
const severity = (ctx.payload.fields?.severity ?? "").toLowerCase();
if (!["critical", "warn"].includes(severity)) return { shouldAlert: false };
return {
  shouldAlert: true,
  alertMessage: `[${ctx.useCase}] ${event}: ${severity} — ${desc}`,
};
```

> **TODO**: 当前 default 规则只看 severity 字段。未来需要更优雅的规则（per-monitor 可配置阈值/字段名等），目前复杂用例都靠 Python override。

---

## 9. 写 alerts 表

```typescript
if (ruleResult.shouldAlert) {
  this.db.createAlert({
    monitorId,
    taskId: task.id,
    eventId: task.eventId,
    useCase: monitor?.useCase ?? "",
    description: ruleResult.alertMessage,    // ← 来自 rule engine 的 alertMessage
  });
}
```

`alerts` 表**最小固定结构**（[packages/db/src/database.ts](../../packages/db/src/database.ts)）：

```
id, monitor_id, task_id, event_id, use_case, description,
created_at, ack_at, ack_by
```

**不存** `severity` / `event` / `alert_type` 这些用户自定义字段——它们都在 `video_summary_tasks` 的扩展列里，通过 `alerts.task_id → video_summary_tasks.id` JOIN 追溯。

`alert_query` 工具（[packages/tools/src/alert-query.ts](../../packages/tools/src/alert-query.ts)）的 `latest` / `by_date` action 通过 LEFT JOIN 自动把 task 详情一起返回，调用方拿到一个 alert 即可看到所有上下文，不需要再多查一次。

---

## 10. 链路完整示例

假设 `cam_child` 收到 motion event，Multilvel-video-understanding 输出：

```
EVENT: child_climbing
SEVERITY: critical
DESC: Child is climbing bookshelf
CONFIDENCE: 0.91
```

经过本链路后：

**`video_summary_tasks` 表新增行**：
```
id=42, monitor_id=cam_child, status=completed,
summary_text="EVENT: child_climbing\nSEVERITY: critical\n...",
event="child_climbing",
severity="critical",
desc="Child is climbing bookshelf",
confidence=0.91,
...
```

**`alerts` 表新增行**：
```
id=7, monitor_id=cam_child, task_id=42, event_id=15,
use_case="child_safety",
description="[child_safety] child_climbing: critical — Child is climbing bookshelf",
created_at="2026-06-26T10:30:00", ack_at=null, ack_by=null
```

Agent 调 `smartbuilding_alert_query action=latest limit=1`，返回包含 `task` 字段的 `AlertWithTask`，前端能直接展示 severity / event / desc。

---

## 11. 加一个新用例需要做什么

完全配置驱动，**零代码改动**：

1. 在 `config.yaml` 的 `schema.video_summary_tasks.extensions` 加新字段（如果用例需要新解析项）
2. 在 `config.yaml` 的 `use_case_dict` 加新 key：
   - `video_summary_task`: multilevel 服务里 task 名
   - `evaluate_rules_path`（可选）: Python override 脚本路径
   - `reports`（可选）: 报告查询的 data_source / filter
3. 在 multilevel-video-understanding 服务里注册对应 task，LOCAL_PROMPT 末尾输出 schema required 字段
4. 在 `monitors.yaml` 加 monitor 实例，`use_case: <新 key>`
5. 重启 MCP server —— `SchemaManager` 自动 ALTER TABLE，`autoRegisterMonitors` 自动注册并启动管线

无需修改 TS 代码，无需重新发布。

---

## 关键文件索引

| 文件 | 职责 |
|------|------|
| [config.yaml.example](../../config.yaml.example) | schema + use_case_dict 配置示例 |
| [monitors.yaml.example](../../monitors.yaml.example) | monitor 实例声明示例 |
| [packages/db/src/schema-manager.ts](../../packages/db/src/schema-manager.ts) | `applySchema` 启动时 ALTER TABLE；`validatePromptSchema` prompt↔schema 校验 |
| [packages/db/src/database.ts](../../packages/db/src/database.ts) | `updateTaskStatus` 动态写扩展列；`createAlert` 最小固定字段 |
| [packages/rule-engine/src/summary-parser.ts](../../packages/rule-engine/src/summary-parser.ts) | `parseSummaryFields` schema-aware 解析 |
| [packages/rule-engine/src/index.ts](../../packages/rule-engine/src/index.ts) | `defaultRuleEvaluator` + `evaluateWithOverride` |
| [packages/mcp-server/src/video-worker/task-poller.ts](../../packages/mcp-server/src/video-worker/task-poller.ts) | 主循环：summary → parse → 写库 → rule → alert |
| [packages/tools/src/use-case-validate.ts](../../packages/tools/src/use-case-validate.ts) | 三步校验，被 `monitor_ctl register_source` 前置调用 |
