# Video Stream Analytics Microservice — Get Started Guide

videostream-analytics 是 Smart Building 的视频流处理微服务。从 RTSP 拉流，做 motion 检测和可选的 NPU YOLO prefilter，把符合条件的片段切成 mp4 并通过 webhook 推送给下游消费方（例如 MCP Server）。本文档只覆盖 VSA 微服务自身的安装、配置、API 使用和验证流程。

## 1. 前提条件

| 依赖 | 版本 / 说明 |
|---|---|
| Python | ≥ 3.10（仅本地模式需要） |
| Docker | ≥ 24，含 `docker compose`（容器模式需要） |
| ffmpeg | 推流测试用 |
| MediaMTX | 提供 RTSP 服务，host 端运行 |
| YOLO 模型 | 启用 prefilter 时挂载 `~/models` 到容器 `/models` |

YOLO 模型目录布局：

```
~/models/openvino/shape_static_1280x704/yolo11s/FP16/yolo11s.xml
~/models/openvino/shape_static_1280x704/yolo11s/FP16/yolo11s.bin
```

## 2. 安装与启动

源码位于仓库根目录的 `videostream-analytics/` 下。下文示例命令默认在该目录执行。

### 2.1 Docker Compose（推荐）

```bash
cd videostream-analytics
docker compose -f docker/docker-compose.yaml build
docker compose -f docker/docker-compose.yaml up -d
docker compose -f docker/docker-compose.yaml logs -f videostream-analytics
```

环境变量（可在 `.env` 或 shell 中设置）：

| 变量 | 默认 | 说明 |
|---|---|---|
| `WEBHOOK_URL` | `http://host.docker.internal:18789/webhook/smarthome/event` | 事件下游 |
| `DATA_DIR` | `/tmp/smartbuilding-clips` | clip 输出目录（host 路径，挂到容器 `/data`） |
| `MODEL_DIR` | `~/models` | YOLO 模型目录（挂到容器 `/models:ro`） |
| `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` | 空 | 仅 build 阶段使用 |

容器使用 `network_mode: host`，对外端口固定 `8999`。

### 2.2 本地模式

```bash
cd videostream-analytics
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[npu,dev]"
videostream-analytics serve --config config/config.yaml
```

启动成功日志：

```
Uvicorn running on http://0.0.0.0:8999
```

## 3. 配置说明

`config/config.yaml`（容器内默认路径 `/app/config/config.yaml`）：

```yaml
server:
  host: "0.0.0.0"
  port: 8999

webhook:
  url: "http://localhost:18800/events"
  timeout: 10
  retry_attempts: 3
  retry_delay: 2

# `data_dir` 是所有 per-source 输出的根目录。
# 每个注册的 source 会写到 `<data_dir>/<source_id>/`，除非注册体里显式传入
# 绝对路径的 `data_dir`（MCP 默认就是传绝对路径）。
data_dir: "~/.smartbuilding/data"

defaults:
  motion:
    enabled: true
    diff_threshold: 15      # 帧差阈值
    area_ratio: 0.005       # 触发动作的最小面积占比
    stable_frames: 45       # 静止判定帧数
  segment:
    interval: 10            # 切片检查间隔（秒）
    min_duration: 1.0       # 最短 clip 时长（秒）
  recording:
    enabled: true           # 启动后台固定时长录制（与 motion 支路并行）
    interval_seconds: 60    # 单个固定时长片段时长（秒）
    fps: 15
    retention_days: 5
  prefilter:
    enabled: true
    model_path: "/models/openvino/shape_static_1280x704/yolo11s/FP16/yolo11s.xml"   # 容器内路径
    target_classes: ["person"]
    min_confidence: 0.4
    min_frames_hit: 1
    detect_fps: 2.0
    device: "NPU"           # NPU / CPU / GPU
  health:
    max_failures: 30
    recovery_strategy: "retry"   # retry / pause / remove
    backoff_base: 2.0
    backoff_max: 120.0

logging:
  level: "INFO"
```

`defaults` 是全局默认值，每个源在注册时可通过同名字段覆盖。

## 4. CLI 三种模式

入口在 `pyproject.toml` 的 `[project.scripts]`，激活 venv 后用 `videostream-analytics` 命令；容器内通过 `docker exec` 调用。

| 子命令 | 用途 | 关键参数 |
|---|---|---|
| `serve` | 启动 HTTP API（默认） | `--config` `--host` `--port` |
| `stream` | 单源调试，事件打印到 stdout / 发到 webhook | `--source-id` `--rtsp-url` `--use-case` `--sink {stdout,webhook,null}` |
| `health` | 探活已运行实例 | `--host` `--port`（默认 127.0.0.1:8999） |

示例：

```bash
videostream-analytics health --port 8999

videostream-analytics stream \
  --source-id cam_dev \
  --rtsp-url rtsp://localhost:8554/live/child \
  --sink stdout
```

## 5. HTTP API

服务监听 `0.0.0.0:8999`，所有请求 / 响应均为 JSON。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/health` | 探活 |
| GET | `/sources` | 列出所有已注册源（**返回裸数组**） |
| GET | `/sources/{source_id}` | 单源详情（含 health 字段） |
| GET | `/sources/{source_id}/status` | 单源详情（MCP `analyticsSourceExists` 使用） |
| POST | `/register_source` | 注册源（嵌套 `pipeline` 包装） |
| DELETE | `/unregister_source` | 注销源（body 形式） |
| POST | `/sources/{source_id}/stop` | 停止并注销 |
| POST | `/sources/{source_id}/restart` | 重启 |
| POST | `/sources/{source_id}/pause` | 暂停（不删除） |
| POST | `/sources/{source_id}/resume` | 恢复 |
| PUT | `/sources/{source_id}/pipeline` | 热更新 motion / segment / prefilter / recording / health 配置（嵌套 `pipeline` 包装） |
| POST | `/sources/{source_id}/keepalive` | MCP 心跳 — VSA 刷新 `last_keepalive_at`；超时 watchdog 自动 pause |
| DELETE | `/sources/{source_id}` | RESTful 删除（同 stop） |

`POST /register_source` 完整 body 示例（嵌套形态，与 MCP `monitor-ctl.ts` 发出的一致）：

```json
{
  "source_id":   "cam_demo",
  "source_url":  "rtsp://localhost:8554/live/child",
  "webhook_url": "http://host.docker.internal:9999/events",
  "data_dir":    "/data/cam_demo",
  "pipeline": {
    "motion":    { "enabled": true, "diff_threshold": 15, "area_ratio": 0.005, "stable_frames": 45 },
    "segment":   { "interval": 10, "min_duration": 1.0 },
    "prefilter": {
      "enabled": false,
      "roi_crop": { "enabled": false, "mode": "crop", "expand": 0.25, "auto_split_area": 0.0 }
    },
    "recording": { "enabled": true, "interval_seconds": 60, "retention_days": 5 },
    "health":    { "max_failures": 30, "recovery_strategy": "retry" },
    "keepalive": { "enabled": false, "timeout_seconds": 90.0, "check_interval_seconds": 10.0 }
  }
}
```

必填：`source_id`、`source_url`。其他字段省略时使用 `config.yaml` 的 `defaults`。`data_dir` 省略时落到 `<config.data_dir>/<source_id>/`。

**`pipeline.keepalive`（Phase 8）**：MCP 端开启后每 ~30s 调 `POST /sources/{id}/keepalive`；VSA 后台 watchdog 每 `check_interval_seconds` 巡检一次，超过 `timeout_seconds` 没收到心跳就**自动 pause** 该 source（不删除，需要 MCP 显式 resume）。默认 OFF — V1–V10 联调脚本无需关心；MCP 实际部署时显式打开。

**`pipeline.prefilter.roi_crop`（Phase 9，child_safety）**：当 prefilter PASS 且 `roi_crop.enabled=true` 时，VSA 用 prefilter 累计的轨迹 union bbox 生成 `<clip>_input.mp4`，并把 `summary_clip_input` 指向该裁剪片段。`mode` ∈ `crop | highlight | crop_and_concat`（默认 `crop`），`expand` 把 bbox 向外延伸（默认 0.25），`auto_split_area > 0` 时若 union 面积超阈值则提前切 segment（避免大轨迹下 crop 失效，child_safety 建议 0.35）。失败（ffmpeg 缺失 / region 过小 / clip 无法读）自动 fallback 到原片，不抛异常。



Webhook 事件（VSA → 下游 `/events`）envelope（嵌套）：

```json
{ "sourceId": "cam_demo", "type": "motion|recording|status",
  "timestamp": "2026-06-29T10:30:15", "payload": { ... } }
```

每种 `type` 的 `payload`：

| type | 必填 | 可选 |
|---|---|---|
| `motion` | `event_file_path`, `summary_clip_input`, `start_time`, `duration_seconds` | `end_time`, `prefilter_passed` (0/1), `prefilter_classes` (JSON str), `prefilter_confidence`, `trajectory_region` (JSON `"[x0,y0,x1,y1]"` 归一化坐标，Phase 9 起 VSA 上报) |
| `recording` | `recording_path`, `recording_start`, `recording_end` | `duration_seconds`, `file_size_bytes` |
| `status` | `status` | `reason` |

## 6. 单元测试

不依赖 Docker / RTSP，最快确认实现完整性：

```bash
cd videostream-analytics
source .venv/bin/activate
python -m pytest tests/unit/ -v --timeout=60
```

期望：**185 个用例全 PASS**（含 `test_snapshot.py` 6 个 latest.jpg 回归 / `test_keepalive.py` 14 个 Phase 8 / `test_trajectory.py` 10 个 + `test_roi_processor.py` 8 个 Phase 9）。

## 6.5 集成测试

需要 **mediamtx + ffmpeg 推流 + mock webhook** 都在跑（`tests/integration/conftest.py` 假定 analytics `:8999`、webhook `:9999`、RTSP `rtsp://localhost:8554/live/child`）。准备步骤复用第 7 节"准备：启动支撑服务"的 T1 / T2 / T4，并把 T3 启动起来（VSA 自身）。

```bash
cd videostream-analytics
source .venv/bin/activate
python -m pytest tests/integration/ -m integration --timeout=300 -v
```

期望：**27 个用例全 PASS**，约 3-5 分钟跑完。分布：

| 文件 | 用例数 | 覆盖 |
|---|---|---|
| `test_source_lifecycle.py` | 9 | register / list / status / stop / restart / unregister / duplicate / 旧平铺 body 422 |
| `test_motion_to_webhook.py` | 5 | motion envelope + payload 字段 + 磁盘 clip + `latest.jpg` |
| `test_recording_to_webhook.py` | 3 | recording envelope + `recordings/<date>/*.mp4` + interval 周期 |
| `test_error_handling.py` | 4 | 注册重复 / 不存在 source 的 404 / 非法 body 422 / 网络抖动恢复 |
| `test_keepalive.py` | 3 | Phase 8：keepalive endpoint / watchdog 超时自动 pause / 关闭时不 pause |
| `test_container_health.py` | 3 | Docker 容器探活（仅容器模式跑） |

常用筛选：

```bash
# 只跑某一类
pytest tests/integration/test_keepalive.py -m integration -v

# 跳过 Docker 用例（host 模式下用）
pytest tests/integration/ -m "integration and not docker" --timeout=300 -v

# 失败时保留 webhook 收到的事件以便排查
pytest tests/integration/test_motion_to_webhook.py -m integration -v -s
```

**注**：
- Phase 9（trajectory + ROI crop）目前**没有自动化集成用例**，依赖 §7 V12 手动验证。后续 child_safety 长期联调时可在 `test_motion_to_webhook.py` 加 `test_motion_event_carries_trajectory_region` 把 `payload.trajectory_region` 与 `_input.mp4` 检查自动化。
- 集成测试用例数会跟 Phase 7-9 演进同步增加；最新数字以 `pytest tests/integration/ -m integration --collect-only -q` 输出为准。

## 7. 功能验证（V1 – V12）

启动顺序：MediaMTX → mock webhook → videostream-analytics → ffmpeg 推流 → 在另一个终端逐条执行下方 curl。

### 准备：启动支撑服务（4 个终端）

**T1 — MediaMTX（host）**

```bash
~/.local/bin/mediamtx /path/to/mediamtx.yml
```

启动成功日志包含 `[RTSP] listener opened on :8554`。

**T2 — Mock webhook（host）**

```bash
cd videostream-analytics
source .venv/bin/activate
python -m uvicorn tests.integration.mock_webhook_server:app \
  --host 0.0.0.0 --port 9999
```

**T3 — videostream-analytics（host 或容器，二选一）**

```bash
# host 方式
WEBHOOK_URL="http://localhost:9999/events" \
  videostream-analytics serve --config config/config.yaml

# 或容器方式
docker run -d --rm --name vsa-test --network host \
  -e WEBHOOK_URL="http://localhost:9999/events" \
  -v "$HOME/models:/models:ro" \
  -v /tmp/smartbuilding-clips:/data \
  videostream-analytics:latest
```

**T4 — 推流（host）**

```bash
ffmpeg -re -stream_loop -1 -ss 40 \
  -i /path/to/child_safety_demo.mp4 \
  -c copy -f rtsp rtsp://localhost:8554/live/child
```

`ffprobe rtsp://localhost:8554/live/child` 应能看到 H.264 流。

### V1. `GET /health`

```bash
curl -sf http://localhost:8999/health | python3 -m json.tool
```

期望：

```json
{ "status": "ok", "service": "videostream-analytics" }
```

### V2. `POST /register_source`

```bash
curl -s -X POST http://localhost:8999/register_source \
  -H "Content-Type: application/json" \
  -d '{
    "source_id":   "cam_demo",
    "source_url":  "rtsp://localhost:8554/live/child",
    "data_dir":    "/tmp/vsa-test/cam_demo",
    "pipeline": {
      "prefilter": {"enabled": false}
    }
  }' | python3 -m json.tool
```

期望：`{"status": "started", "source_id": "cam_demo", "data_dir": "/tmp/vsa-test/cam_demo", ...}`

### V3. `GET /sources` + `GET /sources/{id}/status`

```bash
# /sources 返回**裸数组**（注意：不是 {"sources":[...]} 包装）
curl -sf http://localhost:8999/sources | python3 -m json.tool
curl -sf http://localhost:8999/sources/cam_demo/status | python3 -m json.tool
```

期望单源响应包含：

```json
{
  "source_id": "cam_demo",
  "source_url": "rtsp://localhost:8554/live/child",
  "data_dir": "/tmp/vsa-test/cam_demo",
  "status": "online",
  "running": true,
  "recording_enabled": true,
  "health": {
    "failure_count": 0,
    "reconnect_count": 0,
    "recovery_strategy": "retry",
    "max_failures": 30,
    "start_time": "..."
  }
}
```

### V4. Motion → clip → webhook（含 recording 支路）

等 30 ~ 60 秒让动作触发。clip 写盘路径由注册体 `data_dir` 决定（V2 注册时传入；省略则落到 `<config.data_dir>/<source_id>/`）：

```bash
# motion 事件 — envelope: {sourceId, type:"motion", timestamp, payload:{event_file_path, summary_clip_input, ...}}
curl -sf http://localhost:9999/recorded_events/motion | python3 -m json.tool | head -60

# recording 事件 — envelope: {sourceId, type:"recording", timestamp, payload:{recording_path, recording_start, ...}}
curl -sf http://localhost:9999/recorded_events/recording | python3 -m json.tool | head -40

DATA_DIR=/tmp/vsa-test/cam_demo   # 与 V2 register body 中的 data_dir 一致
ls -la "$DATA_DIR/latest.jpg"
ls -la "$DATA_DIR/motion_events/$(date +%Y-%m-%d)/"
ls -la "$DATA_DIR/recordings/$(date +%Y-%m-%d)/"

CLIP=$(ls "$DATA_DIR/motion_events/$(date +%Y-%m-%d)/"*.mp4 | head -1)
ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$CLIP"
```

期望：
- mock webhook 至少收到 1 条 `type: motion`，`payload` 含 `event_file_path` / `summary_clip_input` / `start_time` / `end_time` / `duration_seconds`
- recording 事件按 `interval_seconds` 周期出现，`payload` 含 `recording_path` / `recording_start` / `recording_end` / `file_size_bytes`
- `latest.jpg` mtime 在最近 2 秒内
- `motion_events/<today>/*.mp4` 至少 1 个，时长 1 ~ 10 秒
- `recordings/<today>/*.mp4` 与运行时长匹配（60s 间隔 ≈ 每分钟 1 个）

### V5. `PUT /sources/{id}/pipeline` 热更新

```bash
curl -s -X PUT http://localhost:8999/sources/cam_demo/pipeline \
  -H "Content-Type: application/json" \
  -d '{
    "pipeline": {
      "motion": {"diff_threshold": 30, "stable_frames": 60},
      "health": {"max_failures": 10, "recovery_strategy": "pause"}
    }
  }' | python3 -m json.tool

sleep 3
curl -sf http://localhost:8999/sources/cam_demo/status | python3 -m json.tool
```

期望 PUT 返回 `{"status": "updated"}`；后续 GET 看到 `health.max_failures: 10`、`recovery_strategy: "pause"`。

### V6. `POST /pause` + `POST /resume`

```bash
curl -s -X POST http://localhost:8999/sources/cam_demo/pause  | python3 -m json.tool
curl -sf http://localhost:8999/sources/cam_demo               | python3 -m json.tool   # status=paused
sleep 5
curl -s -X POST http://localhost:8999/sources/cam_demo/resume | python3 -m json.tool
curl -sf http://localhost:8999/sources/cam_demo               | python3 -m json.tool   # status=online
```

期望：`status` 字段 paused ↔ online 切换；暂停期间 mock webhook 不再收到新 motion 事件。

### V7. `DELETE /sources/{id}`

```bash
curl -s -X DELETE http://localhost:8999/sources/cam_demo | python3 -m json.tool
curl -sf http://localhost:8999/sources                   | python3 -m json.tool
```

期望：`{"status": "stopped", "source_id": "cam_demo"}`，列表为空。

### V8. 健康策略 `recovery_strategy: remove`

```bash
curl -s -X DELETE http://localhost:9999/recorded_events > /dev/null

curl -s -X POST http://localhost:8999/register_source \
  -H "Content-Type: application/json" \
  -d '{
    "source_id":   "cam_bad",
    "source_url":  "rtsp://localhost:8554/live/__nonexistent__",
    "data_dir":    "/tmp/vsa-test/cam_bad",
    "pipeline": {
      "prefilter": {"enabled": false},
      "recording": {"enabled": false},
      "health": {
        "max_failures": 3,
        "recovery_strategy": "remove",
        "backoff_base": 1.0,
        "backoff_max": 2.0
      }
    }
  }' | python3 -m json.tool

sleep 15
curl -sf http://localhost:8999/sources                | python3 -m json.tool
curl -sf http://localhost:9999/recorded_events/status | python3 -m json.tool | head -30
```

期望：`cam_bad` 不在 `/sources` 列表中；`recorded_events/status` 含 envelope `{"sourceId": "cam_bad", "type": "status", "payload": {"status": "unhealthy", "reason": "rtsp_timeout"}}` 和 `{"sourceId": "cam_bad", "type": "status", "payload": {"status": "stopped"}}`。

### V9. CLI 三模式

```bash
# host 方式
videostream-analytics --help
videostream-analytics health --port 8999
WEBHOOK_URL="http://localhost:9999/events" \
  timeout 60 videostream-analytics stream \
    --source-id cam_cli --rtsp-url rtsp://localhost:8554/live/child \
    --sink stdout

# 容器方式
docker exec vsa-test videostream-analytics --help
docker exec vsa-test videostream-analytics health --port 8999
docker exec vsa-test timeout 60 videostream-analytics stream \
  --source-id cam_cli --rtsp-url rtsp://localhost:8554/live/child \
  --sink stdout
```

期望：
- `--help` 列出 `serve` / `stream` / `health` 三个子命令
- `health` 输出 `{"status": "ok", ...}`，exit 0
- `stream --sink stdout` stdout 先输出 `{"sourceId":"...","type":"status","payload":{"status":"online"}}`，等 30 秒以上动作累积后输出 `{"sourceId":"...","type":"motion","payload":{"event_file_path":"...",...}}`

### V10. 接真 MCP server 端到端（替换 V1–V9 的 mock webhook）

V1–V9 的 mock webhook 只能验证 VSA **单边**输出契约；V10 把 mock 换成真 MCP server，验证 webhook → MCP `/events` → SQLite 三张表全链路。**保留** T1 (MediaMTX) 和 T4 (ffmpeg 推流) 不变，把 T2 mock 替换为 MCP，并让 T3 VSA 的 webhook 指向 MCP `:3101`。

**前置：构建 MCP server（仅首次）**

```bash
cd /home/user/jie/smarthome/smart-community
npm install
for pkg in db rule-engine tools mcp-server; do
  (cd packages/$pkg && npx tsc)
done
# 4 个 workspace 都无错误输出
```

**步骤 1：启动 MCP server（替换 T2 mock webhook）**

```bash
# 干净的 MCP 数据目录
rm -rf /tmp/mcp-data && mkdir -p /tmp/mcp-data

cd /home/user/jie/smarthome/smart-community
SMARTBUILDING_DATA_DIR=/tmp/mcp-data \
  node packages/mcp-server/dist/index.js --http

# 启动日志含：
#   [mcp-server] Streamable HTTP on http://localhost:3100/mcp
#   [events-endpoint] Listening on port 3101
```

MCP 监听两个端口：
- `:3100/mcp` — MCP protocol (Streamable HTTP)，给 Agent 客户端用
- `:3101/events` — webhook 接收端点，VSA 推事件来这里

**步骤 2：重启 VSA，webhook 指向 MCP**

杀掉 T3 旧 VSA，重启时 `WEBHOOK_URL` 改成 MCP 的 events 端口：

```bash
cd /home/user/jie/smarthome/smart-community/videostream-analytics
WEBHOOK_URL=http://localhost:3101/events \
  .venv/bin/videostream-analytics serve --config config/config.yaml
```

**步骤 3：用 MCP 风格 body 注册 source（`data_dir` 指向 MCP 的 segments dir）**

```bash
curl -s -X POST http://localhost:8999/register_source \
  -H "Content-Type: application/json" \
  -d '{
    "source_id":   "cam_demo",
    "source_url":  "rtsp://localhost:8554/live/child",
    "webhook_url": "http://localhost:3101/events",
    "data_dir":    "/tmp/mcp-data/segments/cam_demo",
    "pipeline": {
      "motion":    {"diff_threshold": 15, "area_ratio": 0.005, "stable_frames": 45},
      "segment":   {"interval": 10, "min_duration": 1.0},
      "prefilter": {"enabled": false},
      "recording": {"enabled": true, "interval_seconds": 30, "retention_days": 1},
      "health":    {"max_failures": 30, "recovery_strategy": "retry"}
    }
  }' | python3 -m json.tool
```

`data_dir` 必须落到 `${SMARTBUILDING_DATA_DIR}/segments/<source_id>/` —— 这是 MCP 的存储清理器假定的布局。MCP 端 `monitor-ctl.ts` 注入这个字段时也用同样的拼接。

**步骤 4：等事件累积，查 MCP DB 三张表**

```bash
sleep 90   # 让 ~3 个 motion 事件 + ~2 个 recording 落 DB

cd /home/user/jie/smarthome/smart-community/videostream-analytics
.venv/bin/python <<'EOF'
import os, sqlite3

con = sqlite3.connect('/tmp/mcp-data/smartbuilding.db')
con.row_factory = sqlite3.Row

print("===== Row counts =====")
for tbl in ("events", "video_summary_tasks", "recordings"):
    cnt = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
    print(f"  {tbl}: {cnt}")

print("\n===== Latest 3 motion events =====")
for r in con.execute("""
    SELECT id, monitor_id, motion_type, event_file_path,
           prefilter_passed, duration_seconds
    FROM events ORDER BY id DESC LIMIT 3
"""):
    d = dict(r)
    d['file_exists'] = os.path.exists(d['event_file_path']) if d['event_file_path'] else False
    print(f"  {d}")

print("\n===== Latest 3 video_summary_tasks =====")
for r in con.execute("""
    SELECT id, event_id, summary_clip_input, status
    FROM video_summary_tasks ORDER BY id DESC LIMIT 3
"""):
    print(f"  {dict(r)}")

print("\n===== Latest 3 recordings =====")
for r in con.execute("""
    SELECT id, file_path, duration_seconds, file_size_bytes
    FROM recordings ORDER BY id DESC LIMIT 3
"""):
    d = dict(r)
    d['file_exists'] = os.path.exists(d['file_path']) if d['file_path'] else False
    print(f"  {d}")

print("\n===== latest.jpg =====")
snap = '/tmp/mcp-data/segments/cam_demo/latest.jpg'
if os.path.exists(snap):
    import time
    age = int(time.time() - os.path.getmtime(snap))
    print(f"  exists, mtime {age}s ago, size={os.path.getsize(snap)}B")
else:
    print("  MISSING")
EOF
```

**通过标准**：
- `events`: ≥ 3 行（`motion_type=motion`、`event_file_path` 文件 `file_exists=True`）
- `video_summary_tasks`: ≥ 3 行（`summary_clip_input` 填充、`status="pending"` —— 如果 VLM `:8192` 没启动会一直 pending，这是预期）
- `recordings`: ≥ 2 行（90s / 30s 间隔，每条 `duration_seconds=30.0`、`file_exists=True`）
- `latest.jpg`: 存在，mtime ≤ 2s
- MCP 启动日志含 `[reconcile] ... orphans deleted` — 控制面双向连通的额外证据

**MCP server 日志预期项**：

```bash
tail -20 /tmp/.../mcp.log   # 看你 redirect 到的文件
```

应该看到：
- ✅ `[events-endpoint] Listening on port 3101`
- ✅ `[reconcile] ...`（启动时主动调 VSA 清理 orphan）
- ⚠️ `[events-endpoint] unknown event type "status" from cam_demo` — **预期**，VSA 仍发 status envelope，MCP 当前忽略未知 type
- ❌ **不应该有** `missing required fields ...` — 如果有说明 envelope 字段对不齐

**`prefilter_passed=None` 是预期**：注册时 `prefilter.enabled=false`，VSA 不跑 YOLO，所以不附带 `prefilter_*` 字段，MCP 写 NULL。要看 prefilter 落 DB，需要在 register body 开启 prefilter 并提供 YOLO 模型路径。

### V11. Keepalive 行为验证（Phase 8）

```bash
# 注册一个开启 keepalive 的 source，timeout 设短让验证快速完成
curl -s -X POST http://localhost:8999/register_source \
  -H "Content-Type: application/json" \
  -d '{
    "source_id":   "cam_ka",
    "source_url":  "rtsp://localhost:8554/live/child",
    "data_dir":    "/tmp/vsa-test/cam_ka",
    "pipeline": {
      "prefilter": {"enabled": false},
      "recording": {"enabled": false},
      "keepalive": {"enabled": true, "timeout_seconds": 3.0, "check_interval_seconds": 1.0}
    }
  }' | python3 -m json.tool

# 立刻 ping 一次 keepalive — 应返回 200 + last_keepalive_at
curl -s -X POST http://localhost:8999/sources/cam_ka/keepalive | python3 -m json.tool

# 不再 ping，等待 5s（超过 3s timeout + 至少 1 个 watchdog tick）
sleep 5

# 状态应已被 watchdog 自动切到 paused
curl -sf http://localhost:8999/sources/cam_ka/status | python3 -m json.tool
# 期望：{ "status": "paused", "keepalive_enabled": true, "last_keepalive_at": "..." }

# 不存在的 source ping 应返回 404
curl -i -X POST http://localhost:8999/sources/no_such/keepalive | head -5
```

期望：
- 首次 keepalive 返回 `{"status": "ok", "source_id": "cam_ka", "last_keepalive_at": "..."}`
- 5s 后 `GET /sources/cam_ka/status` 的 `status` 字段为 `paused`
- VSA 日志包含 `[cam_ka] keepalive timeout (X.Xs > 3s), auto-pausing`
- 不存在 source 的 keepalive 返回 404

### V12. Trajectory + ROI Crop 验证（Phase 9，child_safety）

验证 child_safety 链路：NPU YOLO prefilter → 累计 trajectory union bbox → 写
`<clip>_input.mp4`（ROI crop） → webhook payload 带 `trajectory_region`。

**前置条件**：NPU YOLO 模型文件（默认路径
`/models/openvino/shape_static_1280x704/yolo11s/FP16/yolo11s.xml`），以及一段含
"人"的视频（如 `child_safety_demo.mp4`）。

#### Step 1 — 启动支撑服务（4 个终端）

复用第 7 节开头的 T1 / T2 / T4。这里关键是 **T3 把 WEBHOOK_URL 指到 mock**：

```bash
# T1 MediaMTX（RTSP server, :8554）—— 接收 ffmpeg 推流并转发给 VSA
~/.local/bin/mediamtx /path/to/mediamtx.yml

# T2 Mock webhook（:9999）—— 假装是 MCP server 的 /events，记录 VSA 推过来的所有事件
cd videostream-analytics && source .venv/bin/activate
python -m uvicorn tests.integration.mock_webhook_server:app --host 0.0.0.0 --port 9999

# T3 VSA（:8999）—— 主角；WEBHOOK_URL 决定它把事件发到哪
WEBHOOK_URL=http://localhost:9999/events \
  .venv/bin/videostream-analytics serve --config config/config.yaml

# T4 ffmpeg 推流 —— 把本地 mp4 当摄像头推到 MediaMTX，让 VSA 拉得到流
ffmpeg -re -stream_loop -1 -i /path/to/child_safety_demo.mp4 \
  -c copy -f rtsp rtsp://localhost:8554/live/child
```

#### Step 2 — 注册 `child_safety` 风格的 source

```bash
curl -s -X POST http://localhost:8999/register_source \
  -H "Content-Type: application/json" \
  -d '{
    "source_id":   "cam_child_roi",
    "source_url":  "rtsp://localhost:8554/live/child",
    "data_dir":    "/tmp/vsa-test/cam_child_roi",
    "pipeline": {
      "prefilter": {
        "enabled": true,
        "model_path": "/models/openvino/shape_static_1280x704/yolo11s/FP16/yolo11s.xml",
        "target_classes": ["person"],
        "detect_fps": 2.0,
        "device": "NPU",
        "roi_crop": {
          "enabled": true,
          "mode": "crop",
          "expand": 0.25,
          "auto_split_area": 0.35
        }
      },
      "recording": {"enabled": false}
    }
  }' | python3 -m json.tool
```

每个字段对应什么：

| 字段 | 含义 |
|---|---|
| `source_id` / `source_url` | VSA 内部 id + 它去 MediaMTX 拉哪条 RTSP |
| `data_dir` | 所有产出文件（motion_events/、latest.jpg）的根目录；本次落到 `/tmp/vsa-test/cam_child_roi` 方便验证完直接 `rm -rf` |
| `prefilter.enabled=true` | 打开 YOLO 后筛——只有"识别到 person"的 motion 才上报 |
| `prefilter.model_path` | OpenVINO 模型路径，必须存在；缺失会 graceful degrade（pipeline 仍跑、prefilter 失效）|
| `prefilter.detect_fps=2.0` | 每秒跑 2 次 YOLO 推理（不是每帧都跑，省 NPU） |
| `prefilter.device=NPU` | 用 NPU；CPU/GPU 也行 |
| `roi_crop.enabled=true` | **Phase 9 关键开关**——开启后才生成 `_input.mp4` 并发 `trajectory_region` |
| `roi_crop.mode=crop` | 三模式选其一：`crop`（只保留 union bbox 区域）/ `highlight`（全画面 + 高亮框）/ `crop_and_concat`（左原图 + 右逐帧人裁，需要 yolo 每帧推理） |
| `roi_crop.expand=0.25` | union bbox 向外延伸 25%，避免裁太紧 |
| `roi_crop.auto_split_area=0.35` | 当 union 面积超过 35% 帧面积时**提前切 segment**——避免一个 clip 跨度太大导致 crop 失效 |
| `recording.enabled=false` | 关掉固定时长录像支路，让验证更聚焦 motion 路径 |

期望响应：`{"status": "started", "source_id": "cam_child_roi", "source_url": "...", "data_dir": "/tmp/vsa-test/cam_child_roi"}`。

#### Step 3 — 等 motion 事件累积

```bash
# 等 60s 让 prefilter 跑出至少 1 个 PASS 事件（取决于视频里 person 出现的时机）
sleep 60
```

如果 60s 内 mock 那边一个事件都没收到（curl 看 `/recorded_events` 是空），不是 V12 bug，先 troubleshoot（按顺序排查）：

1. **VSA 进程是不是最新代码**——最容易踩。`ps -o lstart= -p $(pgrep -f videostream-analytics)` 看启动时间，对比 `stat -c '%y' stream_monitor/rtsp_monitor.py shared/config.py`。若**进程早于代码** mtime，意味着改完没重启 → kill + 重启 VSA。
2. **`WEBHOOK_URL` 是不是指对了**——`tr '\0' '\n' < /proc/<vsa_pid>/environ | grep WEBHOOK_URL` 应输出 `http://localhost:9999/events`（V12 用 mock）或 `http://localhost:3101/events`（接真 MCP）；若指错地方 webhook 永远收不到事件，但磁盘 motion clip 照样写。
3. **ffmpeg 推流**——T4 终端没报错？`ffprobe rtsp://localhost:8554/live/child` 能看到流？
4. **motion 触发**——VSA log 里 `Motion started` 有没有出现过；没有就是动作太弱，调小 `motion.diff_threshold` 或换一段动作幅度更大的视频。
5. **prefilter PASS**——VSA log 里 `Prefilter PASS` 有没有；没有就是 YOLO 没认出 person，看视频内容 + `min_confidence`。**注意：prefilter SKIP 时 motion clip 会被 `os.remove` 删除**，磁盘上看不到任何 mp4；若磁盘有 mp4 但 webhook 没事件，问题在第 1/2 项（不是 prefilter）。

#### Step 4 — 验证 webhook payload（Phase 9 新字段）

```bash
curl -sf http://localhost:9999/recorded_events/motion | python3 -c "
import json, sys
events = json.load(sys.stdin)['events']
print(f'motion events received: {len(events)}')
e = events[0]
p = e['payload']
print('trajectory_region :', p.get('trajectory_region'))      # ← Phase 9 新字段
print('summary_clip_input:', p.get('summary_clip_input'))     # ← Phase 9 起指向 _input.mp4
print('event_file_path   :', p.get('event_file_path'))        # 原片，永远在
print('prefilter_passed  :', p.get('prefilter_passed'))       # 应为 1（prefilter 没 PASS 的 clip 会被丢弃，根本不会 emit）
"
```

每一行在看什么：
- **`trajectory_region`**：JSON string `"[x0,y0,x1,y1]"`，4 个 ∈ [0,1] 的归一化坐标；prefilter 累计 union 的结果。**这是 Phase 9 的核心契约字段**，MCP `events-endpoint.ts:143` 已经在读
- **`summary_clip_input` ≠ `event_file_path`**：说明 `_input.mp4` 真的被生成并指过去了；ROI crop 失败会 fallback 到原片，那时两者相等
- **`event_file_path`**：原始 motion clip 路径，VLM 不消费它（消费的是 `summary_clip_input`），但磁盘保留作存档

#### Step 5 — 验证磁盘上的 `_input.mp4`

```bash
DATA_DIR=/tmp/vsa-test/cam_child_roi
TODAY=$(date +%Y-%m-%d)

# 5.1 文件存在 —— 至少 1 个 _input.mp4
ls -la "$DATA_DIR/motion_events/$TODAY/"*_input.mp4

# 5.2 编码 + 分辨率 —— 看是否真的被 ROI crop 过
INPUT=$(ls "$DATA_DIR/motion_events/$TODAY/"*_input.mp4 | head -1)
ffprobe -v error -show_entries stream=codec_name,width,height,duration -of default=nw=1 "$INPUT"

# 5.3 对比原片尺寸 —— crop 模式下 _input.mp4 应该明显小于原片
ORIG="${INPUT%_input.mp4}.mp4"
ffprobe -v error -show_entries stream=width,height -of csv=p=0 "$ORIG"
ffprobe -v error -show_entries stream=width,height -of csv=p=0 "$INPUT"
```

每一行在看什么：
- **5.1 文件存在**：ROI crop 没真的写就直接 fail
- **5.2 编码**：`codec_name=h264` 说明 ffmpeg 重编码成功；`codec_name=mpeg4`（mp4v）说明 ffmpeg 缺失或重编码失败但 fallback 保留了 mp4v 输出（plan 设计的降级行为）。两种都算 PASS
- **5.3 尺寸**：原片 1920×1080 时 `_input.mp4` 通常是几百×几百（取决于 person 在画面里的占比）；如果两者尺寸**一样**那 crop 没生效，是 bug

#### Step 6 — （可选）验证 `auto_split_area` 早切

VSA 日志里搜 `Segment early-split by trajectory union`。**前提是 VSA 把日志写到文件**——VSA 默认只用 `StreamHandler(sys.stdout)`，建议启动时显式重定向：

```bash
WEBHOOK_URL=http://localhost:9999/events \
  .venv/bin/videostream-analytics serve --config config/config.yaml \
  > /tmp/vsa-test/vsa.log 2>&1 &

# 查 early-split 是否触发
grep "Segment early-split by trajectory union" /tmp/vsa-test/vsa.log
```

也可以前台跑 VSA 直接看终端滚屏。

人物在画面里走动幅度大、union 面积超 `auto_split_area`（V12 例子是 0.35）时这条会出现。**没出现也不算 fail**——本次素材人物移动不大就是正常静默；想强制触发可以把 `auto_split_area` 调到 0.05 再注册重试。

#### 通过标准（4 项必须全部成立）

1. **`payload.trajectory_region`** 是 4 个 ∈ [0,1] 的浮点数 JSON string，**且不是 null / 不缺失**
2. **`payload.summary_clip_input`** 以 `_input.mp4` 结尾，且**与 `event_file_path` 不同**
3. **`_input.mp4` 物理存在**且 `ffprobe` 无错（h264 或 mp4v 都算 PASS）
4. **crop 模式下 `_input.mp4` 尺寸明显小于原片**（说明真的 crop 了，不是把原片复制了一份）

#### 接真 MCP（替代 T2 mock）

参考 V10。把 T2 换成真 MCP server，T3 的 `WEBHOOK_URL` 改 `http://localhost:3101/events`，事件累积后查 DB：

```bash
sqlite3 ~/.smartbuilding-video/data/cam_child_roi/pipeline.db \
  "SELECT id, motion_type, event_file_path, trajectory_region FROM events ORDER BY id DESC LIMIT 3;"
```

期望：`events.trajectory_region` 列非空、内容跟 webhook payload 看到的一致。

### 验收清单

| # | 项目 | 期望 |
|---|---|---|
| V1 | GET /health | 200 + `status: ok` |
| V2 | POST /register_source（嵌套 pipeline） | `status: started` + 旧平铺 body 必须 422 |
| V3 | GET /sources（裸数组）+ /sources/{id}/status | `health.*` / `recording_enabled` / `keepalive_enabled` / `last_keepalive_at` 完整 |
| V4 | Motion + Recording → webhook + 磁盘 + latest.jpg | motion envelope `payload.event_file_path` ✓；recording envelope `payload.recording_path` 按 `interval_seconds` 周期；`latest.jpg` mtime ≤ 2s |
| V5 | PUT /pipeline 热更新（嵌套 pipeline） | 配置生效，recording 启停可切换 |
| V6 | POST pause / resume | 状态切换 + 暂停期间无事件 |
| V7 | DELETE /sources/{id} | 列表移除 |
| V8 | recovery_strategy=remove | 自动 remove + envelope `status: unhealthy/stopped` 事件 |
| V9 | CLI serve/stream/health | 三命令均可用，stream stdout 输出 envelope |
| V10 | 接真 MCP server 端到端 | MCP DB `events` / `video_summary_tasks` / `recordings` 三张表落行，文件物理存在 |
| V11 | Keepalive watchdog | 注册 enabled+timeout=3s → keepalive 后 status 正常；停 keepalive 5s 后 status=paused；未注册 source ping 返回 404 |
| V12 | Trajectory + ROI Crop | motion `payload.trajectory_region` 4 浮点 ∈ [0,1]；`summary_clip_input` 指向 `*_input.mp4`；磁盘上裁剪文件可播 |

## 8. Docker 验证

`videostream-analytics:latest` 容器内置 `serve` 入口，对外暴露 `8999`。容器化后 V1 ~ V10 的所有 curl 命令同样适用，区别仅在第 7 节 T3 选择"容器方式"启动。

启动 / 停止：

```bash
# 启动（直接 docker run，便于单测）
docker run -d --rm --name vsa-test --network host \
  -e WEBHOOK_URL="http://localhost:9999/events" \
  -e no_proxy="localhost,127.0.0.1" \
  -e http_proxy="" -e https_proxy="" \
  -v "$HOME/models:/models:ro" \
  -v /tmp/smartbuilding-clips:/data \
  videostream-analytics:latest

# 启动（compose，含完整环境变量管理）
docker compose -f docker/docker-compose.yaml up -d

# 探活
curl -sf http://localhost:8999/health | python3 -m json.tool

# 进入容器执行 CLI
docker exec vsa-test videostream-analytics --help
docker exec vsa-test videostream-analytics health --port 8999

# 跑完整的集成测试套件（24 cases — 含 recording / status 路径 / 旧平铺 422 等 Phase 7 新增用例）
cd videostream-analytics
bash scripts/test-videostream-analytics.sh --integration-only

# 推荐：用 `--local` 跳过 Docker（避免 build 镜像；本地 venv 直接跑）
bash scripts/test-videostream-analytics.sh --integration-only --local
# 期望末尾输出 "24 passed in ~180s"

# 停止
docker rm -f vsa-test
docker compose -f docker/docker-compose.yaml down
```

容器内 clip 输出路径为 `/data`（对应 host `${DATA_DIR:-/tmp/smartbuilding-clips}`），YOLO 模型目录为 `/models`（对应 host `${MODEL_DIR:-~/models}`）。

## 9. 多场景评估工具

`tools/run_eval.sh` 用 4 个 phase-2 视频场景跑完整管道，输出 prefilter recall / precision：

```bash
cd videostream-analytics
bash tools/run_eval.sh                       # 全部 4 个场景
bash tools/run_eval.sh --scenario child      # 仅儿童安全
```

涵盖场景：

| 场景 | 视频 | use case 标签 |
|---|---|---|
| child | `videos/phase2/child-care/composed/child_safety_demo.mp4` | child_safety |
| fridge | `videos/demo006-2_expanded.mp4` | fridge |
| elder_day1 | `videos/phase2/elder_wakeup/composed/day1_elder_wakeup.mp4` | elder_wakeup |
| elder_day2 | `videos/phase2/elder_wakeup/composed/day2_elder_wakeup.mp4` | elder_wakeup |

> "use case 标签" 仅作为评估工具内部分组，**不传给 VSA `register_source`**（Phase 7 起 VSA 注册体不再接受 `use_case` 字段，use case 归属在 MCP 端管理）。

每个场景的输出：webhook 事件 JSON、clip mp4、prefilter 命中率统计、ASCII 时间线图（`tools/render_eval_timeline.py`）。
