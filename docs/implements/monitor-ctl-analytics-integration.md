# Monitor Lifecycle & videostream-analytics 联调文档

本文档描述 MCP server `monitor_ctl` 工具与 videostream-analytics 微服务之间的状态管理协议，供双方开发联调参考。

---

## 1. register_source 状态矩阵

调用 `smartbuilding_monitor_ctl action=register_source` 时，MCP server 并发查询 DB 和 analytics 的当前状态，根据三列组合（DB 是否存在 / analytics 是否注册 / video-worker 是否在轮询）决定处理方案。

analytics 可达性判断：
- `GET /sources/{id}/status` 返回 200 → 存在
- 返回 404 → 不存在
- 超时 / 连接错误 → **不可达，直接抛出异常**，拒绝操作（无法确定状态）

| DB | Analytics | Worker | 判断逻辑 | 处理方案 |
|----|-----------|--------|----------|----------|
| ❌ | ❌ | ❌ | 全新注册 | INSERT DB → analytics `/register_source` → start worker |
| ✅ | ❌ | ❌ | 曾注册，analytics 已清除 | 校验 use_case_id → 更新 DB → analytics `/register_source` → start worker |
| ✅ | ✅ | ❌ | MCP server 重启未 unregister | 校验 use_case_id → 更新 DB → analytics DELETE → analytics `/register_source` → start worker |
| ✅ | ✅ | ✅ | 一切正常，重复调用 | 直接返回 `{ status: "already_running" }`，无变更 |
| ✅ | ❌ | ✅ | analytics 已清除但 worker 残留 | 校验 use_case_id → graceful stop worker → 更新 DB → analytics `/register_source` → start worker |
| ❌ | ✅ | ❌ | DB 数据丢失，analytics 在跑 | analytics DELETE → INSERT DB → analytics `/register_source` → start worker |
| ❌ | ✅ | ✅ | DB 丢失且 worker 残留 | graceful stop worker → analytics DELETE → INSERT DB → analytics `/register_source` → start worker |
| ❌ | ❌ | ✅ | worker 孤儿 | graceful stop worker → INSERT DB → analytics `/register_source` → start worker |

**use_case_id 校验**：DB 存在且传入了 `use_case_id` 参数时，若与 DB 已存值不同则抛出异常，要求先调用 `unregister`。

**DB 优先原则**：DB 更新/插入在 analytics DELETE 之前完成，确保即使 DELETE 失败 DB 也有记录。

**worker graceful stop**：`WorkerService.stop()` 为 async，等待当前 in-flight 的 `poll()` 调用完成后再返回，避免 race condition。

---

## 2. 优雅退出（SIGINT / SIGTERM）

MCP server 收到信号时的 shutdown 顺序：

1. `workerService.stopAll()` — 停止所有 task poller（graceful，等待 in-flight polls 完成）
2. 查询 DB 中所有 `status=online` 的 monitors
3. 并发调用 analytics `POST /sources/{id}/pause`（超时 3s，失败静默）
4. 批量将 DB 中对应 monitors 标记为 `status=offline`
5. 停止 events webhook endpoint
6. 关闭 DB 连接
7. `process.exit(0)`

---

## 3. 启动时对账

MCP server 启动时（DB 初始化之后，在接受请求之前）执行 `reconcileOnStartup()`：

**前提**：MCP server 不自动启动任何 monitor（无 auto-start 机制）。DB 中 `status=online` 的记录只可能来自上次 crash（未走 graceful shutdown）。

```
1. GET /sources（获取 analytics 当前所有 source）
   - 不可达 → logger.warn，跳过对账，不阻塞启动

2. 遍历 DB 中 status=online 的 monitors：
   a. analytics 存在 → DELETE analytics + DB 标记 offline
      logger.warn: "monitor {id} found in videostream-analytics ({url}) on startup,
                    deleted and marked offline — call register_source to restart"
   b. analytics 不存在 → DB 标记 offline
      logger.warn: "monitor {id} not found in videostream-analytics ({url}) after restart,
                    marked offline — call register_source to restart"

3. 遍历 analytics 中存在但 DB 不存在的 source（孤儿，以 DB 为准）：
   → DELETE analytics（fire-and-forget，失败只 warn）
   logger.info: "deleted orphan source {id} from videostream-analytics ({url})"

4. logger.info: "reconcile complete: {N} marked offline, {M} orphans deleted"
```

---

## 4. Webhook 事件协议

analytics 向 MCP server `POST http://localhost:3101/events` 发送事件，端口可通过 config 配置。

### 4.1 三种 event type

| type | DB 写入 | 说明 |
|------|---------|------|
| `motion` | `events`（motion_type=motion）+ `video_summary_tasks` | 运动检测触发 |
| `static` | `events`（motion_type=static）| 静止状态，不创建 task |
| `recording` | `recordings` | 录制段元数据 |

### 4.2 `motion` event payload

```json
{
  "sourceId": "cam_child",
  "type": "motion",
  "timestamp": "2026-06-25T14:30:45Z",
  "payload": {
    "event_file_path":    "/data/motion_events/cam_child/seg_00001.mp4",
    "summary_clip_input": "/data/motion_events/cam_child/seg_00001_input.mp4",
    "start_time":      "2026-06-25T14:30:30Z",
    "end_time":        "2026-06-25T14:30:45Z",
    "duration_seconds": 15.2,
    "prefilter_passed":     1,
    "prefilter_classes":    "[\"person\"]",
    "prefilter_confidence": 0.92,
    "trajectory_region":    "100,50,300,400"
  }
}
```

**Required**: `event_file_path`, `summary_clip_input`, `start_time`, `duration_seconds`

- `event_file_path`：原始视频片段 → 写入 `events.event_file_path`
- `summary_clip_input`：送给 video summary 服务的输入片段（crop 版本，若无 crop 则同原始）→ 写入 `video_summary_tasks.summary_clip_input`

**`video_summary_tasks.status` 写入规则**：
- `prefilter_passed` 不存在 → `status=pending`
- `prefilter_passed=1` → `status=pending`
- `prefilter_passed=0` → `status=ignored`（跳过 video summary）

### 4.3 `static` event payload

```json
{
  "sourceId": "cam_child",
  "type": "static",
  "timestamp": "2026-06-25T14:31:00Z",
  "payload": {
    "start_time":      "2026-06-25T14:30:45Z",
    "end_time":        "2026-06-25T14:31:00Z",
    "duration_seconds": 15.0
  }
}
```

**Required**: `start_time`, `duration_seconds`

### 4.4 `recording` event payload

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
    "file_size_bytes":  8192000
  }
}
```

**Required**: `recording_path`, `recording_start`, `recording_end`

### 4.5 Payload 合法性检查

MCP server 按 type 校验 required 字段，缺失时 `logger.warn` 并跳过对应 DB 写入（返回 HTTP 200，不抛 500），防止 malformed event 中断整条流水线。

---

## 5. analytics 侧 API 约定（已实现）

MCP server 调用以下 analytics RESTful 端点：

| Endpoint | Method | MCP server 调用场景 |
|----------|--------|---------------------|
| `/register_source` | POST | monitor 注册 |
| `/sources/{id}` | DELETE | monitor 注销 / 对账删除孤儿 |
| `/sources/{id}/status` | GET | 注册前状态探测（200=存在，404=不存在） |
| `/sources/{id}/pause` | POST | graceful shutdown / stop action |
| `/sources/{id}/resume` | POST | start action（当前对账未使用，所有 online 均 offline 处理） |
| `/sources` | GET | 启动对账获取全量 source 列表 |

---

## 6. [TODO: analytics-side] Keepalive 协议

待 analytics 侧实现后联调。约定：

- **Endpoint**: `POST /sources/{id}/keepalive`
- **MCP server 发送间隔**: 30s（`setInterval`，遍历 DB 中 online monitors）
- **Analytics 超时阈值**: 90s 未收到 keepalive → 自动 pause 该 source
- **MCP server 侧实现**：等 analytics 端就绪后在 `index.ts` 添加 keepalive interval

---

## 7. Corner Cases

| 场景 | 处理方式 |
|------|---------|
| analytics 不可达（`register_source`） | 直接抛出异常，不做任何 DB 变更 |
| analytics DELETE 失败（注册流程中） | 抛出异常，停止注册（DB 已更新，方便排查） |
| analytics DELETE 失败（`unregister` action） | 静默忽略，继续删除 DB 记录 |
| use_case_id 变更 | 必须先调 `unregister` 再 `register_source` |
| 对账时 analytics 不可达 | warn log，跳过对账，不阻塞启动 |
| 对账时孤儿 source DELETE 失败 | warn log，继续处理其他 source |
| in-flight poll + stop race | TaskPoller graceful async stop：`stopPolling()` await 当前 in-flight poll 完成后返回 |
