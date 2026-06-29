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
    "prefilter": { "enabled": false },
    "recording": { "enabled": true, "interval_seconds": 60, "retention_days": 5 },
    "health":    { "max_failures": 30, "recovery_strategy": "retry" }
  }
}
```

必填：`source_id`、`source_url`。其他字段省略时使用 `config.yaml` 的 `defaults`。`data_dir` 省略时落到 `<config.data_dir>/<source_id>/`。

**注意**：旧的"平铺"格式（`rtsp_url` / 顶层 `motion/segment/...` / `use_case`）在 Phase 7 硬切换后**不再接受**，会返回 422。

Webhook 事件（VSA → 下游 `/events`）envelope（嵌套）：

```json
{ "sourceId": "cam_demo", "type": "motion|recording|status",
  "timestamp": "2026-06-29T10:30:15", "payload": { ... } }
```

每种 `type` 的 `payload`：

| type | 必填 | 可选 |
|---|---|---|
| `motion` | `event_file_path`, `summary_clip_input`, `start_time`, `duration_seconds` | `end_time`, `prefilter_passed` (0/1), `prefilter_classes` (JSON str), `prefilter_confidence`, `trajectory_region` |
| `recording` | `recording_path`, `recording_start`, `recording_end` | `duration_seconds`, `file_size_bytes` |
| `status` | `status` | `reason` |

## 6. 单元测试

不依赖 Docker / RTSP，最快确认实现完整性：

```bash
cd videostream-analytics
source .venv/bin/activate
python -m pytest tests/unit/ -v --timeout=60
```

期望：**152 个用例全 PASS**，约 85 秒内跑完（含 `test_snapshot.py` 6 个 latest.jpg 回归用例）。

## 7. 功能验证（V1 – V10）

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

### 验收清单

| # | 项目 | 期望 |
|---|---|---|
| V1 | GET /health | 200 + `status: ok` |
| V2 | POST /register_source（嵌套 pipeline） | `status: started` + 旧平铺 body 必须 422 |
| V3 | GET /sources（裸数组）+ /sources/{id}/status | `health.*` / `recording_enabled` 完整 |
| V4 | Motion + Recording → webhook + 磁盘 + latest.jpg | motion envelope `payload.event_file_path` ✓；recording envelope `payload.recording_path` 按 `interval_seconds` 周期；`latest.jpg` mtime ≤ 2s |
| V5 | PUT /pipeline 热更新（嵌套 pipeline） | 配置生效，recording 启停可切换 |
| V6 | POST pause / resume | 状态切换 + 暂停期间无事件 |
| V7 | DELETE /sources/{id} | 列表移除 |
| V8 | recovery_strategy=remove | 自动 remove + envelope `status: unhealthy/stopped` 事件 |
| V9 | CLI serve/stream/health | 三命令均可用，stream stdout 输出 envelope |
| V10 | 接真 MCP server 端到端 | MCP DB `events` / `video_summary_tasks` / `recordings` 三张表落行，文件物理存在 |

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
