# Videostream Analytics Microservice — 实现说明

本文档对应 [videostream-analytics/](../../videostream-analytics/) 目录下的实际代码，说明该微服务的模块划分、运行形态、以及与 MCP server 的契约边界。它是 design 文档 [§7 Video Stream Analytics Microservice](../smartbuilding-video-design-2026.2.md) 的实现侧对齐说明；用户手册与端到端联调步骤见 [vsa-gsg.md](../vsa-gsg.md)，HTTP + Webhook 契约细节见 [apis/videostream_analytics_api.md](../apis/videostream_analytics_api.md)。

---

## 更新历史

| 版本 | 日期 | 更新人 | 说明 |
|------|------|--------|------|
| v0.3 | 2026-07-01 | Li, Jie6 | Phase 9：`prefilter.roi_crop` 子块 + `trajectory_region` webhook 字段 + `<clip>_input.mp4` 自动生成 + `auto_split_area` 早切 |
| v0.2 | 2026-06-30 | Li, Jie6 | Phase 8：`POST /sources/{id}/keepalive` + watchdog 自动 pause + `keepalive_enabled` / `last_keepalive_at` 状态字段 |
| v0.1 | 2026-06-29 | Li, Jie6 | Phase 7：嵌套 `pipeline` 注册 schema；`source_url` 取代 `rtsp_url`；`GET /sources` 裸数组；webhook envelope 改嵌套 `{sourceId,type,timestamp,payload}` |

---

## 目录

- [1. 服务定位与部署形态](#1-服务定位与部署形态)
- [2. 目录结构](#2-目录结构)
- [3. 处理链路](#3-处理链路)
  - [3.1 Motion pipeline](#31-motion-pipeline)
  - [3.2 NPU YOLO Prefilter](#32-npu-yolo-prefilter)
  - [3.3 ROI Crop + Trajectory（Phase 9）](#33-roi-crop--trajectoryphase-9)
  - [3.4 Continuous Recorder（固定时长录像分支）](#34-continuous-recorder固定时长录像分支)
  - [3.5 Latest-frame Snapshot](#35-latest-frame-snapshot)
- [4. Source 生命周期状态机](#4-source-生命周期状态机)
- [5. HTTP 控制面](#5-http-控制面)
- [6. Webhook 事件面](#6-webhook-事件面)
- [7. 配置与默认值](#7-配置与默认值)
- [8. 数据目录约定](#8-数据目录约定)
- [9. Health Watchdog + Keepalive（Phase 8）](#9-health-watchdog--keepalivephase-8)
- [10. 测试策略](#10-测试策略)
- [11. 与 MCP server 的契约点](#11-与-mcp-server-的契约点)

---

## 1. 服务定位与部署形态

`videostream-analytics` 是 SmartBuilding Video 系统里唯一直接与 RTSP 打交道的组件。作用：从 RTSP 源拉流 → 帧差法运动检测 → 可选 NPU YOLO 后筛 → 将符合条件的片段切成 MP4 → 通过 HTTP webhook 推送事件给下游（生产环境是 MCP server `/events`，测试环境是 mock）。

**部署形态**：单一长驻进程（Python + uvicorn），进程内以多线程方式并发管理任意数量的视频源（每个 source 一组后台线程：motion pipeline + 可选 continuous recorder），并共享一个 keepalive watchdog daemon。可选 Docker 镜像 `videostream-analytics:latest`（`network_mode: host`，对外端口固定 `8999`）。

**核心设计原则**：

- **控制面 vs 事件面分离**。控制面（HTTP RESTful，`0.0.0.0:8999`）供 MCP server 调；事件面（VSA 主动 `POST <webhook_url>`）单向出站。两条路径互不阻塞。
- **无鉴权**。假定运行在受信任网段（loopback / 内网 / 反向代理后面）。
- **无状态注册**。所有 source 状态保存在内存 `SourceManager._bundles` dict 中；进程重启需要外部（MCP server）重新调 `/register_source`。这个设计允许 VSA 独立崩溃与重启，只要 MCP server 做过对账。
- **契约先行**。每个契约面（register body、webhook envelope、状态字段）都由 pydantic `extra="forbid"` 强制，未知字段一律 422，避免"客户端多传一个字段被静默忽略"的漂移。

---

## 2. 目录结构

对应 [videostream-analytics/](../../videostream-analytics/) 的实际代码布局：

```
videostream-analytics/
├── service.py                                # FastAPI app / lifespan / route table
├── source_worker.py                          # SourceManager, SourceBundle, watchdog
├── cli.py                                    # `serve` / `stream` / `health` 三命令入口
├── __main__.py                               # python -m videostream-analytics
├── shared/
│   ├── config.py                             # AppConfig + 全部 pydantic 模型
│   ├── logger.py                             # 统一 logger（StreamHandler → stdout）
│   ├── time_utils.py                         # ISO 8601 helpers
│   └── webhook_client.py                     # HTTP POST + retry / timeout
├── sinks/                                    # EventSink 抽象
│   ├── base.py                               # abstract `emit(event) -> bool`
│   ├── webhook.py                            # WebhookSink（生产）
│   ├── stdout.py                             # StdoutSink（CLI 调试）
│   └── null.py                               # NullSink（测试）
├── stream_monitor/
│   ├── base_monitor.py                       # BaseMonitor（线程生命周期共用逻辑）
│   ├── rtsp_monitor.py                       # StreamPipeline（motion 主状态机）
│   ├── continuous_recorder.py                # ContinuousRecorder（固定时长分支）
│   └── pipeline/
│       ├── motion_detector.py                # 帧差 + 面积比检测
│       ├── motion_state.py                   # 静止帧计数器
│       ├── segment_extractor.py              # add_frame() 组装 clip
│       ├── prefilter_yolo.py                 # YoloPrefilter + FramePrefilter
│       ├── roi.py                            # ROI 数据结构
│       └── roi_processor.py                  # prepare_roi_segment（Phase 9）
├── config/
│   └── config.yaml                           # 默认配置
├── docker/
│   ├── Dockerfile                            # OpenCV + OpenVINO + NPU 驱动
│   └── docker-compose.yaml
├── tests/
│   ├── unit/                                 # 15 个用例文件，共 185 assertions
│   └── integration/                          # 6 个用例文件，共 27 assertions
├── scripts/                                  # 联调辅助脚本
└── pyproject.toml
```

**与 design §7.1 的偏差**：

- 实际结构比 design 多了 `pipeline/roi_processor.py`（Phase 9）与 `pipeline/roi.py`。
- design 示意里 `sinks/webhook.py` / `stdout.py` / `null.py` 三个文件真实存在，但当前 `WebhookSink` 已抽象出重试策略（放到 `shared/webhook_client.py`）。
- design 里的 `cli.py` 在项目根路径而非子模块内部，与实际一致。

---

## 3. 处理链路

单个 source 从注册到 emit 事件的完整链路：

```
POST /register_source
       │
       ▼
SourceManager.register_source(SourceConfig)      ← service.py:158-173 → source_worker.py:67-107
       │
       ▼
构造 SourceBundle {pipeline, recorder?, sink, keepalive, last_keepalive_at}
       │
       ├─────────────► StreamPipeline (motion 主线程)      ← stream_monitor/rtsp_monitor.py
       │                    │
       │                    ▼
       │                connect RTSP → read frames → MotionDetector.detect()
       │                    │
       │                    │  motion started
       │                    ▼
       │                SegmentExtractor 缓存帧、可选调 FramePrefilter.accumulate()
       │                    │
       │                    │  interval 到 or motion 结束 or should_split
       │                    ▼
       │                extractor.finish() 写 mp4 → _maybe_emit()
       │                    │
       │                    │  prefilter PASS 且 roi_crop.enabled?
       │                    ▼
       │                prepare_roi_segment() 写 <clip>_input.mp4（可选）
       │                    │
       │                    ▼
       │                _emit_envelope("motion", payload)
       │                    │
       │                    ▼
       │                sink.emit(envelope) → WebhookSink → POST <webhook_url>
       │
       └─────────────► ContinuousRecorder (可选，独立线程)  ← stream_monitor/continuous_recorder.py
                             │
                             ▼
                         按 interval_seconds 切段写 mp4 → sink.emit("recording", payload)
```

以下小节按数据流顺序展开。

### 3.1 Motion pipeline

主状态机在 [`StreamPipeline._run()`](../../videostream-analytics/stream_monitor/rtsp_monitor.py) `_run()` + `_process_loop()`：

- **连接**：`cv2.VideoCapture(source_url)`，失败进入 §4 状态机的 `error` 分支。
- **帧读取**：主线程阻塞在 `cap.read()`；`_paused.is_set()` 为 false 时跳过后续处理但保留 RTSP 连接（避免 idle-timeout 被 MediaMTX kick）。
- **motion 检测**：`MotionDetector.detect(frame)` 用高斯模糊 + `cv2.absdiff` + 二值化 + 轮廓面积比得到 `motion_detected`；`MotionState` 统计连续静止帧（`stable_frames`），达到阈值判定 motion 结束。
- **segment 组装**：`SegmentExtractor` 在 `motion_started` 时打开 `VideoWriter` 写 mp4；每帧 `add_frame(frame)` 返回 `SegmentResult` 表示"到 `interval` 秒了，切一段"；`finish()` 返回尾段。
- **min_duration 过滤**：<1 s 的尾段直接 `os.unlink`，避免 emit 太碎的片段。

参数：`MotionConfig.diff_threshold=25` / `area_ratio=0.015` / `stable_frames=30`；`SegmentConfig.interval=10.0` / `min_duration=1.0`。

### 3.2 NPU YOLO Prefilter

可选，[`stream_monitor/pipeline/prefilter_yolo.py`](../../videostream-analytics/stream_monitor/pipeline/prefilter_yolo.py) 实现。

- **`YoloPrefilter`**：`__init__` 加载 OpenVINO IR 模型（`.xml`），`predict(frame)` 每次推理返回目标类别检测结果（列表 of `{name, conf, xyxy}`，坐标已按 infer 尺寸归一化到 `[0,1]`）。
- **`FramePrefilter`**（帧累加器）：`accumulate(frame, src_fps)` 按 `detect_fps` 频率抽帧推理，累计 `frame_hits` 与 `max_confidence`；`result()` 返回 `PrefilterResult(passed, hit_classes, frame_hits, max_confidence, trajectory_region_xyxy)`。
- **PASS 判定**：`frame_hits >= min_frames_hit`（默认 2）→ `passed=true`。
- **SKIP 处理**：`_maybe_emit()` 里若 `not pf_result.passed` 直接 `os.remove(clip)` 并 return，**不发** motion 事件。这是"节省 VLM 算力"的关键：只把有 person 的 clip 送去汇总。

**配置解耦**：`PrefilterConfig.enabled=false` 默认，`min_confidence=0.4`、`detect_fps=2.0`、`device="CPU"`（生产设 `NPU`）。模型文件不存在时 pipeline 会 graceful degrade 为"prefilter 禁用"，不中断流式处理（见 [test_prefilter_config_contract.py](../../videostream-analytics/tests/unit/test_prefilter_config_contract.py) 的 fallback 用例）。

### 3.3 ROI Crop + Trajectory（Phase 9）

用于 `child_safety` 等需要"聚焦目标 person"的场景：把 motion clip 按 prefilter 累计的 union bbox 裁剪成 `<clip>_input.mp4`，VLM 消费这个裁剪版而非原片，识别小目标准确率更高。

- **trajectory 累计**：`FramePrefilter.accumulate` 每次命中把归一化 xyxy 融进 `_union` bbox；`result()` clamp 到 `[0,1]` 后放进 `PrefilterResult.trajectory_region_xyxy`。
- **ROI crop 生成**：`_emit_segment` 里 prefilter PASS + `roi_crop.enabled` + `trajectory_region_xyxy` 非空时，调 [`prepare_roi_segment()`](../../videostream-analytics/stream_monitor/pipeline/roi_processor.py) 写 `<clip>_input.mp4`；支持三种 mode：
  - `crop`：只保留 union bbox 区域（缩小 canvas）
  - `highlight`：全画面 + union 区域高亮框 + 其他区域调暗
  - `crop_and_concat`：左原图 + 右逐帧 person crop 并列
- **早切**：当 `auto_split_area > 0` 且 union 面积超过阈值时，主循环调 `FramePrefilter.should_split()` 提前 `extractor.finish() → emit → start_segment()`，避免一个 clip 跨度太大导致 crop 失效。
- **失败降级**：ffmpeg h264 重编码失败保留 mp4v 输出；任何异常返回 `None`，caller fallback 到原 clip。
- **payload 契约**：motion payload 加 `"trajectory_region": "[x0,y0,x1,y1]"` JSON string（4 个 ∈ [0,1] 的归一化坐标），`summary_clip_input` 指向 `_input.mp4`。

### 3.4 Continuous Recorder（固定时长录像分支）

[`stream_monitor/continuous_recorder.py`](../../videostream-analytics/stream_monitor/continuous_recorder.py) 独立线程，与 motion pipeline 并行。

- 按 `RecordingConfig.interval_seconds`（默认 60 s）滚动切段写 `<data_dir>/recordings/<YYYY-MM-DD>/<source_id>_HHMMSS.mp4`。
- 每段写完 emit `type=recording` 事件，payload 含 `recording_path` / `recording_start` / `recording_end` / `duration_seconds` / `file_size_bytes`。
- 与 motion 分支**完全独立**：motion pause 不影响 recording，反之亦然。用途：长时间回放（`scene_query` fallback）、事件追溯。
- Retention：VSA **不**主动删除旧录像；由 MCP server 的 storage cleaner 按 `retention_days` 清 `recordings/<date>/` 目录。

### 3.5 Latest-frame Snapshot

`StreamPipeline._maybe_write_snapshot()` 每 ~1 Hz（默认 `_snapshot_hz=1.0`）把当前帧写到 `<data_dir>/latest.jpg`，用**原子 rename**（`.latest.jpg.tmp` → `latest.jpg`）避免读时半张图。失败静默 log，不打断 pipeline。用途：MCP `latest-frame` resource / scene_query 读实时帧。

---

## 4. Source 生命周期状态机

`GET /sources/{id}/status` 返回的 `status` 字段状态转换。权威定义见 [apis/videostream_analytics_api.md §3.7.1](../apis/videostream_analytics_api.md)；这里给实现视角的说明。

| status | 触发条件 | 是否终态 | 退出条件 |
|--------|----------|----------|----------|
| `connecting` | `_connect()` 正在尝试打开 RTSP | 否（瞬时） | 成功 → `online`；失败 → `error` |
| `online` | 连接成功并在抓帧 | 否（事件驱动） | RTSP 失败 → `error` / `reconnecting`；`/pause` → `paused` |
| `error` | 单次 RTSP 读失败 | 否（瞬时） | 进入 `reconnecting` 退避路径 |
| `reconnecting` | `failure_count < max_failures`，正在指数退避重连 | 否 | 连上 → `online`；累计到 `max_failures` → `unhealthy` → 进入 `recovery_strategy` 分支 |
| `unhealthy` | 累计失败 ≥ `max_failures` | 否（瞬时） | `retry` 继续退避 / `pause` → `paused` / `remove` → `removed` |
| `paused` | `POST /pause` **或** `recovery_strategy=pause` 触发 **或** keepalive watchdog 超时 | ✅ 终态 | 仅 `POST /resume` 可切回 `online` |
| `removed` | `recovery_strategy=remove` 触发或 source 已注销 | 终态 | source 已从 `_bundles` 删除，需重新 `/register_source` |
| `stopped` | `/stop` / 优雅退出 | 终态 | 同 `removed` |

**关键不变量**：

1. **`reconnecting` 不是终态**。`recovery_strategy=pause` 不等于"任何失败立刻 pause"—— VSA 会先累计 `failure_count` 次失败并做指数退避，只有累计到 `max_failures` 才触发 pause。默认 `max_failures=30, backoff_base=2.0, backoff_max=120.0`。
2. **`paused` 是终态**。RTSP idle-timeout 触发的隐式重连在 `_run` 里也显式尊重 `_paused` 标志位（[rtsp_monitor.py:230-235](../../videostream-analytics/stream_monitor/rtsp_monitor.py)），不会把用户 pause 的 source 拉回 online。任何"paused 自己变 online"必然有外部 `/resume` 调用。
3. **`failure_count` 在 `online` 成功重连后归零**——RTSP 抖动恢复后计数从头累积。

---

## 5. HTTP 控制面

监听 `0.0.0.0:8999`（`ServerConfig.host` / `port`），FastAPI + uvicorn，请求/响应均为 JSON。全部端点如下，完整字段释义见 [apis/videostream_analytics_api.md §3](../apis/videostream_analytics_api.md)。

| Method | Path | 用途 |
|--------|------|------|
| `GET` | `/health` | Liveness probe |
| `GET` | `/sources` | 列出所有已注册 source（**裸数组**，Phase 7 契约） |
| `GET` | `/sources/{id}` | 单源详情 |
| `GET` | `/sources/{id}/status` | 别名，MCP `analyticsSourceExists` 使用 |
| `POST` | `/register_source` | 注册并启动 source（嵌套 `pipeline` schema） |
| `DELETE` | `/unregister_source` | 注销（body 形式） |
| `DELETE` | `/sources/{id}` | 注销（path 形式） |
| `POST` | `/sources/{id}/stop` | 等价于 DELETE |
| `POST` | `/sources/{id}/restart` | 停 + 起 pipeline / recorder，保留 bundle |
| `POST` | `/sources/{id}/pause` | 暂停（保留注册） |
| `POST` | `/sources/{id}/resume` | 恢复 |
| `POST` | `/sources/{id}/keepalive` | Phase 8 心跳，刷新 `last_keepalive_at` |
| `PUT` | `/sources/{id}/pipeline` | 热更新 pipeline 配置（嵌套 schema） |

**错误响应约定**：

- `404 Not Found` — source 未注册，body `{"detail": "Source not found: ..."}`
- `422 Unprocessable Entity` — pydantic 校验失败；自定义 [handler](../../videostream-analytics/service.py) 会把 `extra_forbidden` 错误提取到 `unknown_fields` 数组，附 `hint` 说明正确 schema。
- `500` — 未预期的服务端异常。

**`register_source` 的语义**：幂等——对已 running 的 id 重复调返回 `{"status": "already_running"}`；对存在但已停止的 id 会先 teardown 再重建；全新 id 返回 `{"status": "started", ...}`。

---

## 6. Webhook 事件面

VSA 主动 `POST <webhook_url>` 的事件都用嵌套 envelope（Phase 7 硬切换后的契约）：

```json
{
  "sourceId":  "cam_child",
  "type":      "motion | recording | status",
  "timestamp": "2026-06-30T14:30:15",
  "payload":   { ... }
}
```

三种 `type` 及其 payload 字段见 [apis/videostream_analytics_api.md §4](../apis/videostream_analytics_api.md)。这里补充实现侧的细节：

| type | 触发点 | 说明 |
|------|--------|------|
| `motion` | `_emit_segment()`（[rtsp_monitor.py](../../videostream-analytics/stream_monitor/rtsp_monitor.py)） | 只在 prefilter PASS（或 prefilter 未启用）时 emit；SKIP 的 clip 被删除，不 emit |
| `recording` | `ContinuousRecorder._record_loop()`（[continuous_recorder.py](../../videostream-analytics/stream_monitor/continuous_recorder.py)） | 每段写完立即 emit；与 motion 完全独立 |
| `status` | `_emit_status()` 及若干 inline `_emit_envelope("status", ...)` 调用 | payload.status ∈ {paused, online, unhealthy, reconnecting, stopped}；MCP 目前忽略未识别 type |

**Design §9.2 里提到的 `static` type 当前不发送**——motion 结束用 `status: online` 恢复标记就够了，MCP 侧的 `case "static"` 只是预留分支。

**Webhook 发送策略**：`WebhookSink` 复用 `shared/webhook_client.py`，默认 `timeout=10s`、`retry_attempts=3`、`retry_delay=2.0`。失败只记 log，不阻塞 pipeline；事件不重放。

---

## 7. 配置与默认值

单一 YAML 配置 [`config/config.yaml`](../../videostream-analytics/config/config.yaml)。**顶层字段**：

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `server.host` / `server.port` | string / int | `0.0.0.0:8999` | HTTP 监听地址 |
| `webhook.url` | string | `http://localhost:18800/events` | 默认 webhook 目标；per-source `webhook_url` 优先 |
| `webhook.timeout` / `retry_attempts` / `retry_delay` | int / int / float | 10 / 3 / 2.0 | HTTP 客户端参数 |
| `data_dir` | string | `~/.smartbuilding/data` | 全局输出根；register 时 body 里 `data_dir` 优先 |
| `defaults.{motion, segment, recording, prefilter, health, keepalive}` | object | 见下 | 每个子块对应一份 pydantic 模型，`register_source` 未传时回退整块 |
| `logging.level` | string | `"INFO"` | Python logger level |

**环境变量覆盖**：

| Env | 覆盖字段 |
|-----|----------|
| `WEBHOOK_URL` | `webhook.url` |
| `RECORDINGS_DIR` | `data_dir` |
| `VIDEOSTREAM_CONFIG` | 备选 config 文件路径 |
| `OV_CACHE_DIR` | OpenVINO 模型缓存目录（YOLO prefilter 使用） |

**`pipeline` 嵌套 schema**（`register_source` body 里）—— 定义在 [`shared/config.py`](../../videostream-analytics/shared/config.py) 每个 `*Config` 类：

| 子块 | 关键字段（默认值） |
|------|-------------------|
| `motion` | `enabled=true`, `diff_threshold=25`, `area_ratio=0.015`, `stable_frames=30` |
| `segment` | `interval=10.0`, `min_duration=1.0` |
| `prefilter` | `enabled=false`, `model_path=""`, `target_classes=["person"]`, `min_confidence=0.4`, `min_frames_hit=2`, `detect_fps=2.0`, `device="CPU"`, `roi_crop=None` |
| `prefilter.roi_crop` (Phase 9) | `enabled=false`, `mode="crop"`, `expand=0.25`, `auto_split_area=0.0` |
| `recording` | `enabled=true`, `interval_seconds=60` (别名 `interval`), `fps=15`, `retention_days=5` |
| `health` | `max_failures=30`, `recovery_strategy="retry"`, `backoff_base=2.0`, `backoff_max=120.0` |
| `keepalive` (Phase 8) | `enabled=false`, `timeout_seconds=90.0`, `check_interval_seconds=10.0` |

**回退语义**：sub-block 若整块省略，回退到 `defaults.<sub_block>`；这是**整块替换**而非字段级合并（见 [test_prefilter_config_contract.py](../../videostream-analytics/tests/unit/test_prefilter_config_contract.py)）。

---

## 8. 数据目录约定

每个 source 的所有产出文件落在 `<data_dir>/`：

```
<data_dir>/
├── latest.jpg                              # 周期写入的快照
├── motion_events/<YYYY-MM-DD>/
│   ├── <source_id>_HHMMSS.mp4              # 原始 motion clip（payload.event_file_path）
│   └── <source_id>_HHMMSS_input.mp4        # ROI cropped 片段（Phase 9，payload.summary_clip_input）
└── recordings/<YYYY-MM-DD>/
    └── <source_id>_HHMMSS.mp4              # 固定时长录像（payload.recording_path）
```

**Retention 责任划分**：

- `latest.jpg` 由 VSA 自身覆盖写，无需清理。
- `motion_events/` / `recordings/` 旧日期目录由 **MCP server 的 storage cleaner** 按 `storage.retention_days` 清理（VSA 不主动删除）。
- 注销 source 时只停 pipeline，`<data_dir>` 目录**保留**（避免 MCP reconcile 中间态清空未同步的证据文件）。

---

## 9. Health Watchdog + Keepalive（Phase 8）

- **健康策略**（health）：`recovery_strategy` ∈ {`retry`, `pause`, `remove`}，触发时机见 §4 状态机。`retry` 是默认；`pause` 保留 bundle 等待 MCP 决策；`remove` 直接从 `_bundles` 移除 source 并发 `status=removed` 事件。
- **Keepalive Watchdog**（`SourceManager._watchdog_loop`）：
  - 默认 OFF（`KeepaliveConfig.enabled=false`），MCP register 时显式打开才生效。
  - 单个 daemon thread 服务所有 source，用 `threading.Event.wait(timeout)` 睡眠；`register_source` 完成时 `event.set()` 唤醒 daemon，避免"新 source 有短 interval 但要等旧 sleep 结束才被检查"的竞态（Phase 8 修复）。
  - 巡检间隔取所有 enabled source 中最小的 `check_interval_seconds`（fallback 到 `defaults.keepalive.check_interval_seconds`）。
  - 超过 `timeout_seconds` 未收到 keepalive → 调 `pause_source(source_id)`（不重复对已 paused source 触发）。
  - 触发的 pause 与手动 pause 走同一条路径，同样是终态，需要 MCP 显式 `/resume`。
- **Grace period**：`register_source` 时若 `keepalive.enabled=true`，`last_keepalive_at` 初始化为 `time.time()`，给 MCP 留 `timeout_seconds` 的窗口发第一次心跳。

---

## 10. 测试策略

| 目录 | 数量 | 依赖 | 用途 |
|------|------|------|------|
| [tests/unit/](../../videostream-analytics/tests/unit/) | 185 assertions（15 个文件） | 只需 Python venv，不依赖 RTSP / VLM | 契约校验、状态机、prefilter/recorder/snapshot 边界、Phase 8 keepalive、Phase 9 trajectory + roi_processor |
| [tests/integration/](../../videostream-analytics/tests/integration/) | 27 assertions（6 个文件） | 需要 MediaMTX + mock webhook + ffmpeg 推流都在跑 | 端到端 register / motion / recording / error / keepalive 各流程 |

**用例覆盖亮点**：

- **`test_prefilter_config_contract.py`**：pin 住"per-source 整块 override defaults"的合同 + prefilter 模型缺失时的 graceful degrade。
- **`test_snapshot.py`**：`latest.jpg` 原子写入 + N 帧一次的采样节奏。
- **`test_pause_resume.py`**：全部状态转换 + status envelope 发送（Phase 7）。
- **`test_keepalive.py`**（Phase 8）：14 个用例覆盖 keepalive endpoint、watchdog 超时、disabled / paused / not_running 分支。
- **`test_trajectory.py` + `test_roi_processor.py`**（Phase 9）：18 个用例覆盖 xyxy 归一化、union 累计、should_split 阈值、ROI crop 三模式 + ffmpeg 失败降级。

**跑法**：

```bash
cd videostream-analytics && source .venv/bin/activate
python -m pytest tests/unit/ --timeout=60 -q
python -m pytest tests/integration/ -m integration --timeout=300 -q
```

完整手动验证步骤（V1–V12）见 [vsa-gsg.md §7](../vsa-gsg.md)。

---

## 11. 与 MCP server 的契约点

| VSA 端能力 | MCP server 端调用点 | 状态 |
|-----------|--------------------|------|
| `POST /register_source`（嵌套 pipeline schema） | `analyticsRegister` in `packages/tools/src/monitor-ctl.ts` | ✅ 对齐 |
| `GET /sources/{id}/status` | `analyticsSourceExists` | ✅ 对齐 |
| `DELETE /sources/{id}` | `analyticsDelete`（unregister + reconcile 删孤儿） | ✅ 对齐 |
| `POST /sources/{id}/pause` | `analyticsPause`（graceful shutdown、`stop` action） | ✅ 对齐 |
| `POST /sources/{id}/resume` | `analyticsResume` | ✅ 对齐 |
| `GET /sources`（裸数组） | `analyticsListSources`（reconcile 启动对账） | ✅ 对齐 |
| `POST /sources/{id}/keepalive` (Phase 8) | 待 MCP `index.ts` 起 `setInterval` 心跳循环 | ⚠️ VSA 就绪，MCP 端未接入 |
| Webhook `POST <webhook_url>`（motion / recording / status） | `EventsEndpoint` (`packages/mcp-server/src/events-endpoint.ts`) | ✅ envelope 一致 |
| `<data_dir>/latest.jpg` | `latest-frame` resource in `packages/mcp-server/src/resources.ts` | ⚠️ VSA 已写，MCP 端仍为 stub |

**联调细节**（register 状态矩阵、优雅退出顺序、reconcile 策略）见 [monitor-ctl-analytics-integration.md](./monitor-ctl-analytics-integration.md)。
