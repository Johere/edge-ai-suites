# Video Stream Analytics Microservice — Get Started Guide

videostream-analytics 是 Smart Building 的视频流处理微服务。从 RTSP 拉流，做 motion 检测和可选的 NPU YOLO prefilter，把符合条件的片段切成 mp4 并通过 webhook 推送给下游消费方（例如 MCP Server）。本文档只覆盖 VSA 微服务自身的安装、配置、API 使用和验证流程。

## 1. 前提条件

| 依赖 | 版本 / 说明 |
|---|---|
| Python | ≥ 3.10（仅本地模式需要） |
| Docker | ≥ 24，含 `docker compose`（容器模式需要） |
| ffmpeg | 推流测试用 |
| MediaMTX | 提供 RTSP 服务，host 端运行 |
| YOLO 模型 | 启用 prefilter 时把 `~/models` 以**恒等路径**挂载到容器同路径（`~/models -> ~/models`） |

YOLO 模型文件（**扁平布局**，host 侧 `~/models` 以恒等路径挂进容器）：

```
~/models/yolo11s.xml
~/models/yolo11s.bin
```

启用 prefilter 前需先按下方 §1.1 导出该模型；不启用 prefilter（`prefilter.enabled: false`）时可跳过。

### 1.1 准备 YOLO11 NPU 模型（仅启用 prefilter 时）

prefilter 用 Intel NPU 上的 YOLO11s OpenVINO IR 做「人/物」快速通过-跳过闸门。下面步骤导出所需模型
文件。

**产物**：`~/models/yolo11s.xml` + `~/models/yolo11s.bin`

- 输入形状：`[1, 3, 704, 1280]`（**静态**；边长取 32 的倍数）
- 精度：**FP16**
- 目标设备：**NPU**

**为什么这么选**：

- **静态 shape**：OpenVINO NPU 插件不支持动态输入，动态 IR 在 NPU 上会编译失败。必须
  `dynamic=False` + 固定 `imgsz`。
- **1280×704**：stream_monitor 喂 1280×720 帧，YOLO11 要求 H/W 是 32 的倍数；1280×704 向下对齐
  （裁掉上下共 16px），避免 letterbox 填充。
- **FP16（非 INT8）**：NPU 原生跑 FP16（Core Ultra 358H NPU 约 12–13ms/帧），省去 INT8 校准数据集
  依赖。
- **yolo11s**（非 n/m）：`s` 在精度/NPU 速度间平衡最好；`n` 对小物体（刀/瓶）掉点多，`m+` 对
  prefilter 这种「快速通过/跳过」的闸门过重。

**前提**：

- Intel Core Ultra / Xeon，带 Arc 集显 NPU；NPU 驱动已装
  （`python3 -c "from openvino import Core; print(Core().available_devices)"` 输出需含 `NPU`）。
- 首次导出需联网下载权重；Python ≥ 3.10。

**导出步骤**（一次性；用独立临时 venv，不污染运行时环境）：

```bash
set -euo pipefail
mkdir -p ~/models
WORK="$HOME/models/_yolo_work"; mkdir -p "$WORK"

# 1. 独立转换 venv
python3 -m venv "$WORK/venv"
"$WORK/venv/bin/pip" install -q ultralytics openvino

# 2. 下载权重（已存在则跳过）
[ -f "$WORK/yolo11s.pt" ] || \
  wget -q https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11s.pt -O "$WORK/yolo11s.pt"

# 3. 导出静态 FP16 IR（H=704, W=1280）→ 产物在 $WORK/yolo11s_openvino_model/
( cd "$WORK" && ./venv/bin/python -c \
  "from ultralytics import YOLO; YOLO('yolo11s.pt').export(format='openvino', dynamic=False, half=True, imgsz=[704,1280])" )

# 4. 拍平到 ~/models/ 根下（VSA / 各 monitor 配置统一引用这两个文件）
cp "$WORK/yolo11s_openvino_model/yolo11s.xml" ~/models/yolo11s.xml
cp "$WORK/yolo11s_openvino_model/yolo11s.bin" ~/models/yolo11s.bin

# 5. 清理转换 venv（保留 .pt 便于重跑）
rm -rf "$WORK/venv"
echo "[prepare-yolo] ready: ~/models/yolo11s.{xml,bin}"
```

**校验**（用 VSA 的 venv，已含 openvino）：

```bash
cd videostream-analytics
.venv/bin/python - <<'PY'
import os
from openvino import Core
c = Core()
m = c.read_model(os.path.expanduser("~/models/yolo11s.xml"))
assert not m.is_dynamic(), "IR 必须是静态 shape 才能上 NPU"
assert tuple(d.get_length() for d in m.input(0).partial_shape) == (1, 3, 704, 1280)
c.compile_model(m, "NPU")   # prefilter 运行时就是这么加载的
print("[verify-yolo] 静态 shape IR 可在 NPU 上编译，OK")
PY
```

预期（Core Ultra 358H NPU）：编译 ~0.1s（热），单帧推理 ~12–13ms @ 1280×704。

**运行时接线**：容器把 host `~/models` 做**恒等挂载**（host X → container X），因此容器模式和本地模式都统一用 host 绝对路径（例如 `$HOME/models/yolo11s.xml`，见 §3 config 示例）。`device: NPU`。

**故障排查**：

| 现象 | 原因 | 处理 |
|---|---|---|
| `Model is not supported by selected device` | 动态 shape IR 上 NPU | 用 `dynamic=False imgsz=[704,1280]` 重新导出 |
| `compile_model` 卡 > 30s | NPU 驱动过旧 | 检查/更新 NPU 驱动到 2024.08+ |
| 推理很慢（> 50ms/帧） | 悄悄回落到 CPU | 配置里显式 `device: NPU`，确认没被切到 `AUTO` |
| 输出张量无命名 output | 正常，yolo11 OV 导出不给 output 命名 | 按下标 `compiled.output(0)` 取（prefilter 已这么做） |

## 2. 安装与启动

源码位于仓库根目录的 `videostream-analytics/` 下。下文示例命令默认在该目录执行。

### 2.1 Docker Compose（推荐）

```bash
cd videostream-analytics
docker compose -f docker/docker-compose.yaml build
docker compose -f docker/docker-compose.yaml up -d
docker compose -f docker/docker-compose.yaml logs -f videostream-analytics
```

环境变量**全部可选**——compose 已内置默认值（`${VAR:-默认}`），`docker compose up -d` 可开箱运行，无需创建 `.env`。  
建议先确认：`${HOME}/models` 可读、`${HOME}/.mcp-smartbuilding` 可写，再按需 `export` 覆盖变量后启动：

| 变量 | 默认 | 说明 |
|---|---|---|
| `WEBHOOK_URL` | `http://localhost:3101/events` | 事件下游 |
| `SMARTBUILDING_DATA_DIR` | `${HOME}/.mcp-smartbuilding` | MCP 数据根（= MCP server 的默认根）。VSA 默认输出根 = `<它>/segments`；并按**恒等路径**挂进容器（host X → 容器 X），使 MCP 下发的 `<它>/segments/<id>` 在容器内解析到同一真实目录 |
| `MODEL_DIR` | `${HOME}/models` | YOLO 模型目录（恒等挂载到容器同路径，`:ro`） |
| `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` | 空 | 仅 build 阶段使用 |

覆盖示例：

```bash
SMARTBUILDING_DATA_DIR=/data/mcp docker compose -f docker/docker-compose.yaml up -d
```

> - 不再需要 `.env` / `DATA_DIR`  —— 都由 compose 默认值 + `export` 覆盖取代。
> - 容器以 **root** 运行，写出的 clip 文件属 root（MCP clip extractor / VLM 读取无碍）。若要让 MCP storage cleaner（以宿主用户跑）能清理这些文件，用 `--user "$(id -u):$(id -g)"` 起容器（见下方 `docker run` 示例）或自行 `chown`。
>
> 常用 `docker run` 模板（和 compose 配置保持一致）：
>
> ```bash
> export SMARTBUILDING_DATA_DIR="${SMARTBUILDING_DATA_DIR:-$HOME/.mcp-smartbuilding}"
>
> # 最小模板（host network + 恒等挂载）
> docker run -d --rm --name vsa-test --network host \
>   -e WEBHOOK_URL="http://localhost:3101/events" \
>   -e SMARTBUILDING_DATA_DIR \
>   -v "${SMARTBUILDING_DATA_DIR}:${SMARTBUILDING_DATA_DIR}" \
>   videostream-analytics:latest
>
> # 完整模板（含模型只读恒等挂载 + 代理 + 非 root）
> docker run -d --rm --name vsa-test --network host \
>   --user "$(id -u):$(id -g)" \
>   -e WEBHOOK_URL="http://localhost:3101/events" \
>   -e SMARTBUILDING_DATA_DIR \
>   -e http_proxy="" -e https_proxy="" -e no_proxy="localhost,127.0.0.1" \
>   -v "${MODEL_DIR:-$HOME/models}:${MODEL_DIR:-$HOME/models}:ro" \
>   -v "${SMARTBUILDING_DATA_DIR}:${SMARTBUILDING_DATA_DIR}" \
>   videostream-analytics:latest
> ```

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
  url: "http://localhost:3101/events"
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
    model_path: "/home/<your_user>/models/yolo11s.xml"   # 容器/host 同路径（恒等挂载，见 §1.1）
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
  "data_dir":    "${SMARTBUILDING_DATA_DIR}/segments/cam_demo",
  "pipeline": {
    "motion":    { "enabled": true, "diff_threshold": 15, "area_ratio": 0.005, "stable_frames": 45 },
    "segment":   { "max_duration": 10, "min_duration": 1.0 },
    "prefilter": { "enabled": false },
    "roi": { "enabled": false, "mode": "crop", "expand": 0.25, "auto_split_area": 0.0 },
    "recording": { "enabled": true, "interval_seconds": 60, "retention_days": 5 },
    "health":    { "max_failures": 30, "recovery_strategy": "retry" },
    "keepalive": { "enabled": false, "timeout_seconds": 90.0, "check_interval_seconds": 10.0 }
  }
}
```

必填：`source_id`、`source_url`。其他字段省略时使用 `config.yaml` 的 `defaults`。`data_dir` 省略时落到 `<config.data_dir>/<source_id>/`。

**`pipeline.keepalive`（Phase 8）**：MCP 端开启后每 ~30s 调 `POST /sources/{id}/keepalive`；VSA 后台 watchdog 每 `check_interval_seconds` 巡检一次，超过 `timeout_seconds` 没收到心跳就**自动 pause** 该 source（不删除，需要 MCP 显式 resume）。默认 OFF — V1–V10 联调脚本无需关心；MCP 实际部署时显式打开。

**`pipeline.roi`（Phase 9，child_safety）**：当 prefilter PASS 且 `roi.enabled=true` 时，VSA 用 prefilter 累计的轨迹 union bbox 生成 `<clip>_input.mp4`，并把 `summary_clip_input` 指向该裁剪片段。`mode` ∈ `crop | highlight | crop_and_concat`（默认 `crop`），`expand` 把 bbox 向外延伸（默认 0.25），`auto_split_area > 0` 时若 union 面积超阈值则提前切 segment（避免大轨迹下 crop 失效，child_safety 建议 0.35）。失败（ffmpeg 缺失 / region 过小 / clip 无法读）自动 fallback 到原片，不抛异常。

### Source 生命周期状态机

`GET /sources/{id}/status` 返回的 `status` 字段取值与触发条件：

| status | 触发条件 | 是否终态 | 退出条件 |
|---|---|---|---|
| `connecting` | `_connect()` 正在尝试打开 RTSP | 否（瞬时态） | 连接成功 → `online`；失败 → `error` |
| `online` | RTSP 连接成功并在抓帧 | 否（事件驱动） | RTSP 失败 → `error` / `reconnecting`；调 `/pause` → `paused` |
| `error` | 单次 RTSP 读失败 | 否（瞬时态） | 进入 `reconnecting` 退避路径 |
| `reconnecting` | 失败但 `failure_count < max_failures`，正在退避重试 | 否 | 连接成功 → `online`；累计到 `max_failures` → `unhealthy` → 进入 `recovery_strategy` 分支 |
| `unhealthy` | 累计失败 ≥ `max_failures` | 否（瞬时态） | 依 `recovery_strategy`：`retry` 继续退避 / `pause` → `paused` / `remove` → `removed` |
| `paused` | 调 `/pause` **或** `recovery_strategy=pause` 触发 **或** Phase 8 keepalive watchdog 超时 | ✅ 终态 | 仅 `/resume` 可切回 `online`；watchdog / health 自身不会自动 resume |
| `removed` | `recovery_strategy=remove` 触发 / source 已注销 | 终态 | source 已从 `_bundles` 删除，需重新 `/register_source` |
| `stopped` | `/stop` / 优雅退出 | 终态 | 同 `removed` |

**关键不变量**：

1. **`reconnecting` 不是终态**。`recovery_strategy=pause` 不等于"任何失败立刻 pause"——VSA 会先累计 `failure_count` 次失败并做指数退避重连，只有累计到 `max_failures` 才触发 pause。以默认 `max_failures=30, backoff_base=2.0, backoff_max=120.0` 为例：

   ```
   失败 1  次 → reconnecting (backoff 2s)
   失败 2  次 → reconnecting (backoff 4s)
   失败 3  次 → reconnecting (backoff 8s)
   ...
   失败 6  次 → reconnecting (backoff 120s, 被 backoff_max 截顶)
   ...
   失败 30 次 → unhealthy → 触发 recovery_strategy → paused
   ```

2. **`paused` 是终态**。watchdog / health 都不会自动切回 online；paused 状态下 RTSP 空闲断连触发的隐式重连也已经在 `_run` 中显式尊重 `_paused` 标志位。任何"paused 之后自动变 online"必然意味着有外部 `/resume` 调用（例如 MCP `monitor-ctl` 恢复动作）。Phase 8 keepalive watchdog 触发的 pause 同样适用——MCP 必须显式 `/resume`。

3. **`failure_count` 在 `online` 成功重连后归零**——所以 RTSP 抖动恢复后计数从头累积。

若需缩短 pause 触发时间做验证，可用 `PUT /sources/{id}/pipeline` 热更新 health 参数：

```bash
curl -X PUT http://localhost:8999/sources/cam_demo/pipeline \
  -H "Content-Type: application/json" \
  -d '{"pipeline": {"health": {"max_failures": 3, "recovery_strategy": "pause", "backoff_base": 1.0, "backoff_max": 5.0}}}'
# 然后 `pkill ffmpeg`，3 次失败（约 1+2+4=7 秒）后 status 变为 paused 并稳定。
```

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

```bash
export PROJECT_ROOT="${PROJECT_ROOT:-$(pwd)}"               # smart-community 根目录
export SMARTBUILDING_DATA_DIR="${SMARTBUILDING_DATA_DIR:-/tmp/vsa-test}"
```

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

# 或容器方式（恒等挂载 SMARTBUILDING_DATA_DIR；VSA 自己推导默认输出根，不再用 /data / RECORDINGS_DIR）
docker run -d --rm --name vsa-test --network host \
  -e WEBHOOK_URL="http://localhost:9999/events" \
  -e SMARTBUILDING_DATA_DIR \
  -v "$HOME/models:$HOME/models:ro" \
  -v "${SMARTBUILDING_DATA_DIR}:${SMARTBUILDING_DATA_DIR}" \
  videostream-analytics:latest

# 或 compose 方式（推荐长期使用）
# 关键：WEBHOOK_URL / SMARTBUILDING_DATA_DIR 需要在执行 compose 的同一终端里 export
WEBHOOK_URL="http://localhost:9999/events" \
SMARTBUILDING_DATA_DIR="/tmp/vsa-test" \
docker compose -f docker/docker-compose.yaml up -d --force-recreate
```

**T4 — 推流（host）**

```bash
ffmpeg -re -stream_loop -1 -ss 40 \
  -i "${PROJECT_ROOT}/demo-videos/cam_child/child_safety_demo.mp4" \
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
  --data-binary @- <<JSON | python3 -m json.tool
{
  "source_id":   "cam_demo",
  "source_url":  "rtsp://localhost:8554/live/child",
  "data_dir":    "${SMARTBUILDING_DATA_DIR}/cam_demo",
  "pipeline": {
    "prefilter": {"enabled": false}
  }
}
JSON
```

期望（首次注册）：`{"status": "started", "source_id": "cam_demo", "data_dir": "${SMARTBUILDING_DATA_DIR}/cam_demo", ...}`

期望（重复注册同一个 `source_id`）：`{"status": "already_running", "source_id": "cam_demo"}`。

如果需要让新的 `webhook_url` / `data_dir` / `pipeline` 全量生效，先删除再注册：

```bash
curl -s -X DELETE http://localhost:8999/sources/cam_demo | python3 -m json.tool
# 然后重跑 V2 的 register_source
```

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
  "data_dir": "${SMARTBUILDING_DATA_DIR}/cam_demo",
  "status": "online",
  "running": true,
  "recording_enabled": true,
  "health": {
    "failure_count": 0,
    "last_failure_time": null,
    "reconnect_count": 0,
    "recovery_strategy": "retry",
    "max_failures": 30,
    "start_time": "..."
  },
  "keepalive_enabled": false,
  "last_keepalive_at": null
}
```

### V4. Motion → clip → webhook（含 recording 支路）

等 30 ~ 60 秒让动作触发。clip 写盘路径由注册体 `data_dir` 决定（V2 注册时传入；省略则落到 `<config.data_dir>/<source_id>/`）：

```bash
# motion 事件 — envelope: {sourceId, type:"motion", timestamp, payload:{event_file_path, summary_clip_input, ...}}
curl -sf http://localhost:9999/recorded_events/motion | python3 -m json.tool | head -60

# recording 事件 — envelope: {sourceId, type:"recording", timestamp, payload:{recording_path, recording_start, ...}}
curl -sf http://localhost:9999/recorded_events/recording | python3 -m json.tool | head -40

DATA_DIR="${SMARTBUILDING_DATA_DIR}/cam_demo"   # 与 V2 register body 中的 data_dir 一致
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
  --data-binary @- <<JSON | python3 -m json.tool
{
  "source_id":   "cam_bad",
  "source_url":  "rtsp://localhost:8554/live/__nonexistent__",
  "data_dir":    "${SMARTBUILDING_DATA_DIR}/cam_bad",
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
}
JSON

sleep 15
curl -sf http://localhost:8999/sources                | python3 -m json.tool
curl -sf http://localhost:9999/recorded_events/status | python3 -m json.tool | head -40
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
cd "$PROJECT_ROOT"
npm install
for pkg in db rule-engine tools mcp-server; do
  (cd packages/$pkg && npx tsc)
done
# 4 个 workspace 都无错误输出
```

**步骤 1：启动 MCP server（替换 T2 mock webhook）**

```bash
# MCP 数据目录（默认是 ${HOME}/.mcp-smartbuilding；如需隔离测试可改成 /tmp/...）
export SMARTBUILDING_DATA_DIR="${SMARTBUILDING_DATA_DIR:-$HOME/.mcp-smartbuilding}"
mkdir -p "$SMARTBUILDING_DATA_DIR"

cd "$PROJECT_ROOT"
node packages/mcp-server/dist/index.js --http \
  --config config.yaml.example \
  --monitors monitor_cam_child.yaml

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
# A) VSA 在 host 进程里跑
cd "$PROJECT_ROOT/videostream-analytics"
WEBHOOK_URL=http://localhost:3101/events \
  .venv/bin/videostream-analytics serve --config config/config.yaml

# B) VSA 在 Docker 跑（推荐 host network，容器内 localhost 就是宿主机）
export SMARTBUILDING_DATA_DIR="${SMARTBUILDING_DATA_DIR:-$HOME/.mcp-smartbuilding}"
docker run -d --rm --name vsa-test --network host \
  -e WEBHOOK_URL="http://localhost:3101/events" \
  -e SMARTBUILDING_DATA_DIR \
  -v "$HOME/models:$HOME/models:ro" \
  -v "${SMARTBUILDING_DATA_DIR}:${SMARTBUILDING_DATA_DIR}" \
  videostream-analytics:latest

# C) VSA 用 docker compose 跑（推荐长期使用）
# 在执行 compose 的同一终端里设置变量，确保容器与 MCP 共享同一数据根
WEBHOOK_URL="http://localhost:3101/events" \
SMARTBUILDING_DATA_DIR="$HOME/.mcp-smartbuilding" \
docker compose -f docker/docker-compose.yaml up -d --force-recreate

# D) 若不能用 --network host（bridge 网络），改用 host.docker.internal
# Linux 需要显式映射 host-gateway
docker run -d --rm --name vsa-test \
  --add-host=host.docker.internal:host-gateway \
  -p 8999:8999 \
  -e WEBHOOK_URL="http://host.docker.internal:3101/events" \
  -e SMARTBUILDING_DATA_DIR \
  -v "$HOME/models:$HOME/models:ro" \
  -v "${SMARTBUILDING_DATA_DIR}:${SMARTBUILDING_DATA_DIR}" \
  videostream-analytics:latest
```

**步骤 3：用 MCP 风格 body 注册 source（`data_dir` 指向 MCP 的 segments dir）**

若 `cam_demo` 已存在，先清理旧 source（避免返回 `already_running`，并确保新的 `data_dir/webhook_url` 生效）：

```bash
curl -s -X DELETE http://localhost:8999/sources/cam_demo | python3 -m json.tool || true
```

```bash
curl -s -X POST http://localhost:8999/register_source \
  -H "Content-Type: application/json" \
  --data-binary @- <<JSON | python3 -m json.tool
{
  "source_id":   "cam_demo",
  "source_url":  "rtsp://localhost:8554/live/child",
  "webhook_url": "http://localhost:3101/events",
  "data_dir":    "${SMARTBUILDING_DATA_DIR}/segments/cam_demo",
  "pipeline": {
    "motion":    {"diff_threshold": 15, "area_ratio": 0.005, "stable_frames": 45},
    "segment":   {"max_duration": 10, "min_duration": 1.0},
    "prefilter": {"enabled": false},
    "recording": {"enabled": true, "interval_seconds": 30, "retention_days": 1},
    "health":    {"max_failures": 30, "recovery_strategy": "retry"}
  }
}
JSON
```

`data_dir` 必须落到 `${SMARTBUILDING_DATA_DIR}/segments/<source_id>/` —— 这是 MCP 的存储清理器假定的布局。MCP 端 `monitor-ctl.ts` 注入这个字段时也用同样的拼接。

**步骤 4：等事件累积，查 MCP DB 三张表**

```bash
sleep 90   # 让 ~3 个 motion 事件 + ~2 个 recording 落 DB

cd "$PROJECT_ROOT/videostream-analytics"
.venv/bin/python <<'EOF'
import os, sqlite3

data_root = os.environ.get("SMARTBUILDING_DATA_DIR", os.path.expanduser("~/.mcp-smartbuilding"))
con = sqlite3.connect(f"{data_root}/smartbuilding.db")
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
snap = f"{data_root}/segments/cam_demo/latest.jpg"
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
  --data-binary @- <<JSON | python3 -m json.tool
{
  "source_id":   "cam_ka",
  "source_url":  "rtsp://localhost:8554/live/child",
  "data_dir":    "${SMARTBUILDING_DATA_DIR}/segments/cam_ka",
  "pipeline": {
    "prefilter": {"enabled": false},
    "recording": {"enabled": false},
    "keepalive": {"enabled": true, "timeout_seconds": 3.0, "check_interval_seconds": 1.0}
  }
}
JSON

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

**前置条件**：NPU YOLO 模型文件（容器/host 同路径，例如 `$HOME/models/yolo11s.xml`，见 §1.1），
以及一段含 person 的视频（如 `demo-videos/cam_child/child_safety_demo.mp4`）。

#### Step 1 — 启动支撑服务（4 个终端）

复用第 7 节开头的 T1 / T2 / T4。`T3` 的 `WEBHOOK_URL` 需指向 mock webhook：

```bash
# T1 MediaMTX (:8554) —— RTSP server，接收 ffmpeg 推流并转发给 VSA
~/.local/bin/mediamtx /path/to/mediamtx.yml

# T2 Mock webhook (:9999) —— 用于测试的 MCP /events 端点替身，记录 VSA 推送的事件
cd videostream-analytics && source .venv/bin/activate
python -m uvicorn tests.integration.mock_webhook_server:app --host 0.0.0.0 --port 9999

# T3 VSA (:8999) —— 主服务；WEBHOOK_URL 环境变量决定事件下游
WEBHOOK_URL=http://localhost:9999/events \
  .venv/bin/videostream-analytics serve --config config/config.yaml

# T4 ffmpeg 推流 —— 以本地 mp4 作为 RTSP 源推送给 MediaMTX
ffmpeg -re -stream_loop -1 -i "${PROJECT_ROOT}/demo-videos/cam_child/child_safety_demo.mp4" \
  -c copy -f rtsp rtsp://localhost:8554/live/child
```

#### Step 2 — 注册 `child_safety` 风格的 source

```bash
curl -s -X POST http://localhost:8999/register_source \
  -H "Content-Type: application/json" \
  --data-binary @- <<JSON | python3 -m json.tool
{
  "source_id":   "cam_child_roi",
  "source_url":  "rtsp://localhost:8554/live/child",
  "data_dir":    "${SMARTBUILDING_DATA_DIR}/segments/cam_child_roi",
  "pipeline": {
    "prefilter": {
      "enabled": true,
      "model_path": "${MODEL_DIR:-$HOME/models}/yolo11s.xml",
      "target_classes": ["person"],
      "detect_fps": 2.0,
      "device": "NPU"
    },
    "roi": {
      "enabled": true,
      "mode": "crop",
      "expand": 0.25,
      "auto_split_area": 0.35
    },
    "recording": {"enabled": false}
  }
}
JSON
```

字段说明：

| 字段 | 含义 |
|---|---|
| `source_id` / `source_url` | source 标识与 RTSP 拉流地址 |
| `data_dir` | 该 source 所有产出文件（`motion_events/`、`latest.jpg`）的根目录 |
| `prefilter.enabled=true` | 启用 YOLO 后筛，仅上报识别到目标类别的 motion 事件 |
| `prefilter.model_path` | OpenVINO 模型绝对路径；文件缺失时 prefilter 降级为禁用，pipeline 继续运行 |
| `prefilter.detect_fps=2.0` | YOLO 推理频率上限（Hz） |
| `prefilter.device=NPU` | OpenVINO device，可选 `NPU` / `GPU` / `CPU` |
| `roi.enabled=true` | Phase 9 开关；启用后生成 `_input.mp4` 并在 payload 附加 `trajectory_region` |
| `roi.mode=crop` | ROI 模式：`crop`（裁剪 union bbox 区域）/ `highlight`（原图 + 高亮框）/ `crop_and_concat`（原图与逐帧人像并排，需要 YOLO 每帧推理） |
| `roi.expand=0.25` | union bbox 向外扩展 25% |
| `roi.auto_split_area=0.35` | 当 union 面积超过 35% 帧面积时，提前切 segment，避免长 clip 上 crop 失效 |
| `recording.enabled=false` | 关闭固定时长录像分支，仅验证 motion 路径 |

期望响应：`{"status": "started", "source_id": "cam_child_roi", "source_url": "...", "data_dir": "${SMARTBUILDING_DATA_DIR}/cam_child_roi"}`。

#### Step 3 — 等待 motion 事件累积

```bash
# 等 60 秒累积至少 1 条 prefilter PASS 事件
sleep 60
```

若 60 秒内 mock webhook 未收到事件（`curl /recorded_events` 为空），按顺序排查：

1. **VSA 进程是否已加载最新代码**：`ps -o lstart= -p $(pgrep -f videostream-analytics)` 与 `stat -c '%y' stream_monitor/rtsp_monitor.py shared/config.py` 对比。进程启动时间早于源文件 mtime，需 kill + 重启。
2. **`WEBHOOK_URL` 是否指向本轮验证目标**：`tr '\0' '\n' < /proc/$(pgrep -f videostream-analytics)/environ | grep WEBHOOK_URL` 应输出 `http://localhost:9999/events`。地址错误时 webhook 无事件但磁盘 motion clip 仍会写出。
3. **RTSP 推流是否正常**：T4 终端无错误；`ffprobe rtsp://localhost:8554/live/child` 能列出流信息。
4. **motion 是否触发**：VSA 日志中出现 `Motion started`；如未出现，减小 `motion.diff_threshold` 或使用动作幅度更大的素材。
5. **prefilter 是否 PASS**：VSA 日志中出现 `Prefilter PASS`；如未出现，检查视频内容与 `min_confidence`。prefilter SKIP 时 motion clip 会被删除；若磁盘存在 mp4 但 webhook 无事件，问题在第 1 / 2 项，不在 prefilter。

#### Step 4 — 验证 webhook payload

```bash
curl -sf http://localhost:9999/recorded_events/motion | python3 -c "
import json, sys
events = json.load(sys.stdin)['events']
print(f'motion events received: {len(events)}')
e = events[0]
p = e['payload']
print('trajectory_region :', p.get('trajectory_region'))
print('summary_clip_input:', p.get('summary_clip_input'))
print('event_file_path   :', p.get('event_file_path'))
print('prefilter_passed  :', p.get('prefilter_passed'))
"
```

字段说明：
- `trajectory_region`：JSON string `"[x0,y0,x1,y1]"`，4 个归一化坐标 ∈ [0,1]，为 prefilter 累积的 union bbox。MCP 端 `events-endpoint.ts` 消费该字段。
- `summary_clip_input`：若与 `event_file_path` 不同，则说明 ROI crop 已成功生成 `_input.mp4`；相等则表示 ROI crop 失败并回退到原 clip。
- `event_file_path`：原始 motion clip 路径。VLM 消费的是 `summary_clip_input`，原 clip 仅作存档。
- `prefilter_passed`：启用 prefilter 时应为 `1`（SKIP 的 clip 不会 emit）。

#### Step 5 — 验证磁盘上的 `_input.mp4`

```bash
DATA_DIR="${SMARTBUILDING_DATA_DIR}/segments/cam_child_roi"
TODAY=$(date +%Y-%m-%d)

# 5.1 文件存在
ls -la "$DATA_DIR/motion_events/$TODAY/"*_input.mp4

# 5.2 编码与分辨率
INPUT=$(ls "$DATA_DIR/motion_events/$TODAY/"*_input.mp4 | head -1)
ffprobe -v error -show_entries stream=codec_name,width,height,duration -of default=nw=1 "$INPUT"

# 5.3 对比原 clip 尺寸
ORIG="${INPUT%_input.mp4}.mp4"
ffprobe -v error -show_entries stream=width,height -of csv=p=0 "$ORIG"
ffprobe -v error -show_entries stream=width,height -of csv=p=0 "$INPUT"
```

字段说明：
- **5.1**：文件不存在则说明 ROI crop 未产出。
- **5.2**：`codec_name=h264` 表示 ffmpeg h264 重编码成功；`codec_name=mpeg4`（mp4v）为 ffmpeg 缺失或重编码失败时的降级输出，两者均视为 PASS。
- **5.3**：`_input.mp4` 尺寸应显著小于原 clip；若两者尺寸完全一致，说明 ROI crop 未生效。

#### Step 6 — 验证 `auto_split_area` 早切（可选）

**前提：把日志级别调到 DEBUG。** 早切日志在代码里是 `logger.debug("... Segment early-split by trajectory union")`（见 `stream_monitor/rtsp_monitor.py`），而 `config/config.yaml` 默认 `logging.level: "INFO"` —— DEBUG 日志根本不输出，即使早切真的触发，INFO 级别下也 grep 不到（空结果是预期的）。验证前先改配置：

```bash
# config/config.yaml 里把 logging.level 从 INFO 改成 DEBUG
sed -i 's/level: "INFO"/level: "DEBUG"/' config/config.yaml
```

VSA 默认仅通过 `StreamHandler(sys.stdout)` 输出日志。启动 VSA 时重定向到文件后可搜索早切事件：

```bash
WEBHOOK_URL=http://localhost:9999/events \
  .venv/bin/videostream-analytics serve --config config/config.yaml \
  > "${SMARTBUILDING_DATA_DIR}/vsa.log" 2>&1 &

grep "Segment early-split by trajectory union" "${SMARTBUILDING_DATA_DIR}/vsa.log"
```

当画面动作幅度大、union 面积超过 `auto_split_area`（本例为 `0.35`）时会记录该日志。**注意需同时满足两个条件才能 grep 到**：① `logging.level: DEBUG`（上一步已改）；② 早切分支被真正走到（`prefilter.enabled=true` 且 `roi.enabled=true` 且 `auto_split_area>0` 且 union 面积在 segment 间隔到达前就超阈值）。未触发不视为失败；如需强制触发，将 `auto_split_area` 调低至 `0.05` 后重新注册。

#### 通过标准（须同时满足以下 4 项）

1. `payload.trajectory_region` 为包含 4 个 ∈ [0,1] 浮点数的 JSON string，不为 null 或缺失。
2. `payload.summary_clip_input` 以 `_input.mp4` 结尾，且与 `event_file_path` 不同。
3. `_input.mp4` 物理存在，`ffprobe` 无错误输出（h264 或 mp4v 均可）。
4. crop 模式下 `_input.mp4` 尺寸显著小于原 clip。

#### 对接真 MCP server（替代 T2 mock）

参考 V10。T2 替换为真 MCP server，T3 的 `WEBHOOK_URL` 改为 `http://localhost:3101/events`，事件累积后查询 MCP DB。

MCP 现在用**全局单一** DB（`${SMARTBUILDING_DATA_DIR:-$HOME/.mcp-smartbuilding}/smartbuilding.db`），所有 monitor 共用一张 `events` 表并以 `monitor_id` 列区分 —— 不再是旧版每 monitor 一个 `~/.smartbuilding-video/data/<id>/pipeline.db`。查询时按 `monitor_id` 过滤：

```bash
sqlite3 "${SMARTBUILDING_DATA_DIR:-$HOME/.mcp-smartbuilding}/smartbuilding.db" \
  "SELECT id, motion_type, event_file_path, trajectory_region FROM events \
   WHERE monitor_id='cam_child_roi' ORDER BY id DESC LIMIT 3;"
```

期望：`events.trajectory_region` 列非空，且与 webhook payload 一致。

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
# 启动（直接 docker run，便于单测；恒等挂载 SMARTBUILDING_DATA_DIR）
export SMARTBUILDING_DATA_DIR="${SMARTBUILDING_DATA_DIR:-$HOME/.mcp-smartbuilding}"
docker run -d --rm --name vsa-test --network host \
  -e WEBHOOK_URL="http://localhost:9999/events" \
  -e SMARTBUILDING_DATA_DIR \
  -e no_proxy="localhost,127.0.0.1" \
  -e http_proxy="" -e https_proxy="" \
  -v "$HOME/models:$HOME/models:ro" \
  -v "${SMARTBUILDING_DATA_DIR}:${SMARTBUILDING_DATA_DIR}" \
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

容器通过**恒等挂载**把 host 的 `SMARTBUILDING_DATA_DIR` 挂到容器内同名绝对路径，clip 直接落在 host（不再有独立 `/data` 映射）；VSA 默认输出根 = `<SMARTBUILDING_DATA_DIR>/segments`，注册体里显式的 `data_dir` 优先。YOLO 模型目录也采用恒等挂载（`${MODEL_DIR:-$HOME/models}` → `${MODEL_DIR:-$HOME/models}`）。

权限提醒：容器默认 root 运行，挂载目录中的新文件会是 root 属主。若希望与宿主用户权限一致，可用 `docker run --user "$(id -u):$(id -g)" ...`，或使用 compose：

```bash
# 让 compose 里的 user: "${UID}:${GID}" 生效
UID="$(id -u)" GID="$(id -g)" docker compose -f docker/docker-compose.yaml up -d
```

```yaml
# docker/docker-compose.yaml 示例（可选）
services:
  videostream-analytics:
    user: "${UID:-1000}:${GID:-1000}"
```

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
| child | `demo-videos/cam_child/child_safety_demo.mp4` | child_safety |
| fridge | `demo-videos/cam_fridge/demo006-2_expanded_20min_v2.mp4` | fridge |
| elder_day1 | `demo-videos/cam_elder_bedroom/day1_elder_wakeup.mp4` | elder_wakeup |
| elder_day2 | `demo-videos/cam_elder_bedroom_2/day2_elder_wakeup.mp4` | elder_wakeup |

> "use case 标签" 仅作为评估工具内部分组，**不传给 VSA `register_source`**（Phase 7 起 VSA 注册体不再接受 `use_case` 字段，use case 归属在 MCP 端管理）。

每个场景的输出：webhook 事件 JSON、clip mp4、prefilter 命中率统计、ASCII 时间线图（`tools/render_eval_timeline.py`）。
