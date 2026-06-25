# Plan: MCP Tools & Resources 尽调与框架无关性重构

## 术语说明

**Stub（桩函数）**：软件工程术语，指只有接口定义和空实现（或 placeholder 返回值）的函数。用于早期开发阶段搭建项目骨架，使代码可编译、可调用，但无实际功能。例如：
```typescript
export async function sceneQuery(params: SceneQueryParams): Promise<unknown> {
  // TODO: implement
  return {};  // stub: 无实际逻辑，仅返回空对象
}
```

**服务区分**：
- **vllm-serving-ipex**（`:41091`）：视觉语言模型推理服务，支持单帧图像 + 文本 prompt → 场景描述。用于 **scene_query**（实时场景分析）。
- **multilevel-video-understanding**（`:8192`）：多层视频理解服务，支持视频片段分析 + caption-only 模式（纯文本输入）。用于 **video_summary_tasks**（运动片段分析）和 **generate_report caption-only 模式**（从事件日志生成报告）。

## 背景

smart-community MCP Server 的设计目标是**框架无关（framework-agnostic）**和**用例无关（use-case-agnostic）**，这是 finalized design doc (smartbuilding-video-design-2026.2.md) 的核心原则。当前实现是早期骨架阶段，存在以下问题：

1. **工具未实现**: `generate_report`、`rule_eval`、`scene_query` 只有接口定义和 TODO 注释，无实际逻辑
2. **功能缺失**: 许多工具缺少 smarthome 参考实现中已有的 action 和参数
3. **可配置字段当作固定值**: `severity` 是用户自定义 schema 扩展字段，但 `alert_query` 代码假定它固定存在
4. **工具功能不足**: `state_query` 缺少 plan 管理，`monitor_ctl` 缺少 RTSP 校验，`alert_query` 缺少 stats 模式

本 plan 解决用户提出的问题：
- `stats_only` 是做什么的？ → 高效聚合查询模式（返回统计数字而非完整 alert 列表），避免拉取大数据量
- 如何避免用例专用逻辑？ → 通过 monitor config YAML 的配置驱动分派，实现时不要硬编码 `if (useCase === "fridge")`
- 自定义字段（severity/event）如何处理？ → 通过 `task_id` 外键从 `video_summary_tasks` 表追溯，不在 `alerts` 表冗余存储

---

## 需修改的关键文件

### 1. Tools 层

**`packages/mcp-server/src/tools.ts`** — Tool 注册
- 现状：8 个工具注册，基础 schema
- 改动：增强 input schema 以匹配 smarthome action 集合

**`packages/tools/src/alert-query.ts`** — Alert 工具实现
- 现状：基础查询 + status 过滤，通过 ID 确认
- 改动：添加 action 枚举 (latest/by_date/ack/stats)，日期范围参数

**`packages/tools/src/state-query.ts`** — 状态管理
- 现状：通用 JSON blob get/set
- 改动：
  - 添加 plan 管理 action (list_plans/upsert_plan/delete_plan)
  - **WRITABLE_STATE_KEYS 白名单**：安全机制，防止 tool 调用者修改系统保留字段（例如：只允许写 `user_note`, `preferred_alert_language`，拒绝写 `expected_wakeup_time` 等受保护字段）

**`packages/tools/src/scene-query.ts`** — 实时场景分析
- 现状：TODO stub（仅接口定义 + 空实现）
- 改动：完整集成（复制 smarthome 模式：帧捕获 → 调用 vllm-serving-ipex `:41091` → 可选归档）
- 服务：vllm-serving-ipex 的 `/v1/chat/completions` 端点，vision model 推理

**`packages/tools/src/generate_report.ts`** — 生成报告（支持日报/周报/月报/自定义时间范围）
- 现状：TODO stub
- 改动：
  - 支持多种报告类型：
    - `type` 参数："daily" | "weekly" | "monthly" | "custom"（默认使用 `config.reports.defaultType`）
    - `custom` 类型需额外参数：`period_start`, `period_end`（YYYY-MM-DD 格式）
  - 配置驱动的数据源选择（events/alerts/tasks），**避免硬编码 `if (useCase === "fridge")`**
  - Caption-only 模式：将事件日志转为 SRT 格式，POST 到 multilevel-video-understanding `:8192` 的 `/v1/summary` 端点
  - Debug 持久化：当 `config.debug.enabled = true` 时，SRT 中间产物保存到 `{dataDir}/logs/reports/{monitor_id}_{type}_{start}_{end}.srt`

**`packages/tools/src/monitor-ctl.ts`** — Monitor 生命周期
- 现状：TODO stub
- 改动：管理两个服务
  1. **videostream-analytics microservice**：通过 RESTful API 管理（POST `/register_source`, DELETE `/sources/{id}`, POST `/sources/{id}/pause` 等，见设计文档 §7.3）
  2. **video-worker**：MCP Server 内部模块，启停 per-monitor task poller
- 配置：在 `config.yaml` 中预留 `videostream_analytics.url` placeholder（默认 `http://localhost:8999`）
- 联调：videostream-analytics 由其他同事实现，集成时通过 RESTful endpoint 联调

**`packages/tools/src/rule-eval.ts`** — 手动规则触发
- 现状：TODO stub
- 改动：通用 hook 接口，通过 use-case adapter 注册表分派回调

**`packages/tools/src/use-case-validate.ts`** — Schema 校验
- 现状：prompt 文本中的简单子串搜索
- 改动：通过 SchemaManager 进行 schema-aware 校验，检查必需字段与 DB schema 匹配

### 2. 配置 Schema

**`packages/db/src/config-schema.ts`**（新文件）— Monitor 配置类型
- 目的：Monitor config YAML 结构的 TypeScript 接口
- 内容：`ReportConfig` 接口，包含 `dataSource`, `period_start`, `period_end`, `filterSeverity`, `taskFilter`, `includeLiveSnapshot` 等

**`config.yaml.example`** — 示例 monitor 配置
- 改动：添加 `report` 配置块，展示 fridge/child_safety/elder_wakeup 模式，说明如何配置日报/周报/月报

---

## 差距分析：Tools

| Tool | Smarthome Actions | MCP 现状 | 缺失/待实现功能 |
|------|------------------|---------|---------------|
| **alert_query** | `latest`, `by_date`, `by_type`, `ack`, `unacked_count` | `query`, `ack`（互斥） | • 日期范围过滤<br>• Stats/count 模式（总数 + unacked 数）<br>• Action 枚举设计模式<br>• 通过 `task_id` 外键可追溯完整事件详情 |
| **state_query** | `get`, `set`, `list_plans`, `upsert_plan` | `get`, `set` | • Plan 管理（独立表）<br>• WRITABLE_STATE_KEYS 白名单（防止修改系统保留字段）<br>• State key 命名空间 |
| **scene_query** | 完整集成 | TODO stub（无实现） | • 帧捕获机制<br>• 调用 vllm-serving-ipex<br>• Fallback prompt 逻辑<br>• 帧归档选项 |
| **generate_report** | 用例 handler (child_safety, elder_wakeup, fridge) | TODO stub（无实现） | • 支持自定义时间范围（日报/周报/月报）<br>• 配置驱动分派<br>• SRT 时间线生成<br>• Caption-only 模式<br>• Artifact 持久化（reports 表） |
| **monitor_ctl** | `status`, `list`, `start_stream`, `stop_stream`, `clear_recordings`, RTSP validation | TODO stub（无实现） | • RTSP URL 校验<br>• 进程管理器生命周期<br>• Config.yaml 持久化<br>• 流健康检查 |
| **rule_eval** | Elder_wakeup fallback, child_safety audit | TODO stub（无实现） | • 通用回调分派<br>• Use-case adapter 注册表<br>• State 检查接口 |
| **video_db** | Action 枚举 (stats/recent_events/tasks_by_date/report/clear) | TODO stub（无实现） | • 破坏性操作的安全包装<br>• 高层 action 抽象 |
| **use_case_validate** | Smarthome 中无 | TODO stub（无实现） | • Schema-aware 校验<br>• DB schema 集成<br>• 必需字段检查 |

### Alert 查询设计原则

**核心理念**：写入 `alerts` 表的数据已经过 rule engine 筛选，都是"需要告警的重要事件"，无需在查询时再按 type/severity 过滤。

**关键架构原则**：
- `alerts` 表通过 `task_id` 外键关联 `video_summary_tasks`，通过 `event_id` 关联 `events`
- `alerts` 表有固定字段：
  - `alert_type`（TEXT）：自然语言描述告警原因，例如"儿童从高处跳下"，由 rule engine 生成，给人类看
  - `monitor_id`, `task_id`, `event_id`, `use_case`, `created_at`, `ack_at`, `ack_by`（固定列）
- `severity`, `event`, `desc`, `confidence` 等**不在** `alerts` 表冗余存储，通过 `task_id` 外键从 `video_summary_tasks` 追溯
- **不需要 by_type/by_severity 过滤**：rule engine 已做筛选，`alerts` 表中的每一条都重要

**Alert 查询核心功能**：
1. **按日期范围查询**：`by_date` action，支持 `start_date` ~ `end_date`
2. **查询最新 N 条**：`latest` action + `limit` 参数
3. **确认告警**：`ack` action，记录 `ack_at` 和 `ack_by`
4. **统计模式**：`stats` action，返回总数 + unacked 数（无需按 severity/type 分组统计）

**追溯完整事件**：
```typescript
// Client-side: 通过 task_id 获取完整事件详情
const alert = alertQuery({ action: "latest", limit: 1 });
const task = db.getTask(alert.task_id);  // 获取视频分析结果 + 自定义字段（event, severity, desc 等）
const event = db.getEvent(alert.event_id);  // 获取 motion 检测原始数据
const clip = task.clip_file_path;  // 视频片段路径
```

**优势**：
- 数据归一化：`alerts` 表结构固定，与用例 schema 解耦
- 简化查询：按日期排序即可，无需复杂过滤条件
- 用例无关：任何用例的 alert 查询逻辑完全一致
- 可追溯性：通过外键可还原完整事件上下文

---

## 配置驱动的报告生成设计

### 问题

当前 `generate-report.ts` 有硬编码分支：
```typescript
if (useCase === "fridge") {
  // query events table
} else if (useCase === "child_safety") {
  // query alerts table
}
```

这违反了**用例无关性**原则。新增用例需要修改代码。

### 解决方案：配置驱动分派

在 monitor YAML 中添加 `reports` 配置块：

```yaml
monitors:
  cam_fridge:
    useCase: fridge
    reports:
      dataSource: events          # "events" | "alerts" | "tasks"
      defaultType: daily          # 默认报告类型（agent 说"生成报告"时用此类型）
      filter:                     # key-value 过滤条件（应用于 dataSource 表）
        motion_type: motion       # 过滤 events 表的 motion_type 字段
      includeLiveSnapshot: true   # 附加最新帧场景分析

  cam_child:
    useCase: child_safety
    reports:
      dataSource: alerts
      defaultType: daily
      filter: {}                  # 空 filter = 查询所有告警（rule engine 已筛选）

  cam_elder_bedroom:
    useCase: elder_wakeup
    reports:
      dataSource: tasks
      defaultType: daily
      filter:
        event: wakeup             # 过滤 tasks 表的 event 字段（自定义扩展字段）
```

**实现**：
```typescript
// 无用例字符串硬编码
const reportConfig = monitor.reports;
const filter = reportConfig.filter || {};

let data;
if (reportConfig.dataSource === "events") {
  data = db.getEventsByTimeRange(periodStart, periodEnd, filter);
} else if (reportConfig.dataSource === "alerts") {
  data = db.queryAlerts({ monitorId, startDate: periodStart, endDate: periodEnd, ...filter });
} else if (reportConfig.dataSource === "tasks") {
  data = db.getTasks({ monitorId, startDate: periodStart, endDate: periodEnd, ...filter });
}
```

**优势**：
- 新增用例零代码修改
- 数据源留在配置中，不在 tool 逻辑中
- 跨框架复用（Hermes、Claude Desktop、Cursor）

---

## 实施步骤

### Phase 1: Tools 增强（高优先级）

1. **alert_query 重构**
   - 添加 action 枚举：`latest`, `by_date`, `ack`, `stats`
   - `by_date` action：添加日期范围参数 `start_date`, `end_date`
   - `latest` action：添加 `limit` 参数（默认 20）
   - `ack` action：记录 `ack_at`, `ack_by`
   - `stats` action：返回 `{ total: number, unacked: number }`（无需按 type/severity 分组）
   - 返回值包含 `task_id`, `event_id` 外键，供客户端追溯完整事件详情

2. **generate_report 配置化**
   - 定义 `ReportConfig` 接口（包含 `dataSource`, `defaultType`, `filter` 等）
   - 支持报告类型参数：
     - `type` = "daily" | "weekly" | "monthly" | "custom"（默认使用 `config.reports.defaultType`）
     - `custom` 类型需额外提供：`period_start`, `period_end`（ISO 8601 格式）
   - 根据 type 自动计算时间范围：
     - daily: today 00:00 ~ 23:59
     - weekly: last 7 days
     - monthly: last 30 days
     - custom: 使用用户指定的 `period_start` ~ `period_end`
   - 移除用例字符串匹配逻辑
   - 实现配置驱动的数据源选择 + key-value filter
   - Caption-only 模式：将事件日志转为 SRT 格式，POST 到 multilevel-video-understanding (`:8192`) `/v1/summary` 端点
   - Debug 持久化：当 `config.debug.enabled = true` 时，SRT 持久化到 `{dataDir}/logs/reports/{monitor_id}_{type}_{start}_{end}.srt`

3. **scene_query 实现**
   - 复制 smarthome 集成模式
   - 通过 videostream-analytics 或 ffmpeg fallback 捕获帧
   - 调用 vllm-serving-ipex (`:41091`) `/v1/chat/completions` 端点 + fallback prompt
   - 可选的帧归档

4. **state_query plan 管理**
   - 添加 plan 管理 action（elder_wakeup 用例需要：跟踪每日计划起床时间）
   - 实现 WRITABLE_STATE_KEYS 白名单（例如：允许 `user_note`，拒绝 `expected_wakeup_time`）
   - 独立 plans 表或 state key 命名空间（设计决策：独立表 vs JSON 字段）

5. **monitor_ctl 生命周期**
   - 实现两层管理：
     - videostream-analytics microservice：RESTful API 调用（POST `/register_source`, DELETE `/sources/{id}` 等）
     - video-worker：MCP Server 内部 task poller 启停
   - RTSP URL 校验（格式检查，可选连接测试）
   - 配置持久化：注册成功后更新 `config.yaml` 中的 monitors 列表

6. **use_case_validate schema-aware**
   - 与 SchemaManager 集成
   - 按实际 DB schema 校验必需字段
   - 移除简单子串搜索

### Phase 2: Config Schema & 文档

1. **创建 config schema 类型**
   - `ReportConfig` 接口（含 `dataSource`, `defaultType`, `filter` 等）
   - `MonitorConfig` 接口含 `reports` 字段
   - 从 `packages/db/src/config-schema.ts` 导出

2. **更新 config.yaml.example**
   - 展示 fridge/child_safety/elder_wakeup monitor 示例
   - 记录所有 `reports` 配置字段：
     - `defaultType`: "daily" | "weekly" | "monthly"（默认报告类型）
     - `dataSource`: "events" | "alerts" | "tasks"
     - `filter`: key-value 对象（可选，为空则查询所有）
     - `includeLiveSnapshot`: boolean（可选）
   - 展示 schema 扩展示例

3. **更新 CLAUDE.md**
   - 记录配置驱动设计
   - 解释 `dataSource` vs 用例无关性
   - 链接到 db-schema-design.md 了解 schema 定制

4. **创建 docs/implements/tools_list.md**
   - 列出所有 MCP tools 清单
   - 每个 tool 的功能说明、action 枚举、参数列表、返回值结构
   - 实现状态标记（✅ 已实现 / ⚠️ 部分实现 / ❌ TODO）
   - 与设计文档的对照表

---

## 实现细节

### DB 层新增方法

为了支持规范化 schema（alerts 表不冗余存储自定义字段），需要在 `packages/db/src/database.ts` 中添加：

```typescript
// 带 JOIN 的 alert 查询，返回包含 task 详情的 alert
interface AlertWithTask extends Alert {
  task?: VideoSummaryTask;  // 包含 event, severity, desc, clip_file_path 等
  event?: Event;             // 包含 motion_type, start_time, prefilter_classes 等
}

class SmartBuildingDB {
  // 查询 alert + 关联的 task 和 event
  queryAlertsWithDetails(params: {
    monitorId?: string;
    startDate?: string;
    endDate?: string;
    limit?: number;
  }): AlertWithTask[] {
    const whereClauses: string[] = [];
    const bindings: any[] = [];
    
    if (params.monitorId) {
      whereClauses.push('a.monitor_id = ?');
      bindings.push(params.monitorId);
    }
    if (params.startDate) {
      whereClauses.push('date(a.created_at) >= ?');
      bindings.push(params.startDate);
    }
    if (params.endDate) {
      whereClauses.push('date(a.created_at) < ?');
      bindings.push(params.endDate);
    }
    
    const whereClause = whereClauses.length > 0 ? `WHERE ${whereClauses.join(' AND ')}` : '';
    const limitClause = params.limit ? `LIMIT ${params.limit}` : '';
    
    const query = `
      SELECT 
        a.id as alert_id, a.monitor_id, a.task_id, a.event_id, 
        a.use_case, a.alert_type, a.created_at, a.ack_at, a.ack_by,
        t.id as task_id, t.clip_file_path, t.summary_text, t.status as task_status,
        t.event as task_event, t.severity as task_severity, t.desc as task_desc,
        e.id as event_id, e.motion_type, e.start_time, e.end_time
      FROM alerts a
      LEFT JOIN video_summary_tasks t ON a.task_id = t.id
      LEFT JOIN events e ON a.event_id = e.id
      ${whereClause}
      ORDER BY a.created_at DESC
      ${limitClause}
    `;
    
    const rows = this.db.prepare(query).all(...bindings);
    return rows.map(row => ({
      id: row.alert_id,
      monitorId: row.monitor_id,
      taskId: row.task_id,
      eventId: row.event_id,
      useCase: row.use_case,
      alertType: row.alert_type,
      createdAt: row.created_at,
      ackAt: row.ack_at,
      ackBy: row.ack_by,
      task: row.task_id ? {
        id: row.task_id,
        clipFilePath: row.clip_file_path,
        summaryText: row.summary_text,
        status: row.task_status,
        event: row.task_event,        // 自定义字段
        severity: row.task_severity,  // 自定义字段
        desc: row.task_desc,          // 自定义字段
      } : undefined,
      event: row.event_id ? {
        id: row.event_id,
        motionType: row.motion_type,
        startTime: row.start_time,
        endTime: row.end_time,
      } : undefined,
    }));
  }
  
  // Alert 统计（不需要 JOIN，直接 COUNT）
  getAlertStats(monitorId: string, startDate?: string, endDate?: string): {
    total: number;
    unacked: number;
  } {
    const whereClauses = ['monitor_id = ?'];
    const bindings: any[] = [monitorId];
    
    if (startDate) {
      whereClauses.push('date(created_at) >= ?');
      bindings.push(startDate);
    }
    if (endDate) {
      whereClauses.push('date(created_at) < ?');
      bindings.push(endDate);
    }
    
    const whereClause = whereClauses.join(' AND ');
    const row = this.db.prepare(`
      SELECT 
        COUNT(*) as total,
        SUM(CASE WHEN ack_at IS NULL THEN 1 ELSE 0 END) as unacked
      FROM alerts
      WHERE ${whereClause}
    `).get(...bindings) as { total: number; unacked: number };
    
    return row;
  }
  
  // 确认 alert（添加 ack_by 参数）
  ackAlert(alertId: number, ackBy: string): void {
    this.db.prepare(`
      UPDATE alerts 
      SET ack_at = datetime('now'), ack_by = ?
      WHERE id = ?
    `).run(ackBy, alertId);
  }
}
```

**关键设计点**：
1. `queryAlertsWithDetails` 通过 LEFT JOIN 返回 alert + 关联的 task + event 详情
2. 客户端可以从 `alert.task.severity`, `alert.task.event` 读取自定义字段
3. `getAlertStats` 不需要 JOIN，直接统计，性能高
4. `ackAlert` 添加 `ack_by` 参数，记录是谁确认的告警

### Alert Query Tool 实现示例

```typescript
// packages/tools/src/alert-query.ts
import type { SmartBuildingDB, AlertWithTask } from '@smartbuilding-video/db';

export interface AlertQueryParams {
  monitor_id: string;
  action: 'latest' | 'by_date' | 'ack' | 'stats';
  // latest action 参数
  limit?: number;
  // by_date action 参数
  start_date?: string;  // YYYY-MM-DD
  end_date?: string;    // YYYY-MM-DD
  // ack action 参数
  alert_id?: number;
  ack_by?: string;
}

export async function alertQuery(
  db: SmartBuildingDB,
  params: AlertQueryParams
): Promise<unknown> {
  switch (params.action) {
    case 'latest': {
      const alerts = db.queryAlertsWithDetails({
        monitorId: params.monitor_id,
        limit: params.limit ?? 20,
      });
      return { alerts };
    }
    
    case 'by_date': {
      if (!params.start_date) {
        throw new Error('start_date is required for by_date action');
      }
      const alerts = db.queryAlertsWithDetails({
        monitorId: params.monitor_id,
        startDate: params.start_date,
        endDate: params.end_date,
      });
      return { alerts };
    }
    
    case 'stats': {
      const stats = db.getAlertStats(
        params.monitor_id,
        params.start_date,
        params.end_date
      );
      return stats;
    }
    
    case 'ack': {
      if (!params.alert_id) {
        throw new Error('alert_id is required for ack action');
      }
      if (!params.ack_by) {
        throw new Error('ack_by is required for ack action');
      }
      db.ackAlert(params.alert_id, params.ack_by);
      return { success: true, alert_id: params.alert_id };
    }
    
    default:
      throw new Error(`Unknown action: ${params.action}`);
  }
}
```

**返回值示例**：
```json
{
  "alerts": [
    {
      "id": 123,
      "monitorId": "cam_child",
      "taskId": 456,
      "eventId": 789,
      "useCase": "child_safety",
      "alertType": "child_climbing",
      "createdAt": "2026-06-23T14:32:00.000Z",
      "ackAt": null,
      "ackBy": null,
      "task": {
        "id": 456,
        "clipFilePath": "/data/clips/cam_child_20260623_143200.mp4",
        "summaryText": "SEVERITY: critical\nEVENT: child_climbing\nDESC: Child climbing bookshelf",
        "event": "child_climbing",
        "severity": "critical",
        "desc": "Child climbing bookshelf"
      },
      "event": {
        "id": 789,
        "motionType": "motion",
        "startTime": "2026-06-23T14:31:45.000Z",
        "endTime": "2026-06-23T14:32:15.000Z"
      }
    }
  ]
}
```

客户端可以直接访问 `alert.task.severity`, `alert.task.event` 而无需额外查询。

### Monitor Control Tool 实现示例

```typescript
// packages/tools/src/monitor-ctl.ts
export interface MonitorCtlParams {
  action: 'start' | 'stop' | 'register' | 'status' | 'list';
  monitor_id?: string;
  // register action 参数
  rtsp_url?: string;
  use_case?: string;
  pipeline_config?: Record<string, any>;
}

export async function monitorCtl(
  config: ServerConfig,
  workerService: WorkerService,
  params: MonitorCtlParams
): Promise<unknown> {
  const videostreamUrl = config.videostream_analytics?.url || 'http://localhost:8999';
  
  switch (params.action) {
    case 'register': {
      // 1. RTSP URL 校验
      if (!params.rtsp_url) {
        throw new Error('rtsp_url is required for register action');
      }
      if (!params.rtsp_url.startsWith('rtsp://')) {
        throw new Error('Invalid RTSP URL format');
      }
      
      // 2. 调用 videostream-analytics microservice
      const webhookUrl = `http://localhost:${config.events_webhook.port}/events`;
      const response = await fetch(`${videostreamUrl}/register_source`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_id: params.monitor_id,
          rtsp_url: params.rtsp_url,
          webhook_url: webhookUrl,  // MCP Server 的 /events 端点
          pipeline: params.pipeline_config || {
            motion: { enabled: true },
            prefilter: { enabled: false },
            recording: { enabled: true, interval: 60 },
          },
        }),
      });
      
      if (!response.ok) {
        throw new Error(`Failed to register source: ${response.statusText}`);
      }
      
      // 3. 启动 MCP Server 内部的 video-worker
      workerService.startMonitor(params.monitor_id);
      
      // 4. 持久化配置（可选）
      // updateConfigYaml(params.monitor_id, params.rtsp_url, params.use_case);
      
      return { success: true, monitor_id: params.monitor_id };
    }
    
    case 'stop': {
      // 1. 停止 video-worker
      workerService.stopMonitor(params.monitor_id);
      
      // 2. 暂停 videostream-analytics 流处理
      await fetch(`${videostreamUrl}/sources/${params.monitor_id}/pause`, {
        method: 'POST',
      });
      
      return { success: true, monitor_id: params.monitor_id };
    }
    
    case 'start': {
      // 1. 恢复 videostream-analytics 流处理
      await fetch(`${videostreamUrl}/sources/${params.monitor_id}/resume`, {
        method: 'POST',
      });
      
      // 2. 启动 video-worker
      workerService.startMonitor(params.monitor_id);
      
      return { success: true, monitor_id: params.monitor_id };
    }
    
    case 'status': {
      // 查询 videostream-analytics 的 source 状态
      const response = await fetch(`${videostreamUrl}/sources/${params.monitor_id}/status`);
      const status = await response.json();
      
      // 合并 video-worker 状态
      const workerStatus = workerService.getMonitorStatus(params.monitor_id);
      
      return {
        monitor_id: params.monitor_id,
        stream: status,  // videostream-analytics 返回的状态
        worker: workerStatus,  // video-worker 状态
      };
    }
    
    case 'list': {
      // 列出所有已注册的 monitors
      const response = await fetch(`${videostreamUrl}/sources`);
      const sources = await response.json();
      
      return { monitors: sources };
    }
    
    default:
      throw new Error(`Unknown action: ${params.action}`);
  }
}
```

**配置文件示例**（`config.yaml`）：
```yaml
debug:
  enabled: false  # 全局 debug 开关（true 时持久化 SRT 等中间产物）

videostream_analytics:
  url: http://localhost:8999  # Placeholder，联调时由其他同事提供实际 endpoint
  
events_webhook:
  port: 3101  # MCP Server /events webhook 监听端口（可配置）

monitors:
  cam_child:
    rtsp_url: rtsp://localhost:8554/live/child
    use_case: child_safety
    reports:
      dataSource: alerts
      defaultType: daily
      filter: {}
    # ... 其他配置
```

**videostream-analytics API 参考**（设计文档 §7.3）：
- `POST /register_source` — 注册新 source
- `DELETE /sources/{id}` — 注销 source
- `GET /sources` — 列出所有 sources
- `GET /sources/{id}/status` — 查询 source 状态
- `POST /sources/{id}/pause` — 暂停处理
- `POST /sources/{id}/resume` — 恢复处理

---

## 验证计划

### Tool 测试

1. **alert_query**：
   - 调用 `action=by_date&start_date=2026-06-01&end_date=2026-06-23` → 验证日期范围查询
   - 调用 `action=latest&limit=10` → 验证返回最新 10 条
   - 调用 `action=stats` → 验证返回 `{ total: N, unacked: M }`
   - 调用 `action=ack&alert_id=123&ack_by=user1` → 验证 ack 记录
   - 验证返回的 alert 包含 `task_id`, `event_id` 外键

2. **generate_report**：
   - 日报：`type=daily` → 验证今日数据查询
   - 周报：`type=weekly` → 验证 7 天数据聚合
   - 自定义范围：`type=custom&period_start=2026-06-01&period_end=2026-06-15` → 验证指定时间范围
   - Fridge monitor (dataSource: events, filter: {motion_type: motion}) → 验证 events 查询 + filter
   - Child safety (dataSource: alerts) → 验证仅 alerts 查询
   - Elder wakeup (dataSource: tasks, filter: {event: wakeup}) → 验证 task 过滤

3. **scene_query**：
   - 在有 live frame 的 monitor 上调用 → 验证服务响应
   - 在无 videostream-analytics 的 monitor 上调用 → 验证 ffmpeg fallback 或错误

4. **state_query**：
   - 调用 `action=list_plans` → 验证 plan 列表
   - 调用 `action=upsert_plan` → 验证 DB 写入
   - 尝试写非白名单 state key → 验证拒绝

### 端到端验证

1. **Standalone MCP 模式**（Claude Desktop）：
   - 在 Claude Desktop config 中配置 MCP server
   - 询问："Any alerts this week?" → 验证 `alert_query` action=by_date 日期范围查询
   - 询问："Generate daily report for cam_child" → 验证日报生成
   - 询问："Generate weekly report for cam_child" → 验证周报生成（7 天数据）

2. **新用例注册**：
   - 注册 pet_safety monitor + 自定义 `reports` 配置
   - 生成报告 → 验证零代码修改

---

## 可复用的 Smarthome 模式

### 1. Action 枚举设计
Smarthome tools 使用 action 参数而非独立 tool：
- `alert_query`: action = latest | by_date | ack | stats（MCP 简化版，移除 by_type/unacked_count）
- 优势：单个 tool 注册，一致的 API，更易权限管理

### 2. 外键追溯模式
MCP 通过外键追溯事件详情，而非冗余存储：
```typescript
// MCP: 通过 task_id 外键获取详情
const alert = db.getAlert(123);
const task = db.getTask(alert.task_id);  // severity, event, desc, clip_file_path
const event = db.getEvent(alert.event_id);  // motion_type, start_time, prefilter_classes

// Smarthome: 直接存储在 alerts 表
const alert = db.getAlert(123);  // 已包含 severity, event, desc（冗余设计）
```

### 3. Plan 管理作为一级实体
Smarthome 有独立的 plans 表，带确定性 key：
- `(monitor_id, plan_date)` 唯一约束
- Plans 跨重启持久化
- Elder_wakeup 用于跟踪起床时间

### 4. 帧归档模式
Smarthome 的 scene_query 可选归档帧：
```typescript
if (archiveFrame) {
  const archivePath = `${dataDir}/scenes/${timestamp}.jpg`;
  fs.writeFileSync(archivePath, frameBuffer);
}
```

### 5. Fallback Prompt 模式
Scene query 未提供问题时，使用默认 prompt：
```typescript
const prompt = params.question || "Describe what you see in this scene.";
```

---

## 参考文件

### Smarthome 参考实现
- `/home/mytest/agent-ai.smarthome/openclaw-extensions/smarthome-video/src/tools/alert-query.ts` — Action 枚举模式，severity 过滤
- `/home/mytest/agent-ai.smarthome/openclaw-extensions/smarthome-video/src/tools/daily-report.ts` — Use-case handler（待迁移到配置）
- `/home/mytest/agent-ai.smarthome/openclaw-extensions/smarthome-video/src/tools/scene-query.ts` — 实时场景分析集成，帧归档
- `/home/mytest/agent-ai.smarthome/openclaw-extensions/smarthome-video/src/tools/state-query.ts` — Plan 管理
- `/home/mytest/agent-ai.smarthome/openclaw-extensions/smarthome-video/src/db.ts` — 带 plans 表的 DB 层
- `/home/mytest/agent-ai.smarthome/openclaw-smarthome-demo/openclaw-plugin-monitors.yaml` — Monitor 配置结构

### 设计文档
- `/home/mytest/agent-ai.smart-community-ai-automation/docs/smartbuilding-video-design-2026.2.md` — 最终设计（§3.2 tools, §3.3 resources, §5 use-case adapter）
- `/home/mytest/agent-ai.smart-community-ai-automation/docs/db-schema-design.md` — Schema 扩展机制

### 当前实现
- `/home/mytest/agent-ai.smart-community-ai-automation/packages/mcp-server/src/tools.ts` — Tool 注册
- `/home/mytest/agent-ai.smart-community-ai-automation/packages/mcp-server/src/resources.ts` — Resource 定义
- `/home/mytest/agent-ai.smart-community-ai-automation/packages/tools/src/` — Tool 实现
- `/home/mytest/agent-ai.smart-community-ai-automation/packages/db/src/database.ts` — DB 层
- `/home/mytest/agent-ai.smart-community-ai-automation/packages/rule-engine/src/engine.ts` — Rule engine

---

## 总结

本计划解决了所有已识别的差距，同时保持框架和用例无关性：

1. **Tools**：用 smarthome action 模式增强，改为配置驱动
2. **配置**：Monitor 专用的 `reports` 配置（支持 daily/weekly/monthly + filter key-value）消除用例硬编码
3. **Alert 查询**：通过外键追溯完整事件，不在 alerts 表冗余存储自定义字段
4. **Stats 模式**：实现为聚合 action，避免拉取大数据量
5. **服务管理**：monitor_ctl 管理 videostream-analytics microservice + video-worker

所有改动保持设计目标："零代码用例创建"。新用例通过声明配置工作，无需编写 TypeScript。