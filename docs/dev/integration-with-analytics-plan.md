# Plan: Monitor 生命周期健壮性 —— 重复注册、优雅退出、启动对账

## Context

`monitor_ctl register_source` 当前实现在 DB 已存在 monitor 时直接跳过 DB 写入，并继续调用 analytics `/register_source`，没有处理 DB 与 analytics 状态不一致的四种情况。此外 MCP server 关闭或 crash 时不通知 analytics，重启后也不恢复 online monitors。本 plan 解决这三个问题，并产出一份面向 videostream-analytics 开发侧的联调文档。

---

## 关键文件

- `packages/tools/src/monitor-ctl.ts` — 主要修改：`register_source` case
- `packages/mcp-server/src/index.ts` — 修改：优雅退出 + 启动对账
- `packages/db/src/database.ts` — 删除 `monitor_state` 表 + 新增 `updateMonitor` 方法
- `docs/implements/monitor-ctl-analytics-integration.md` — 新建联调文档

---

## 一、register_source 四种情况处理

通过并发查询 DB (`db.getMonitor`) 和 analytics (`GET /sources/{id}/status`) 判断组合状态：

- analytics 200 → 存在；404 → 不存在；超时/连接错误 → **不可达，直接抛出异常**（无法确定状态，拒绝继续）

### 情况矩阵

新增 **video-worker** 列：`workerService.workers.has(monitorId)`，代表当前进程内是否有正在运行的 poller interval。

| DB | Analytics | Worker running | 判断逻辑 | 处理方案 |
|----|-----------|----------------|----------|----------|
| ❌ | ❌ | ❌ | 全新注册 | INSERT DB → analytics `/register_source` → `workerService.start` |
| ✅ | ❌ | ❌ | 曾注册，analytics 已清除 | 校验 use_case_id → 更新 DB → analytics `/register_source` → `workerService.start` |
| ✅ | ✅ | ❌ | MCP server 重启未 unregister（无残留 worker） | 校验 use_case_id → 更新 DB → analytics `DELETE` → 若 DELETE 失败抛异常 → analytics `/register_source` → `workerService.start` |
| ✅ | ✅ | ✅ | 一切正常，重复调用 | 直接返回 `{ success: true, monitor_id, status: "already_running" }`，不做任何变更 |
| ✅ | ❌ | ✅ | DB/analytics 已关闭但 worker 仍在轮询（stop 时 race）| 校验 use_case_id → `workerService.stop` → 更新 DB → analytics `/register_source` → `workerService.start` |
| ❌ | ✅ | ❌ | DB 数据丢失，analytics 还在跑 | analytics `DELETE` → 若 DELETE 失败抛异常 → INSERT DB → analytics `/register_source` → `workerService.start` |
| ❌ | ✅ | ✅ | DB 丢失但 worker 残留（极端 crash 场景） | `workerService.stop` → analytics `DELETE` → 若 DELETE 失败抛异常 → INSERT DB → analytics `/register_source` → `workerService.start` |
| ❌ | ❌ | ✅ | Worker 孤儿（DB/analytics 均无，进程内残留） | `workerService.stop` → INSERT DB → analytics `/register_source` → `workerService.start` |

**注意**：DB 更新/插入在 analytics DELETE 之前完成（情况 2、3 先更新 DB，再 DELETE，再 register）。原因：DB 是本地持久化，操作更可靠；analytics DELETE 失败时已有 DB 记录，方便用户排查。

### use_case_id 一致性校验（DB 存在时）

参数名统一使用 `use_case_id`（与 `monitors` 表字段、`MonitorCtlParams` 接口一致，`Monitor` TS 接口对应字段为驼峰 `useCaseId`）。

仅在传入了 `use_case_id` 参数且与 DB 已存值不同时报错：
```
throw new Error(`use_case_id mismatch: DB="${existing.useCaseId}", got="${params.use_case_id}". Unregister first.`)
```

### video-worker 处理

**架构**：WorkerService 是 **per-monitor** 的，每个 `monitor_id` 有独立的 `setInterval`。

**需要改造 TaskPoller/WorkerService 支持 graceful async stop**：

当前 `stopPolling` 是同步 `clearInterval`，正在 in-flight 的 async `poll()` 不会被中断。矩阵中凡需要先 stop 再 re-register 的情况，都依赖 stop 完成后才能安全操作 analytics。

改造方案（`task-poller.ts` + `video-worker/index.ts`）：
- `TaskPoller` 新增 `private activePoll: Map<string, Promise<void>>` 追踪每个 monitor 当前 in-flight 的 poll Promise
- `TaskPoller.stopPolling(monitorId)` 改为 `async`：`clearInterval` + `await activePoll.get(monitorId)`
- `WorkerService.stop(monitorId)` 改为 `async`，`stopAll()` 改为 `async`

**职责分工**：DB + analytics + video-worker 三层协调是 `monitorCtl` 的原子职责，`tools.ts` 只负责调用并返回结果。

`monitorCtl` 函数签名增加 `workerService` 参数：

```typescript
export async function monitorCtl(
  db: SmartBuildingDB,
  analyticsBaseUrl: string,
  workerService: WorkerService,   // 新增
  params: MonitorCtlParams
): Promise<unknown>
```

`tools.ts` 里删除现有的 `workerService.start/stop` 调用，统一由 `monitorCtl` 内部处理。`register_source` case 内部按矩阵执行：graceful stop（如需）→ DB 操作 → analytics 操作 → workerService.start。

### DB 改动

删除 `monitor_state` 表及 `getState()`/`setState()` 方法（无调用方，死代码）。

新增 `updateMonitor()` 方法：

```typescript
// packages/db/src/database.ts
updateMonitor(id: string, updates: {
  sourceUrl?: string;
  name?: string;
  useCaseId?: string;
  videoSummaryTask?: string;
  status?: Monitor["status"];
}): void
```

---

## 二、优雅退出

在 `index.ts` 的 `SIGINT` / `SIGTERM` handler 中，新增 `shutdown()` 函数：

```
async function shutdown(db, analyticsUrl, workerService, eventsEndpoint):
  1. await workerService.stopAll()（graceful，等 in-flight polls 完成）
  2. 查询 DB 中所有 status=online 的 monitors
  3. 并发调用 analytics POST /sources/{id}/pause（fire-and-forget，超时 3s，失败静默）
  4. 批量 db.updateMonitorStatus(id, 'offline')
  5. eventsEndpoint.stop()
  6. db.close()
  7. process.exit(0)
```

同时监听 `SIGTERM`（容器/systemd 关闭信号，当前只有 SIGINT）。

---

## 三、启动时对账

**前提**：MCP server 启动时不自动带动任何 monitor（无 auto-start / `enabled` 机制）。DB 中 `status=online` 的记录只可能来自上次 crash。启动时 worker running 固定为 ❌，对账是情况矩阵的子集。

在 `main()` 中 `workerService` 初始化之后调用 `reconcileOnStartup()`：

```
async function reconcileOnStartup(db, analyticsUrl, workerService):
  1. GET /sources（analytics 返回所有已注册 sources）
     - 若 analytics 不可达：logger.warn，跳过对账（不阻塞启动）
  2. analyticsById = Map<id, source>
  3. 遍历 DB 中 status=online 的 monitors（worker 固定 ❌）：
     a. analytics 存在（矩阵 ✅/✅/❌）
        → DELETE analytics（清理旧状态）+ db.updateMonitorStatus(id, 'offline')
        → 不自动重注册，需人工 register_source
        → logger.warn(`monitor {id} found in videostream-analytics ({analyticsUrl}) on startup, deleted and marked offline — call register_source to restart`)
     b. analytics 不存在（矩阵 ✅/❌/❌）
        → db.updateMonitorStatus(id, 'offline')，不自动重注册（需人工 register_source）
        → logger.warn(`monitor {id} not found in videostream-analytics ({analyticsUrl}) after restart, marked offline — call register_source to restart`)
  4. 遍历 analytics 中存在但 DB 中不存在的 source（孤儿，以 DB 为准）：
     → DELETE analytics `DELETE /sources/{id}`（fire-and-forget，失败只 warn）
     → logger.info(`deleted orphan source {id} from videostream-analytics ({analyticsUrl})`)
  5. logger.info(`reconcile complete: {offlined} marked offline, {deleted} orphans deleted`)
```

---

## 四、Keepalive（联调文档 TODO）

MCP server 侧实现在本 plan 中**不做**，仅在联调文档中写清楚协议约定供 analytics 侧参考：

- analytics 提供 `POST /sources/{id}/keepalive` 端点
- MCP server 每 30s 发送一次（`setInterval`，遍历 DB online monitors）
- analytics 超过 90s 未收到 keepalive → 自动 pause 该 source
- MCP server 侧实现等 analytics 端就绪后补充

---

## 五、联调文档结构

`docs/implements/monitor-ctl-analytics-integration.md`：

1. **register_source 状态矩阵**（八种情况 + 处理流程）
2. **优雅退出行为**（SIGINT/SIGTERM → pause → offline）
3. **启动对账行为**（offline/孤儿删除）
4. **analytics 侧 API 约定**（已实现）：`/register_source`、`DELETE /sources/{id}`、`GET /sources/{id}/status`、`/pause`、`/resume`、`GET /sources`
5. **Webhook 事件协议约定**（analytics → MCP server `POST http://localhost:3101/events`）：

   三种 event type 及其 DB 写入目标：

   | type | DB 写入 | 说明 |
   |------|---------|------|
   | `motion` | `events`（motion_type=motion）+ `video_summary_tasks`（status 条件写入，见下） | 运动检测触发，含 prefilter 通过和未通过两种情况，统一 type=motion |
   | `static` | `events`（motion_type=static） | 静止状态，无视频片段，不创建 task |
   | `recording` | `recordings` | 录制段元数据，独立 event type |

   **`video_summary_tasks` status 写入规则（motion 事件）**：
   - prefilter 字段存在 且 `prefilter_passed=1` → `status=pending`（送入 video summary 队列）
   - prefilter 字段存在 且 `prefilter_passed=0` → `status=ignored`（跳过 video summary）
   - prefilter 字段不存在 → `status=pending`（默认处理）

   **`video_summary_tasks` status 新增 `ignored` 值**，需同步更新 TypeScript 类型定义。

   各 type payload 字段约定及示例：

   **`motion` event**（required: `event_file_path`, `summary_clip_input`, `start_time`, `duration_seconds`）：
   ```json
   {
     "sourceId": "cam_child",
     "type": "motion",
     "timestamp": "2026-06-25T14:30:45Z",
     "payload": {
       "event_file_path": "/data/motion_events/cam_child/seg_00001.mp4",
       "summary_clip_input":  "/data/motion_events/cam_child/seg_00001_input.mp4",
       "start_time": "2026-06-25T14:30:30Z",
       "end_time":   "2026-06-25T14:30:45Z",
       "duration_seconds": 15.2,
       "prefilter_passed": 1,
       "prefilter_classes": "[\"person\"]",
       "prefilter_confidence": 0.92,
       "trajectory_region": "100,50,300,400"
     }
   }
   ```
   - `event_file_path`（`*.mp4`）：原始完整视频片段 → 写入 `events.event_file_path`（新增列）
   - `summary_clip_input`（`*_input.mp4`）：crop 版本，直接送给 video summary 服务 → 写入 `video_summary_tasks.summary_clip_input`
   - `prefilter_passed` 缺省时视为无 prefilter，status=pending

   **`static` event**（required: `start_time`, `duration_seconds`）：
   ```json
   {
     "sourceId": "cam_child",
     "type": "static",
     "timestamp": "2026-06-25T14:31:00Z",
     "payload": {
       "start_time": "2026-06-25T14:30:45Z",
       "end_time":   "2026-06-25T14:31:00Z",
       "duration_seconds": 15.0
     }
   }
   ```
   - 仅写 `events`（motion_type=static），不创建 task，无 prefilter 字段

   **`recording` event**（required: `recording_path`, `recording_start`, `recording_end`）：
   ```json
   {
     "sourceId": "cam_child",
     "type": "recording",
     "timestamp": "2026-06-25T14:31:00Z",
     "payload": {
       "recording_path":  "/data/recordings/cam_child/rec_20260625_143000.mp4",
       "recording_start": "2026-06-25T14:30:00Z",
       "recording_end":   "2026-06-25T14:31:00Z",
       "duration_seconds": 60.0,
       "file_size_bytes": 8192000
     }
   }
   ```
   - 仅写 `recordings` 表

   **Payload 合法性检查**：events-endpoint.ts 按 type 校验 required 字段，缺失时 logger.warn 并跳过对应 DB 写入（不抛 500，防止 malformed event 中断流水线）。

   **DB schema 变更**：`events` 表需新增 `event_file_path TEXT` 列（原始视频路径，可选）。

   **当前 events-endpoint.ts 实现缺口**：只处理 `motion` 且只写 `video_summary_tasks`，未写 `events`/`recordings` 表，无 payload 校验。本 plan 同步改造。

6. **[TODO: analytics-side] Keepalive 协议**：端点、心跳间隔(30s)、超时阈值(90s)
7. **Corner cases**：
   - analytics 不可达时 register_source 直接失败（不做猜测）
   - use_case_id 变更必须先 unregister
   - 孤儿 source（analytics 存在但 DB 无）：以 DB 为准，启动对账时自动删除，DELETE 失败只 warn 不阻塞
   - 启动对账失败不阻塞 MCP server 启动
   - **in-flight poll race**：通过 TaskPoller graceful async stop 解决（`await activePoll`），stop 返回后 in-flight poll 已完成，可安全继续 analytics 操作

---

## 实施步骤

1. `database.ts` + `types.ts` — 删除 `monitor_state` 表/方法；新增 `updateMonitor()` 方法；`events` 表 MIGRATIONS 加 `event_file_path TEXT` 列；`video_summary_tasks` 表列名 `clip_file_path` 改为 `summary_clip_input`；`VideoSummaryTask.status` 类型新增 `"ignored"` 值；`Event` 接口新增 `eventFilePath?: string` 字段；`VideoSummaryTask` 接口字段 `clipFilePath` 改为 `summaryClipInput`
2. `task-poller.ts` + `video-worker/index.ts` — graceful async stop（`activePoll` Map + `await`）
3. `monitor-ctl.ts` — 函数签名加 `workerService` 参数；重写 `register_source` case（八行情况矩阵）；`start`/`stop`/`unregister` 同步加入 `workerService` 操作
4. `tools.ts` — `monitorCtl` 调用改为传入 `workerService`；删除现有的 `workerService.start/stop` 调用
5. `events-endpoint.ts` — 按协议约定改造 webhook handler：`motion` 写 `events`（含 `event_file_path`、prefilter 字段）+ `video_summary_tasks`；`static` 写 `events`；`recording` 写 `recordings`；按 type 校验 required 字段
6. `index.ts` — 新增 `reconcileOnStartup()` + 重构 SIGINT/SIGTERM 为 async `shutdown()`，增加 SIGTERM 监听
7. 新建 `docs/implements/monitor-ctl-analytics-integration.md`
8. 新建 `tests/mock/videostream-analytics/mock_server.py`（基于 `tests/dev-mcp-server/mock_videostream.py` 扩展，增加 REST API + 真实视频片段 webhook）
9. 更新 `tests/dev-mcp-server/test_events_webhook.py` — 按新协议重写测试：
   - motion event：payload 改为 `event_file_path` + `summary_clip_input` + prefilter 字段；验证 `events` 表 + `video_summary_tasks` 表均有写入
   - static event：验证仅写 `events` 表，不创建 task
   - motion event 含 `prefilter_passed=0`：验证 `video_summary_tasks.status=ignored`
   - recording event：验证写 `recordings` 表
   - invalid payload（缺 required 字段）：验证 warn 但不抛 500
10. 新建 `tests/mcp-tools/monitor-ctl/test_monitor_ctl.py`（情况矩阵全路径 auto tests）
10. 全量 `npm run build` 验证

---

## 验证

### Mock videostream-analytics 服务

新建 `tests/mock/videostream-analytics/mock_server.py`，基于 `tests/dev-mcp-server/mock_videostream.py` 扩展。

**增加 videostream-analytics RESTful API**（状态存内存 dict，进程内有效）：
- `POST /register_source` → 记录 source，返回 200
- `DELETE /sources/{id}` → 删除 source，返回 200 / 404
- `GET /sources` → 返回所有已注册 sources
- `GET /sources/{id}/status` → 返回单个 source 状态，不存在返回 404
- `POST /sources/{id}/pause` → 更新状态为 paused
- `POST /sources/{id}/resume` → 更新状态为 running

**使用真实视频片段发送 webhook events**：

`data/motion_events/` 目录下按摄像头存放了真实 mp4 片段：
```
data/motion_events/
├── cam_child/        seg_NNNNN_*.mp4（原始），seg_NNNNN_*_input.mp4（crop 版本）
├── cam_elder_bedroom/
├── cam_elder_bedroom_2/
└── cam_fridge/       seg_NNNNN_*.mp4（仅原始，无 _input.mp4）
```

mock server 按摄像头策略发送事件：

| 摄像头 | prefilter | event_file_path（原始 → events 表） | summary_clip_input（crop/原始 → video summary） |
|--------|-----------|-------------------------------------|------------------------------------------------|
| `cam_fridge` | 无（不携带 prefilter 字段） | `seg_NNNNN_*.mp4` | 同 event_file_path（无 crop） |
| `cam_child` | passed 值：序列中随机 1-2 个设为 0（prefilter 未通过），其余为 1；classes=["person"]，confidence=0.9 | `seg_NNNNN_*.mp4` | `seg_NNNNN_*_input.mp4`（有 crop）；passed=0 时仍发送字段但 MCP server 写 ignored |
| `cam_elder_bedroom`、`cam_elder_bedroom_2` | 同 cam_child（随机 1-2 个 passed=0） | `seg_NNNNN_*.mp4` | 同 event_file_path（无 crop） |

参数示例（`--monitor` 可指定一至多个摄像头，默认全部）：
```bash
python tests/mock/videostream-analytics/mock_server.py \
  --port 8999 \
  --events-url http://localhost:3101/events \
  --data-dir data/motion_events \
  --interval 60 \                     # 发送间隔（秒），默认 60
  --monitor cam_child cam_fridge      # 可选，默认全部 4 个
```

### Auto tests（Python）

新建 `tests/mcp-tools/monitor-ctl/test_monitor_ctl.py`，通过 MCP HTTP 调用验证所有情况矩阵路径：

| 测试用例 | 前置条件 | 期望结果 |
|----------|----------|----------|
| 全新注册（❌/❌/❌） | DB 空，mock analytics 无此 source | DB 插入，analytics 注册成功 |
| 重复调用（✅/✅/✅） | DB 有，analytics 有，worker 已启动 | 返回 `already_running`，无变更 |
| 曾注册 analytics 已清除（✅/❌/❌） | DB 有，analytics 无此 source | 更新 DB，re-register 成功 |
| DB 丢失 analytics 在跑（❌/✅/❌） | DB 无，analytics 有此 source | DELETE 后重建，DB 插入 |
| use_case 不一致 | DB 有 use_case_id=A，传入 B | 抛出异常，DB 不变 |
| analytics 不可达 | mock server 未启动 | 抛出异常（明确失败） |
| 优雅退出 | 启动 MCP server，注册 monitor | SIGINT 后 DB status=offline，analytics paused |
| 启动对账：DB online + analytics 有 | crash 模拟（DB status=online）| 启动后 analytics DELETE + DB offline |
| 启动对账：DB online + analytics 无 | crash 模拟（DB status=online，mock 无此 source）| DB 标记 offline |
| 启动对账：孤儿 source | mock analytics 有，DB 无 | analytics DELETE |

```bash
# 运行方式
python tests/mock/videostream-analytics/mock_server.py --port 8999 &
python tests/mcp-tools/monitor-ctl/test_monitor_ctl.py
```

### 编译验证
```bash
npm run build  # 全包无错误
```
