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

data_dir: "~/.smartbuilding/data"

defaults:
  motion:
    diff_threshold: 15      # 帧差阈值
    area_ratio: 0.005       # 触发动作的最小面积占比
    stable_frames: 45       # 静止判定帧数
  segment:
    interval: 10            # 切片检查间隔（秒）
    min_duration: 1.0       # 最短 clip 时长（秒）
  recording:
    interval: 60            # 连续录制单文件时长（秒）
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
| GET | `/sources` | 列出所有已注册源 |
| GET | `/sources/{source_id}` | 单源详情（含 health 字段） |
| POST | `/register_source` | 注册源 |
| DELETE | `/unregister_source` | 注销源（body 形式） |
| POST | `/sources/{source_id}/stop` | 停止并注销 |
| POST | `/sources/{source_id}/restart` | 重启 |
| POST | `/sources/{source_id}/pause` | 暂停（不删除） |
| POST | `/sources/{source_id}/resume` | 恢复 |
| PUT | `/sources/{source_id}/pipeline` | 热更新 motion / segment / prefilter / health 配置 |
| DELETE | `/sources/{source_id}` | RESTful 删除（同 stop） |

`POST /register_source` 完整 body 示例：

```json
{
  "source_id": "cam_demo",
  "rtsp_url": "rtsp://localhost:8554/live/child",
  "use_case": "child_safety",
  "webhook_url": "http://host.docker.internal:9999/events",
  "motion":     { "diff_threshold": 15, "area_ratio": 0.005, "stable_frames": 45 },
  "segment":    { "interval": 10, "min_duration": 1.0 },
  "prefilter":  { "enabled": false },
  "health":     { "max_failures": 30, "recovery_strategy": "retry" }
}
```

仅 `source_id` 和 `rtsp_url` 必填，其余字段省略时使用 `config.yaml` 的 `defaults`。

## 6. 单元测试

不依赖 Docker / RTSP，最快确认实现完整性：

```bash
cd videostream-analytics
source .venv/bin/activate
python -m pytest tests/unit/ -v --timeout=60
```

期望：97 个用例全 PASS，约 60 秒内跑完。

## 7. 功能验证（V1 – V9）

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
    "source_id": "cam_demo",
    "rtsp_url": "rtsp://localhost:8554/live/child",
    "use_case": "child_safety",
    "prefilter": {"enabled": false}
  }' | python3 -m json.tool
```

期望：`{"status": "started", "source_id": "cam_demo", ...}`

### V3. `GET /sources` + `GET /sources/{id}`

```bash
curl -sf http://localhost:8999/sources | python3 -m json.tool
curl -sf http://localhost:8999/sources/cam_demo | python3 -m json.tool
```

期望单源响应包含：

```json
{
  "source_id": "cam_demo",
  "status": "online",
  "running": true,
  "health": {
    "failure_count": 0,
    "reconnect_count": 0,
    "recovery_strategy": "retry",
    "max_failures": 30,
    "start_time": "..."
  }
}
```

### V4. Motion → clip → webhook

等 30 ~ 60 秒让动作触发。clip 写盘路径由 `config.yaml` 的 `data_dir` 决定（本地模式默认 `~/.smartbuilding/data`，Docker 模式挂载到 `/data`）：

```bash
curl -sf http://localhost:9999/recorded_events/motion | python3 -m json.tool | head -40

CLIPS_DIR=$HOME/.smartbuilding/data/cam_demo/motion_events/$(date +%Y-%m-%d)   # 本地模式
# Docker 模式下：CLIPS_DIR=${DATA_DIR:-/tmp/smartbuilding-clips}/cam_demo/motion_events/$(date +%Y-%m-%d)
ls -la "$CLIPS_DIR"

CLIP=$(ls "$CLIPS_DIR"/*.mp4 | head -1)
ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$CLIP"
```

期望：
- mock webhook 至少收到 1 条 `event_type: motion`，payload 含 `clip_path` / `duration_seconds` / `start_time` / `end_time` / `clip_size_bytes`
- 磁盘有对应 mp4，时长 1 ~ 10 秒

### V5. `PUT /sources/{id}/pipeline` 热更新

```bash
curl -s -X PUT http://localhost:8999/sources/cam_demo/pipeline \
  -H "Content-Type: application/json" \
  -d '{
    "motion": {"diff_threshold": 30, "stable_frames": 60},
    "health": {"max_failures": 10, "recovery_strategy": "pause"}
  }' | python3 -m json.tool

sleep 3
curl -sf http://localhost:8999/sources/cam_demo | python3 -m json.tool
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
    "source_id": "cam_bad",
    "rtsp_url": "rtsp://localhost:8554/live/__nonexistent__",
    "prefilter": {"enabled": false},
    "health": {
      "max_failures": 3,
      "recovery_strategy": "remove",
      "backoff_base": 1.0,
      "backoff_max": 2.0
    }
  }' | python3 -m json.tool

sleep 15
curl -sf http://localhost:8999/sources                | python3 -m json.tool
curl -sf http://localhost:9999/recorded_events/status | python3 -m json.tool | head -30
```

期望：`cam_bad` 不在 `/sources` 列表中；`recorded_events/status` 含 `{"event_type": "status", "status": "unhealthy", "reason": "rtsp_timeout"}` 和 `{"event_type": "status", "status": "stopped"}`。

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
- `stream --sink stdout` stdout 先输出 `{"... "event_type": "status", "status": "online"}`，等 30 秒以上动作累积后输出 `{"... "event_type": "motion", "clip_path": "...", ...}`

### 验收清单

| # | 项目 | 期望 |
|---|---|---|
| V1 | GET /health | 200 + `status: ok` |
| V2 | POST /register_source | `status: started` |
| V3 | GET /sources(/id) 含 health 字段 | `health.*` 完整 |
| V4 | Motion → clip → webhook | 收到 motion 事件 + mp4 文件 1–10 秒 |
| V5 | PUT /pipeline 热更新 | 配置生效 |
| V6 | POST pause / resume | 状态切换 + 暂停期间无事件 |
| V7 | DELETE /sources/{id} | 列表移除 |
| V8 | recovery_strategy=remove | 自动 remove + unhealthy 事件 |
| V9 | CLI serve/stream/health | 三命令均可用 |

## 8. Docker 验证

`videostream-analytics:latest` 容器内置 `serve` 入口，对外暴露 `8999`。容器化后 V1 ~ V9 的所有 curl 命令同样适用，区别仅在第 7 节 T3 选择"容器方式"启动。

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

# 跑完成的集成测试套件（19 cases）
cd videostream-analytics
bash scripts/test-videostream-analytics.sh --integration-only

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

| 场景 | 视频 | use_case |
|---|---|---|
| child | `videos/phase2/child-care/composed/child_safety_demo.mp4` | child_safety |
| fridge | `videos/demo006-2_expanded.mp4` | fridge |
| elder_day1 | `videos/phase2/elder_wakeup/composed/day1_elder_wakeup.mp4` | elder_wakeup |
| elder_day2 | `videos/phase2/elder_wakeup/composed/day2_elder_wakeup.mp4` | elder_wakeup |

每个场景的输出：webhook 事件 JSON、clip mp4、prefilter 命中率统计、ASCII 时间线图（`tools/render_eval_timeline.py`）。
