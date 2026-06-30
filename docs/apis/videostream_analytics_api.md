# videostream-analytics — HTTP API & Webhook Reference

> **Status**：覆盖 Phase 7 / Phase 8 / Phase 9 现状（截至 2026-06-30）。
> 配套文档：
> - 系统设计：[smartbuilding-video-design-2026.2.md](../smartbuilding-video-design-2026.2.md)（§7 Video Stream Analytics Microservice）
> - Getting Started / 端到端验证：[vsa-gsg.md](../vsa-gsg.md)
> - VSA → MCP webhook 的 MCP 端契约：[mcp_webhook_event_api.md](./mcp_webhook_event_api.md)
>
> 本文档是 **VSA 实际代码层** 的精确接口契约。任何契约层面变更（路由 / 字段 / 行为）必须同步更新本文件 + 对照源码 anchor 链接。

---

## 1. 服务概览

| 项目 | 值 | 来源 |
|---|---|---|
| 服务名 | `videostream-analytics` | `service.py:99` |
| 框架 | FastAPI（uvicorn） | `service.py` |
| 默认监听 | `0.0.0.0:8999` | [shared/config.py:95-97](../../videostream-analytics/shared/config.py#L95-L97) |
| 默认 webhook 目标 | `http://localhost:18800/events`（可被 `WEBHOOK_URL` env 或 `pipeline.webhook_url` 覆盖） | [shared/config.py:88-92](../../videostream-analytics/shared/config.py#L88-L92), [config.py:161-162](../../videostream-analytics/shared/config.py#L161-L162) |
| 控制面 | RESTful HTTP（本文档 §3）— MCP server 通过它注册 / 注销 / 心跳 source | [service.py](../../videostream-analytics/service.py) |
| 事件面 | VSA 主动 `POST <webhook_url>`（本文档 §4），envelope 与 MCP `events-endpoint.ts` 对齐 | [stream_monitor/rtsp_monitor.py:416-422](../../videostream-analytics/stream_monitor/rtsp_monitor.py#L416-L422) |
| Content-Type | 请求 / 响应均为 `application/json` | FastAPI 默认 |
| 字符编码 | UTF-8 | FastAPI 默认 |

**部署形态**：单实例长驻进程，进程内管理多个 RTSP source（每个 source 一组后台线程：motion pipeline + 可选 continuous recorder + keepalive watchdog daemon）。

---

## 2. 端点速查表

| Method | Path | 用途 | 鉴权 | 引入 | 详见 |
|---|---|---|---|---|---|
| GET | `/health` | liveness probe | 无 | Phase 6 | §3.1 |
| GET | `/sources` | 列出所有已注册 source（**裸数组**） | 无 | Phase 6 | §3.2 |
| GET | `/sources/{source_id}` | 单 source 详情 | 无 | Phase 6 | §3.3 |
| GET | `/sources/{source_id}/status` | 单 source 详情（别名，MCP `analyticsSourceExists` 使用） | 无 | Phase 7 | §3.3 |
| POST | `/register_source` | 注册并启动 source | 无 | Phase 7 嵌套 schema | §3.4 |
| DELETE | `/unregister_source` | 注销（body 形式） | 无 | Phase 6 | §3.5 |
| DELETE | `/sources/{source_id}` | RESTful 注销（path 形式，与 `unregister_source` 等价） | 无 | Phase 6 | §3.5 |
| POST | `/sources/{source_id}/stop` | 等价于 `DELETE /sources/{id}` | 无 | Phase 6 | §3.5 |
| POST | `/sources/{source_id}/restart` | 停 + 起 pipeline / recorder | 无 | Phase 6 | §3.6 |
| POST | `/sources/{source_id}/pause` | 暂停（保留 source） | 无 | Phase 6 | §3.7 |
| POST | `/sources/{source_id}/resume` | 恢复 | 无 | Phase 6 | §3.7 |
| POST | `/sources/{source_id}/keepalive` | 心跳（Phase 8） | 无 | Phase 8 | §3.8 |
| PUT | `/sources/{source_id}/pipeline` | 热更新 pipeline 配置（嵌套 schema） | 无 | Phase 7 | §3.9 |

**鉴权**：VSA 当前**不做鉴权**。生产部署需要在 LAN 内 / 反向代理上做网络隔离。

---

## 3. 控制面 Endpoint 详解

所有响应均为 JSON，HTTP 状态码遵循下列约定：

| 状态码 | 含义 |
|---|---|
| 200 | 操作成功（含幂等的"already_running" / "not_running"） |
| 404 | source 不存在 |
| 422 | 请求体 schema 校验失败（`extra="forbid"` 拒绝未知字段、缺必填字段等）— 见 §5 错误格式 |
| 500 | 服务端内部异常（pydantic 之外的不可恢复错误） |

---

### 3.1 `GET /health`

Liveness probe。

**请求**：无 body。

**响应 200**：
```json
{ "status": "ok", "service": "videostream-analytics" }
```

源码：[service.py:132-134](../../videostream-analytics/service.py#L132-L134)。

---

### 3.2 `GET /sources`

列出当前进程内所有已注册 source。**返回裸数组**（不是 `{"sources":[...]}` 包装）—— 这是 Phase 7 硬切换的契约。

**请求**：无 body。

**响应 200**：`array<SourceStatus>`（schema 见 §3.3）。

```json
[
  {
    "source_id": "cam_demo",
    "source_url": "rtsp://localhost:8554/live/child",
    "data_dir": "/data/cam_demo",
    "status": "online",
    "running": true,
    "recording_enabled": true,
    "health": { "...": "..." },
    "keepalive_enabled": false,
    "last_keepalive_at": null
  }
]
```

源码：[service.py:136-138](../../videostream-analytics/service.py#L136-L138)；元素由 [`SourceManager._describe_bundle`](../../videostream-analytics/source_worker.py#L261-L279) 生成。

---

### 3.3 `GET /sources/{source_id}` 与 `GET /sources/{source_id}/status`

返回单个 source 的完整状态。两路径**调用同一个 handler**，返回结构完全一致。

MCP 的 `analyticsSourceExists` 走 `/sources/{id}/status`（Phase 7 起的契约）。

**路径参数**：`source_id` — 注册时使用的 id。

**响应 200**（`SourceStatus` schema）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `source_id` | string | 同路径参数 |
| `source_url` | string | RTSP URL（注册时给的） |
| `data_dir` | string | 该 source 的产出根目录绝对路径 |
| `status` | string | pipeline 当前 lifecycle 状态：`connecting` / `online` / `paused` / `unhealthy` / `reconnecting` / `error` / `removed` / `stopped` |
| `running` | boolean | 后台线程是否在跑 |
| `recording_enabled` | boolean | continuous recorder 是否在该 source 上启用 |
| `health` | object | 健康信息子对象（详见下表） |
| `keepalive_enabled` | boolean | 该 source 的 keepalive watchdog 是否启用（Phase 8） |
| `last_keepalive_at` | string \| null | 上次 keepalive 的 ISO8601 UTC 时间；keepalive 未启用时为 null |

**`health` 子对象**（来自 [rtsp_monitor.py:177-187](../../videostream-analytics/stream_monitor/rtsp_monitor.py#L177-L187)）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `failure_count` | int | RTSP 读取失败累计次数（重连成功后归零） |
| `last_failure_time` | string \| null | 上次失败 ISO8601 |
| `reconnect_count` | int | 重连成功次数 |
| `recovery_strategy` | string | `retry` / `pause` / `remove`（注册时来自 `pipeline.health.recovery_strategy`） |
| `max_failures` | int | 触发策略前允许的失败次数 |
| `start_time` | string \| null | pipeline 启动 ISO8601 |

**响应 404**：source 未注册：
```json
{ "detail": "Source not found: cam_xxx" }
```

源码：[service.py:147-154](../../videostream-analytics/service.py#L147-L154)。

---

### 3.4 `POST /register_source`

注册一个新 source 并启动后台 pipeline。**幂等**：对已注册且 running 的 id 重复调返回 `already_running` 而不报错。

#### 请求体（`RegisterSourceRequest`，`extra="forbid"`）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `source_id` | string | ✅ | 唯一标识 |
| `source_url` | string | ✅ | RTSP URL（VSA 从该 URL 拉流） |
| `webhook_url` | string \| null | ❌ | 覆盖该 source 的事件 webhook 目标；省略时回退到全局 `webhook.url` |
| `data_dir` | string \| null | ❌ | 该 source 的产出根目录绝对路径；省略时落到 `<config.data_dir>/<source_id>/` |
| `pipeline` | `PipelineConfig` | ❌ | 嵌套 pipeline 配置（见下） |

**Phase 7 硬切换**：旧的"平铺" body（顶层 `rtsp_url` / `motion` / `use_case` 等）会被 `extra="forbid"` 拒绝并返回 422（带 `unknown_fields` 列表）。

#### `PipelineConfig`（嵌套 schema，`extra="forbid"`）

所有子块均为可选；省略时**整体回退**到 `defaults.<sub_block>`（注意：是整块回退而非字段级合并，参见 `test_prefilter_config_contract.py`）。

| 子块 | 模型 | 默认 | 说明 |
|---|---|---|---|
| `motion` | `MotionConfig` | `defaults.motion` | 帧差法 motion 触发参数 |
| `segment` | `SegmentConfig` | `defaults.segment` | motion clip 切片间隔 |
| `prefilter` | `PrefilterConfig` | `defaults.prefilter` | NPU YOLO 后筛（含 Phase 9 `roi_crop` 子块） |
| `recording` | `RecordingConfig` | `defaults.recording` | 固定时长 continuous recording 支路 |
| `health` | `HealthConfig` | `defaults.health` | RTSP 失败处理策略 |
| `keepalive` | `KeepaliveConfig` | `defaults.keepalive` | Phase 8 心跳协议 |

#### 各子块字段表

**`MotionConfig`**（[shared/config.py:13-17](../../videostream-analytics/shared/config.py#L13-L17)）：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `enabled` | bool | `true` | 关闭后不再进 motion 检测路径 |
| `diff_threshold` | int | `25` | 帧差像素阈值（越小越敏感） |
| `area_ratio` | float | `0.015` | 触发 motion 的最小帧面积比 |
| `stable_frames` | int | `30` | 连续静止帧数判定 motion 结束 |

**`SegmentConfig`**（[shared/config.py:20-22](../../videostream-analytics/shared/config.py#L20-L22)）：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `interval` | float | `10.0` | clip 切片间隔（秒） |
| `min_duration` | float | `1.0` | 低于该时长的尾部 clip 直接丢弃 |

**`PrefilterConfig`**（[shared/config.py:56-64](../../videostream-analytics/shared/config.py#L56-L64)）：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `enabled` | bool | `false` | 开启后用 OpenVINO YOLO 筛 motion clip |
| `model_path` | string | `""` | OpenVINO model `.xml` 路径（绝对路径） |
| `target_classes` | array<string> | `["person"]` | 命中即视为有效 |
| `min_confidence` | float | `0.4` | 检测最低置信度 |
| `min_frames_hit` | int | `2` | 累计命中帧数 ≥ 该值 → PASS |
| `detect_fps` | float | `2.0` | YOLO 推理频率（不是每帧都跑） |
| `device` | string | `"CPU"` | OpenVINO 设备（CPU / GPU / NPU） |
| `roi_crop` | `RoiCropConfig` \| null | `null` | Phase 9：trajectory + ROI crop（见下） |

**`RoiCropConfig`**（Phase 9，[shared/config.py:40-53](../../videostream-analytics/shared/config.py#L40-L53)）：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `enabled` | bool | `false` | 开启后 prefilter PASS 时生成 `<clip>_input.mp4`，并发 `trajectory_region` payload |
| `mode` | string | `"crop"` | `crop`（裁 union 区域）/ `highlight`（全画面 + 高亮框）/ `crop_and_concat`（左原图 + 右逐帧 person crop） |
| `expand` | float | `0.25` | union bbox 向外扩展比例 |
| `auto_split_area` | float | `0.0` | union 面积 > 阈值时提前切 segment；0 表示禁用 |

**`RecordingConfig`**（[shared/config.py:25-37](../../videostream-analytics/shared/config.py#L25-L37)）：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `enabled` | bool | `true` | 开启 continuous recorder（独立于 motion） |
| `interval_seconds`（别名 `interval`） | int | `60` | 单段录像时长 |
| `fps` | int | `15` | 录像输出 fps |
| `retention_days` | int | `5` | 旧片段保留天数（VSA 自动清） |

**`HealthConfig`**（[shared/config.py:67-72](../../videostream-analytics/shared/config.py#L67-L72)）：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `max_failures` | int | `30` | 触发恢复策略前允许的连续失败次数 |
| `recovery_strategy` | string | `"retry"` | `retry` 指数退避重连 / `pause` 自动暂停 / `remove` 自动注销 |
| `backoff_base` | float | `2.0` | 重连退避基数（秒） |
| `backoff_max` | float | `120.0` | 重连退避上限（秒） |

**`KeepaliveConfig`**（Phase 8，[shared/config.py:75-85](../../videostream-analytics/shared/config.py#L75-L85)）：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `enabled` | bool | `false` | 开启后 source 必须周期收到 `POST /sources/{id}/keepalive` |
| `timeout_seconds` | float | `90.0` | 超过该时长无 keepalive 自动 pause |
| `check_interval_seconds` | float | `10.0` | watchdog 巡检间隔 |

#### 完整请求示例

```json
{
  "source_id":   "cam_child",
  "source_url":  "rtsp://localhost:8554/live/child",
  "webhook_url": "http://localhost:3101/events",
  "data_dir":    "/data/cam_child",
  "pipeline": {
    "motion":    { "diff_threshold": 15, "area_ratio": 0.005, "stable_frames": 45 },
    "segment":   { "interval": 10, "min_duration": 1.0 },
    "prefilter": {
      "enabled": true,
      "model_path": "/models/openvino/yolo11s/FP16/yolo11s.xml",
      "target_classes": ["person"],
      "detect_fps": 2.0,
      "device": "NPU",
      "roi_crop": { "enabled": true, "mode": "crop", "expand": 0.25, "auto_split_area": 0.35 }
    },
    "recording": { "enabled": true, "interval_seconds": 60, "retention_days": 5 },
    "health":    { "max_failures": 30, "recovery_strategy": "retry" },
    "keepalive": { "enabled": true, "timeout_seconds": 90.0, "check_interval_seconds": 10.0 }
  }
}
```

#### 响应

**200 OK** — 三种 `status`：

```json
// 1) 全新注册
{ "status": "started", "source_id": "cam_child",
  "source_url": "rtsp://localhost:8554/live/child",
  "data_dir": "/data/cam_child" }

// 2) 已注册且 running（幂等）
{ "status": "already_running", "source_id": "cam_child" }

// 3) 已注册但已停止 → 自动重建（旧 bundle 被 teardown）
{ "status": "started", "source_id": "cam_child", ... }
```

**422** — schema 校验失败，body 见 §5。

源码：[service.py:158-173](../../videostream-analytics/service.py#L158-L173)，调用 [`SourceManager.register_source`](../../videostream-analytics/source_worker.py#L54-L105)。

---

### 3.5 `DELETE /unregister_source` / `DELETE /sources/{source_id}` / `POST /sources/{source_id}/stop`

三个端点**语义等价**——停掉 pipeline + recorder + 关闭 per-source webhook sink，从 `_bundles` 中移除。**不删除 `data_dir`**（retention 由 MCP 端控制）。

| 端点 | 形式 | 备注 |
|---|---|---|
| `DELETE /unregister_source` | body 形式 `{"source_id": "..."}` | 历史端点 |
| `DELETE /sources/{source_id}` | path 形式 | MCP 启动对账 `reconcileOnStartup` 用 |
| `POST /sources/{source_id}/stop` | path 形式 | 与 DELETE 等价；某些客户端不便发 DELETE 用此 |

**响应 200**：
```json
{ "status": "stopped", "source_id": "cam_child" }
```

**响应 404**：source 未注册。

源码：[service.py:175-191](../../videostream-analytics/service.py#L175-L191), [253-258](../../videostream-analytics/service.py#L253-L258)。

---

### 3.6 `POST /sources/{source_id}/restart`

停 + 起 pipeline 和（如启用）recorder。**保留** `_bundles` 中的 SourceBundle、保留 sink。

**响应 200**：
```json
{ "status": "restarted", "source_id": "cam_child" }
```

**响应 404**：未注册。

源码：[service.py:193-207](../../videostream-analytics/service.py#L193-L207)。

---

### 3.7 `POST /sources/{source_id}/pause` 与 `/resume`

`pause` 把 pipeline 切到 `paused` 状态（停止抓帧、停止 motion 检测、停止 webhook 推送），但保留 RTSP 连接 fd 和 source 注册。`resume` 恢复。

**幂等**：对 `not_running` 的 source pause 返回 `{"status":"not_running"}`（200）。

**响应 200**：
```json
// pause
{ "status": "paused", "source_id": "cam_child" }
// resume
{ "status": "online", "source_id": "cam_child" }
```

**响应 404**：未注册。

副作用：均发一个 `type="status"` 的 webhook 事件，payload `{"status":"paused"}` / `{"status":"online"}`，见 §4.4。

源码：[service.py:209-223](../../videostream-analytics/service.py#L209-L223), 触发处 [rtsp_monitor.py:124, 132](../../videostream-analytics/stream_monitor/rtsp_monitor.py#L124-L132)。

---

### 3.8 `POST /sources/{source_id}/keepalive` （Phase 8）

MCP server 端每 ~30s 调用一次，VSA 内部刷新 `last_keepalive_at = now`。后台 watchdog daemon 每 `check_interval_seconds` 巡检：超过 `timeout_seconds` 没收到 keepalive **自动 pause** 该 source（不删除，需 MCP 显式 `/resume`）。

**默认 OFF**（`keepalive.enabled=false`）—— MCP 必须在注册 body 里显式 `pipeline.keepalive.enabled=true` 才生效，避免破坏 V1–V10 联调脚本节奏。

**请求**：body 可为空 / `{}` / 任意 JSON 都被忽略。

**响应 200**：
```json
{
  "status": "ok",
  "source_id": "cam_child",
  "last_keepalive_at": "2026-06-30T12:34:56.789012+00:00"
}
```

**响应 404**：source 未注册。

**Pause 语义**：watchdog 触发的 pause 复用 `pause_source()` 路径，发同样的 `type=status, payload={status:paused}` envelope。源代码：[source_worker.py:235-247](../../videostream-analytics/source_worker.py#L235-L247) + watchdog loop [281-321](../../videostream-analytics/source_worker.py#L281-L321)。

**Grace period**：注册时若 `keepalive.enabled=true` 则 `last_keepalive_at` 初始化为 `now()`，给 MCP 留 `timeout_seconds` 的缓冲时间发第一次心跳。

---

### 3.9 `PUT /sources/{source_id}/pipeline`

热更新 pipeline 配置（不需要先 unregister）。**整体替换语义**：传入 `pipeline.motion` 整块覆盖，未传子块则保留原配置。

**请求体**：`UpdatePipelineRequest`（`extra="forbid"`）—— 包装一层 `pipeline` 字段，内部就是 `PipelineConfig`：

```json
{
  "pipeline": {
    "motion": { "diff_threshold": 10 },
    "recording": { "enabled": false }
  }
}
```

**响应 200**：
```json
{ "status": "updated", "source_id": "cam_child" }
```

**响应 404 / 422**：同 `/register_source`。

副作用：pipeline 会 stop + apply + start；recording 启停切换会创建 / 销毁 ContinuousRecorder。

源码：[service.py:238-251](../../videostream-analytics/service.py#L238-L251)。

---

## 4. 事件面 — VSA → 下游 Webhook

VSA 向 `webhook_url` 主动 `POST` 的事件，**MCP `events-endpoint.ts` 已对齐为嵌套 envelope**：

### 4.1 通用 envelope

```json
{
  "sourceId":  "cam_child",
  "type":      "motion | recording | status",
  "timestamp": "2026-06-30T14:30:15",
  "payload":   { ... }
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `sourceId` | string | 注册时的 `source_id`（注意 camelCase） |
| `type` | string | `motion` / `recording` / `status` 之一 |
| `timestamp` | string | ISO8601（秒精度，本地时区） |
| `payload` | object | 由 `type` 决定的子结构 |

> **注**：design §9.2 表里写过 `static` type，但 VSA 当前实现**不发送** `static` 事件（仅 motion / recording / status 三种）。MCP 端的 `case "static"` 是预防性代码，未来如果需要"静止时段"特征再引入。

### 4.2 `type=motion` payload

由 [`_emit_segment`](../../videostream-analytics/stream_monitor/rtsp_monitor.py#L429-L488) 发出。motion 触发 → 写 mp4 → prefilter PASS 则 emit；prefilter SKIP 时 clip 会被 `os.remove`，**不会发**这个事件。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `event_file_path` | string | ✅ | 原始 motion 片段绝对路径（`<data_dir>/motion_events/<YYYY-MM-DD>/*.mp4`） |
| `summary_clip_input` | string | ✅ | 供 VLM 消费的视频路径；prefilter PASS + `roi_crop.enabled` 时为 `<stem>_input.mp4`，否则 = `event_file_path` |
| `start_time` | string | ✅ | clip 起始时间 ISO8601 |
| `end_time` | string | ❌ | clip 结束时间 ISO8601 |
| `duration_seconds` | float | ✅ | clip 时长（秒） |
| `prefilter_passed` | int (0/1) | ❌ | 仅 prefilter 启用时存在；0 时该 clip 不会 emit（见上） |
| `prefilter_classes` | string | ❌ | JSON string of `list[str]`，命中的 YOLO 类名 |
| `prefilter_confidence` | float | ❌ | 该 clip 内 YOLO 检测最大置信度 |
| `trajectory_region` | string | ❌ | **Phase 9 起**：JSON string `"[x0,y0,x1,y1]"`，4 个 ∈ [0,1] 的归一化坐标；prefilter 累计 union bbox 的结果 |

**MCP 侧消费**：见 [mcp_webhook_event_api.md](./mcp_webhook_event_api.md) 或 [events-endpoint.ts:139-145](../../packages/mcp-server/src/events-endpoint.ts#L139-L145)。

### 4.3 `type=recording` payload

由 [`ContinuousRecorder._record_loop`](../../videostream-analytics/stream_monitor/continuous_recorder.py#L157-L169) 在每段固定时长录像写盘后发出。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `recording_path` | string | ✅ | 录像段绝对路径（`<data_dir>/recordings/<YYYY-MM-DD>/*.mp4`） |
| `recording_start` | string | ✅ | 段起始时间 ISO8601 |
| `recording_end` | string | ✅ | 段结束时间 ISO8601 |
| `duration_seconds` | float | ❌ | 实际时长（与 `interval_seconds` 略有偏差） |
| `file_size_bytes` | int | ❌ | 文件字节数 |

### 4.4 `type=status` payload

由 [`_emit_status`](../../videostream-analytics/stream_monitor/rtsp_monitor.py#L490-L492) 与若干 inline `_emit_envelope("status", ...)` 调用发出。MCP 当前忽略未知 type，但事件仍会被 envelope 包装发出。

`payload.status` 取值：

| 值 | 触发点 | 附加字段 |
|---|---|---|
| `paused` | pause action / watchdog auto-pause / health 策略 pause | — |
| `online` | resume action / 重连恢复 | — |
| `unhealthy` | 连续失败超 `max_failures` | `reason`: e.g. `"rtsp_timeout"` |
| `reconnecting` | 重连退避中 | — |
| `stopped` | source 注销 | — |

示例：
```json
{ "sourceId": "cam_child", "type": "status",
  "timestamp": "2026-06-30T14:31:00",
  "payload": { "status": "unhealthy", "reason": "rtsp_timeout" } }
```

---

## 5. 错误响应

### 5.1 404 — Source not found

普通 `HTTPException(404)`：
```json
{ "detail": "Source not found: cam_xxx" }
```

### 5.2 422 — Schema 校验失败（含 `extra="forbid"`）

VSA 用 [自定义 RequestValidationError handler](../../videostream-analytics/service.py#L107-L128) 把 pydantic 错误转译为更可读的 422，附带 `unknown_fields` 列表与 hint：

```json
{
  "detail": [
    { "type": "extra_forbidden", "loc": ["body", "rtsp_url"], "...": "..." },
    { "type": "extra_forbidden", "loc": ["body", "motion"], "...": "..." }
  ],
  "unknown_fields": ["rtsp_url", "motion"],
  "hint": "request body must match the nested-pipeline schema (source_id/source_url/webhook_url/data_dir/pipeline.{motion,segment,prefilter,recording,health})"
}
```

`unknown_fields` 数组**只列**被 `extra="forbid"` 拒绝的字段；其他 422（缺必填、类型错）`unknown_fields` 为空，详情在 `detail` 里。

---

## 6. 数据目录约定

VSA 按 `pipeline.data_dir` 落盘，**与 MCP 端的 `storage.retention_days` 清理器对齐**：

```
<data_dir>/
├── latest.jpg                          # 周期写入的快照（MCP latest-frame resource 读这里）
├── motion_events/<YYYY-MM-DD>/         # motion clip
│   ├── <source_id>_HHMMSS.mp4          # 原片，对应 webhook payload.event_file_path
│   └── <source_id>_HHMMSS_input.mp4    # ROI cropped 片段，payload.summary_clip_input（Phase 9）
└── recordings/<YYYY-MM-DD>/            # 固定时长录像（独立于 motion）
    └── <source_id>_HHMMSS.mp4          # 对应 webhook payload.recording_path
```

**清理职责**：
- `motion_events/` / `recordings/` 旧日期目录 — 由 **MCP server** 按 `storage.retention_days` 清理。
- `latest.jpg` — VSA 自身覆盖写，无需清理。

VSA **不**主动删除 `data_dir`；source 注销时只停 pipeline，目录保留。

---

## 7. 端口与环境变量

| Env / Config | 默认 | 说明 |
|---|---|---|
| `server.host` / `server.port` | `0.0.0.0:8999` | VSA 自己监听 |
| `webhook.url`（或 env `WEBHOOK_URL`） | `http://localhost:18800/events` | 默认 webhook 目标（per-source `webhook_url` 优先） |
| `data_dir`（或 env `RECORDINGS_DIR`） | `~/.smartbuilding/data` | 全局 data_dir 根；register 体里 `data_dir` 字段优先 |
| `VIDEOSTREAM_CONFIG` | `config/config.yaml` | 自定义 config 文件路径 |
| `OV_CACHE_DIR` | `/tmp/ov_cache` | OpenVINO 模型缓存（YoloPrefilter 用） |

集成测试 / 本地联调对应端口（来自 vsa-gsg.md / tests/integration/conftest.py）：
- `:8554` — MediaMTX RTSP server
- `:8999` — VSA 自己（本服务）
- `:9999` — mock webhook（测试用，仿 MCP `:3101`）
- `:3101` — 真 MCP `events-endpoint`（生产）

---

## 8. 版本与变更历史（按 Phase）

| Phase | 关键改动 | 引入 endpoint / 字段 |
|---|---|---|
| **Phase 7** 接口硬切换 | 嵌套 `pipeline` schema；`source_url`（不再是 `rtsp_url`）；移除 `use_case`；`GET /sources` 返回裸数组；新增 `/sources/{id}/status` 路径；webhook envelope 改嵌套 `{sourceId,type,timestamp,payload}` | §3.4, §3.3, §4 |
| **Phase 8** keepalive | `POST /sources/{id}/keepalive`；`KeepaliveConfig` 子块；watchdog daemon；`SourceStatus` 加 `keepalive_enabled / last_keepalive_at` | §3.8 |
| **Phase 9** trajectory + ROI crop | `PrefilterConfig.roi_crop`；motion payload 加 `trajectory_region`；自动生成 `<clip>_input.mp4`；`summary_clip_input` 智能切换；`auto_split_area` 早切 | §3.4 RoiCropConfig, §4.2 |

---

## 9. 实际运行验证

完整 V1–V12 手动验证脚本与脚本式自动测试见 [vsa-gsg.md §6 / §6.5 / §7](../vsa-gsg.md)：
- 单元测试 185 用例（`pytest tests/unit/`）
- 集成测试 27 用例（`pytest tests/integration/ -m integration`，需要 mediamtx + mock webhook + ffmpeg）
- V1–V12 手动 curl 路径（依次覆盖 `/health` 探活 → register → 三态切换 → motion / recording → 健康策略 → CLI → 接真 MCP → keepalive → trajectory + ROI crop）

---

## 附录 A：与 MCP 端契约对齐核对

| MCP 端调用 | 对应 VSA endpoint | 状态 |
|---|---|---|
| `analyticsRegister` | `POST /register_source` | ✅ 嵌套 schema 一致 |
| `analyticsSourceExists` | `GET /sources/{id}/status` | ✅ |
| `analyticsDelete` | `DELETE /sources/{id}` | ✅ |
| `analyticsPause` | `POST /sources/{id}/pause` | ✅ |
| `analyticsResume` | `POST /sources/{id}/resume` | ✅ |
| `analyticsListSources` | `GET /sources` | ✅ 裸数组 |
| keepalive（MCP 端发送循环） | `POST /sources/{id}/keepalive` | ⚠️ VSA 已就绪；MCP `index.ts` 端的 setInterval 还没接入 |
| webhook 接收 motion / recording / status | VSA `POST <webhook_url>` | ✅ envelope 一致 |
| `latest-frame` resource | VSA 写 `<data_dir>/latest.jpg` | ⚠️ VSA 已写；MCP `resources.ts:28` 仍是 stub（return `frame: null`） |
