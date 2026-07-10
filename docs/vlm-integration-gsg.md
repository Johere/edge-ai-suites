# VLM Integration — Get Started Guide

本文档面向"给一个 **新 use case** 接入 VLM 服务"的完整流程。它填补了几份 GSG
之间的空档：

- [vsa-gsg.md](./vsa-gsg.md) 只覆盖 VSA 单服务（motion / prefilter / webhook）
- [use-case-adapter-gsg.md](./use-case-adapter-gsg.md) 假定 `summary_text` 已经在 DB 里，只测 rule / cooldown 层
- **本文档** 补齐中间的一层：**如何起 VLM、把 use case prompt 注册进去、如何验证 VLM 对特定视频的输出**

场景族的完整语义视图见 [use-case-catalog.md](./use-case-catalog.md)；
适配器写法见 [use-case-adapter.md](./use-case-adapter.md)。

---

## 1. VLM 服务架构与依赖

源码位于仓库根目录下。下文示例命令除特别说明外，默认从仓库根目录执行。

VLM 由两个 Docker 容器组成，分别在 `docker/` 下用两份 compose 文件管理，
`multilevel-video-understanding/compose.yaml` 通过 `depends_on` 编排它一起起：

```
docker/
├── vllm-serving/               # 独立起 vLLM 用（不带 multilevel）
│   ├── compose.yaml
│   ├── set_env_qwen3.5.sh
│   └── test_resources/         # start_server_enable_cache.sh + patch py
└── multilevel-video-understanding/
    ├── compose.yaml            # 同时定义 vllm-ipex-serving + multilevel
    ├── set_env.sh              # 默认：vllm 与 multilevel 都本地 docker 起
    └── set_env-dev.sh          # 开发：multilevel 本地起，vllm 走远端 IP
```

拓扑：

```
┌──────────────────────────────────────────────────────────┐
│  vllm-ipex-serving   (Intel XPU + FP8 vLLM)              │
│  外部端口 :41091 → 容器内 :8000                            │
│  跑 Qwen/Qwen3.5-* 模型（默认 Qwen3.5-35B-A3B FP8         │
│    首次会拉 ~70 GB weights；可切 9B-AWQ / 35B-AWQ）        │
│  首次启动做 FP8 编译，3-20 分钟；含首次拉模型 30-120 min    │
│  entrypoint 从 ../vllm-serving/test_resources/ 拉起脚本   │
└──────────────▲───────────────────────────────────────────┘
               │  HTTP /v1/chat/completions（app-network 内）
               │
┌──────────────┴───────────────────────────────────────────┐
│  multilevel-video-understanding                           │
│  外部端口 :8192 → 容器内 :8000                             │
│  视频 clip → ffmpeg 抽帧 → 组合 chat/completions →         │
│    按 task prompt 输出 summary_text                       │
│  build context: ../../edge-ai-libraries/microservices/    │
│                 multilevel-video-understanding            │
│  内置 task（仅这 6 个）：                                   │
│    summary / engine_valves_sop /                          │
│    refrigerator_monitor / refrigerator_monitor_en /       │
│    daily_report / daily_report_en                         │
│  其他 task（含 child_safety_monitor / elder_wakeup_monitor │
│    / high_altitude_monitor / parking_safety_monitor）     │
│    **必须运行时通过 POST /v1/tasks 动态注册**              │
│  depends_on vllm-ipex-serving healthy —— vllm 起来后才 start │
└──────────────────────────────────────────────────────────┘
```

**硬性依赖**：

| 依赖 | 说明 |
|---|---|
| Intel XPU / iGPU | `/dev/dri/renderD128` 必须存在；`video` + `render` group 都要有 |
| Docker + compose v2 | 用 `docker compose`（不是 `docker-compose`）|
| `HF_HOME` 目录 | 默认 `~/models/huggingface`；首次会拉模型（几 GB - 几十 GB）|
| `edge-ai-libraries` submodule | multilevel 的 build context 引用它。首次使用 `git submodule update --init --recursive` |
| `VIDEO_SUMMARY_CACHE_HOST` | 默认 `~/.cache/.multilevel-video-understanding`，必须**用户自己 mkdir**，否则 docker 会以 root 建（`set_env.sh` 里已自动 `mkdir -p`）|
| 可选：swap 32 GB | 35B FP8 编译期内存高峰会 OOM；按所在环境的 swap helper 或系统方式配置 |

**smart-community 侧对应配置**（`config.yaml.example`）：

```yaml
summary_service:
  url: http://localhost:8192          # multilevel-video-understanding
  path_remap:
    host_prefix: ${HOME}/.mcp-smartbuilding    # 必须与 SMARTBUILDING_DATA_DIR 一致
    container_prefix: /data                    # 与 compose.yaml volume 一致
vlm_service:
  url: http://localhost:41091/v1      # vllm-ipex-serving 直连（scene_query 用）
  model: Qwen/Qwen3.5-35B-A3B         # 必须与 /v1/models 返回的 id 一致
  max_edge_px: 720
```

`summary_service.url` 是 task-poller 消费的服务端点；`vlm_service.url` 是
`smartbuilding_scene_query` 单帧问答的直连端点（本文档主要关注前者）。

**Data 目录三方一致（important invariant）**：MCP 端 `SMARTBUILDING_DATA_DIR`
（默认 `~/.mcp-smartbuilding`）、`docker/multilevel-video-understanding/set_env.sh`
里同名变量、`config.yaml.example` 的 `summary_service.path_remap.host_prefix`
**必须指向同一个宿主机目录**，否则容器内 `/data/segments/<monitor>/motion_events/...`
读不到 MCP 写下的 clip，`/v1/summary` 会返 400 `Local file not found`。

---

## 2. 启动 VLM 服务

> 若之前跑过旧的视频摘要 stack，先停掉它避免端口 (`:41091` / `:8192`) 冲突。
> 例如旧 stack 在 sibling 仓库时：
>
> ```bash
> cd ../agent-ai.smarthome/start-video-summary-service/end2end
> source ./set_env.sh && docker compose down
> ```

### 2.1 首次启动（vllm + multilevel 一起本地起）

```bash
cd docker/multilevel-video-understanding

# 1) 拉 submodule（首次；edge-ai-libraries 是 multilevel 的 build context）
git -C ../.. submodule update --init --recursive

# 2) 建模型缓存目录
mkdir -p ~/models/huggingface

# 3) 加载环境（暴露 XPU 组 / 模型名 / 端口 / SMARTBUILDING_DATA_DIR /
#    VIDEO_SUMMARY_CACHE_HOST 等；同时会 mkdir prompt cache）
source ./set_env.sh

# 4) 起容器（vllm + multilevel；vllm depends 让 multilevel 等 healthy）
docker compose up -d

# 5) 观察启动进度
docker compose logs -f vllm-ipex-serving
# 首次跑 35B：拉 model ~70 GB（可能 30-90 min，取决于网速）
# → 拉完后 FP8 编译 3-20 min
# → 最终看到 "Uvicorn running on http://0.0.0.0:8000" 表示 vLLM ready
# multilevel-video-understanding 会等 vLLM healthy 之后再自动启动
```

**vllm 起来但 multilevel 还没起**（如"vllm 3 分钟 up 但 8192 端口不通"）：这是**正常
中间状态**——vllm 需要通过 healthcheck 才会触发 multilevel 启动。用下面命令观察：

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E "vllm|multilevel"
# 目标：两行都是 "Up ... (healthy)"
```

**判断模型下载 vs 加载卡住**：如果 `docker compose logs vllm-ipex-serving`
最后一行是 `Using Flash Attention backend` 之类且长时间无更新，看下载进度：

```bash
du -sh ~/models/huggingface/hub/models--Qwen--Qwen3.5-*/
ls ~/models/huggingface/hub/models--Qwen--Qwen3.5-*/blobs/*.incomplete 2>/dev/null | wc -l
```

若 `.incomplete` 文件数 > 0 或目录大小还在长（`docker stats vllm-ipex-serving`
的 NET I/O 持续增长），说明**在下载**而非死锁——等就行。

### 2.2 探活

```bash
# vLLM 层（模型是否加载好）
curl -sf http://localhost:41091/v1/models | jq .
# 期望：{"data": [{"id": "Qwen/Qwen3.5-35B-A3B", ...}], ...}

# multilevel-video-understanding 层
curl -sf http://localhost:8192/v1/health
# 期望：{"status": "ok"} 或类似

# 若 multilevel 层 curl 空响应，说明它还没起（vllm 尚未 healthy）
docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E "vllm|multilevel"

# 看内置 task 列表（这也是 multilevel 起来后的第一件事该检查的）
curl -sf http://localhost:8192/v1/tasks | jq '.tasks[].name'
# 期望包含至少：summary, engine_valves_sop, refrigerator_monitor,
#              refrigerator_monitor_en, daily_report, daily_report_en
```

### 2.3 只起 vllm（远端 / 独立使用）

如果只想跑 vllm 不想跑 multilevel（比如另开机器跑 multilevel、或只用 scene_query）：

```bash
cd docker/vllm-serving
source ./set_env_qwen3.5.sh
docker compose up -d
```

注意这份 compose 只声明了 vllm，volume 挂的是本目录下 `./test_resources`。
和 `multilevel-video-understanding/compose.yaml` 里的 vllm 服务定义**是两份，不共享**——不要同时起，端口会冲突。

### 2.4 Dev 模式：multilevel 本地起 + vllm 走远端

用 `set_env-dev.sh` 代替 `set_env.sh`：

```bash
cd docker/multilevel-video-understanding

# set_env-dev.sh 里改成远端 vllm，例如 http://10.67.116.201:41091/v1
source ./set_env-dev.sh

# 只起 multilevel（跳过 dependencies）
docker compose up -d --no-deps multilevel-video-understanding
```

用途：本地机器没足够显存跑 35B，直接用一台已经起好 vllm 的机器；调 prompt / task
时避免每次都本地重编 vllm。

### 2.5 停 / 重启

```bash
cd docker/multilevel-video-understanding
source ./set_env.sh                            # 每次都要先 source（compose 用其中的 env）
docker compose down                            # 停两个
docker compose restart multilevel-video-understanding   # 仅重启 video 服务
docker compose logs -f --tail=100 multilevel-video-understanding
```

**注意**：`vllm-ipex-serving` 冷启动很贵（拉模型 + FP8 编译），除非切换模型，
日常调 prompt / task 只重启 `multilevel-video-understanding`。

**注意 2**：重启 multilevel 会**丢掉动态注册的 task**吗？不会。
`VIDEO_SUMMARY_CACHE_HOST/tasks` 是宿主机目录挂到容器
`/home/appuser/.cache/.multilevel-video-understanding` 作 registry 持久化；
容器重启不会清空。只在你自己 `rm -rf $VIDEO_SUMMARY_CACHE_HOST/tasks/*` 时才丢。

### 2.6 切换模型

修改 `docker/multilevel-video-understanding/set_env.sh`：

```bash
# 快速迭代（对硬件要求低，回答质量一般；FP8 走不了要用 AWQ）
export LLM_MODEL=QuantTrio/Qwen3.5-9B-AWQ
export MAX_MODEL_LEN=32768

# 中等
export LLM_MODEL=Qwen/Qwen3.5-9B
export MAX_MODEL_LEN=49152

# 高质量（35B FP8，需要 64+ GB 内存 + swap；当前 set_env.sh 默认）
export LLM_MODEL=Qwen/Qwen3.5-35B-A3B
export MAX_MODEL_LEN=61440
```

`set_env.sh` 会根据 LLM_MODEL 名字里是否含 "awq" 自动切 `LOAD_QUANTIZATION`
与 `GPU_MEM_UTIL`（awq/sym_int4 → 0.5，fp8 → 0.7）。

改完 `source ./set_env.sh && docker compose up -d` 触发重建。

---

## 3. 为新 use case 注册 VLM Task

VLM 服务用**task 注册表**把 prompt 与 use case 绑定。一个 task 由 4 段
Python-style 常量组成：

| 常量 | 用途 |
|---|---|
| `LOCAL_PROMPT` | 每 chunk 推理时用，定义 VLM 单段输出格式（必须与 smart-community 端 `schema.video_summary_tasks.extensions` 里的字段名对齐） |
| `MACRO_CHUNK_PROMPT` | 多个 chunk 合并时用 |
| `GLOBAL_PROMPT` | 整段视频最终汇总用（daily-report 消费）|
| `T_MINUS_1_PROMPT` | 前一 chunk 上下文（提供 `{past_summary}`）|

注册方式两种：`autogen`（服务端 LLM 自动补齐 4 段）或 `full`（客户端提交完整 4 段）。
**smart-community 的 prompt.md** 通常已经准备好 GLOBAL / MACRO / LOCAL 段，推荐 `full` 模式。

**本 repo 里 4 个已定义 use case，全部都需要动态注册**（因为它们不是 6 个内置 task 之一）：

| use case | task_name | prompt 文件 |
|---|---|---|
| `child_safety` | `child_safety_monitor` | `use-cases/child_safety/prompt.md` |
| `elder_wakeup` | `elder_wakeup_monitor` | `use-cases/elder_wakeup/prompt.md` |
| `high_altitude_safety` | `high_altitude_monitor` | `use-cases/high_altitude_safety/prompt.md` |
| `parking_safety` | `parking_safety_monitor` | `use-cases/parking_safety/prompt.md` |

fridge 用 `refrigerator_monitor` / `refrigerator_monitor_en` 是**内置**，不用注册。

### 3.1 通用注册脚本

以 use case `<uc_name>` + prompt 文件 `use-cases/<uc_name>/prompt.md` 为例：

```bash
UC=child_safety                            # 与 config.yaml use_case_dict.<uc> 对应
TASK=child_safety_monitor                  # 与 use_case_dict.<uc>.video_summary_task 对应
PROMPT_MD=$PWD/use-cases/${UC}/prompt.md

# 从 prompt.md 抽 GLOBAL / MACRO / LOCAL / T_MINUS_1 段（按 `## <NAME>` 分段）
python3 - <<PY > /tmp/register-${UC}.json
import re, json, pathlib

md = pathlib.Path("$PROMPT_MD").read_text(encoding="utf-8")
sections = {}
current, buf = None, []
for line in md.splitlines():
    m = re.match(r"^##\s+([A-Z0-9_]+)\s*\$", line)
    if m:
        if current:
            sections[current] = "\n".join(buf).strip()
        current, buf = m.group(1), []
    elif current:
        buf.append(line)
if current:
    sections[current] = "\n".join(buf).strip()

# 4 段：LOCAL 必填；GLOBAL 可选；MACRO / T_MINUS_1 用简版兜底
LOCAL = sections.get("LOCAL_PROMPT", "")
GLOBAL = sections.get("GLOBAL_PROMPT", LOCAL)   # fallback
MACRO = sections.get("MACRO_CHUNK_PROMPT",
    "Merge sub-chunks into a window narrative. "
    "Start time: {st_tm}s, End time: {end_tm}s. User question: {question}")
TMINUS = sections.get("T_MINUS_1_PROMPT",
    "Previous {dur}s summary below; do not copy. "
    "Start time: {st_tm}s, End time: {end_tm}s. {past_summary}")

# 组成注册体，text 字段是完整的 4 常量 Python 源码
text = (
    f"GLOBAL_PROMPT = '''{GLOBAL}'''\n\n"
    f"MACRO_CHUNK_PROMPT = '''{MACRO}'''\n\n"
    f"LOCAL_PROMPT = '''{LOCAL}'''\n\n"
    f"T_MINUS_1_PROMPT = '''{TMINUS}'''\n"
)
body = {
    "task_name": "$TASK",
    "mode": "full",
    "description": "Auto-registered from $PROMPT_MD",
    "content": {"text": text},
}
print(json.dumps(body, ensure_ascii=False))
PY

curl -sS -X POST http://localhost:8192/v1/tasks \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/register-${UC}.json | jq .

# 校验注册成功
curl -sS http://localhost:8192/v1/tasks | jq ".tasks[] | select(.name==\"${TASK}\")"
```

**注意 task_name 命名规则**（服务端 pydantic 校验）：
- 全小写 ascii，2-64 字符，允许下划线
- 正则 `^[a-z][a-z0-9_]{1,63}$`
- **不能与内置 task 重名**（builtins：`summary` / `engine_valves_sop` / `refrigerator_monitor` /
  `refrigerator_monitor_en` / `daily_report` / `daily_report_en`）——冲突返 409。

### 3.2 一键注册全部 4 个 use case（本 repo 常用，脚本可直接跑）

fridge 用内置 `refrigerator_monitor_en`，不用注册。其余 4 个（child_safety / elder_wakeup /
high_altitude_safety / parking_safety）批量注册：

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO=$(pwd)
VLM=http://localhost:8192

# 前置：服务必须 up
curl -sf ${VLM}/v1/tasks >/dev/null || { echo "VLM :8192 not up"; exit 1; }

register_one () {
    local UC=$1
    local TASK=$2
    local PROMPT_MD=${REPO}/use-cases/${UC}/prompt.md
    [[ -f "$PROMPT_MD" ]] || { echo "missing $PROMPT_MD"; return 1; }

    local BODY_JSON=/tmp/register-${UC}.json
    UC="$UC" TASK="$TASK" PROMPT_MD="$PROMPT_MD" \
    python3 - <<'PY' > "$BODY_JSON"
import os, re, json, pathlib

md = pathlib.Path(os.environ["PROMPT_MD"]).read_text(encoding="utf-8")

sections, current, buf = {}, None, []
for line in md.splitlines():
    m = re.match(r"^##\s+([A-Z0-9_]+)\s*$", line)
    if m:
        if current: sections[current] = "\n".join(buf).strip()
        current, buf = m.group(1), []
    elif current is not None:
        buf.append(line)
if current: sections[current] = "\n".join(buf).strip()

LOCAL  = sections.get("LOCAL_PROMPT", "")
GLOBAL = sections.get("GLOBAL_PROMPT", LOCAL)
MACRO  = sections.get("MACRO_CHUNK_PROMPT",
    "Merge sub-chunks into a window narrative. "
    "Start time: {st_tm}s, End time: {end_tm}s. User question: {question}")
TMINUS = sections.get("T_MINUS_1_PROMPT",
    "Previous {dur}s summary below; do not copy. "
    "Start time: {st_tm}s, End time: {end_tm}s. {past_summary}")

text = (
    f"GLOBAL_PROMPT = '''{GLOBAL}'''\n\n"
    f"MACRO_CHUNK_PROMPT = '''{MACRO}'''\n\n"
    f"LOCAL_PROMPT = '''{LOCAL}'''\n\n"
    f"T_MINUS_1_PROMPT = '''{TMINUS}'''\n"
)
print(json.dumps({
    "task_name": os.environ["TASK"],
    "mode": "full",
    "description": f"Auto-registered from use-cases/{os.environ['UC']}/prompt.md",
    "content": {"text": text},
}, ensure_ascii=False))
PY

    # 先尝试注册，冲突则 PATCH
    local HTTP
    HTTP=$(curl -sS -o /tmp/resp-${UC}.json -w "%{http_code}" \
        -X POST ${VLM}/v1/tasks \
        -H 'Content-Type: application/json' \
        --data-binary @"$BODY_JSON")
    if [[ "$HTTP" == "409" ]]; then
        echo "  $TASK exists → PATCH"
        curl -sS -X PATCH ${VLM}/v1/tasks/${TASK} \
            -H 'Content-Type: application/json' \
            --data-binary @"$BODY_JSON" | jq -r '.name + " updated"'
    elif [[ "$HTTP" == "201" || "$HTTP" == "200" ]]; then
        echo "  $TASK registered"
    else
        echo "  $TASK FAILED (HTTP $HTTP):"; cat /tmp/resp-${UC}.json; return 1
    fi
}

for pair in \
    "child_safety:child_safety_monitor" \
    "elder_wakeup:elder_wakeup_monitor" \
    "high_altitude_safety:high_altitude_monitor" \
    "parking_safety:parking_safety_monitor"; do
    UC=${pair%:*}; TASK=${pair#*:}
    echo "=== $UC → $TASK ==="
    register_one "$UC" "$TASK"
done

# 校验：应看到 4 个 dynamic + 6 个 builtin
curl -sS ${VLM}/v1/tasks | jq '.tasks[] | {name, source}'
```

存成 `/tmp/register-all.sh && bash /tmp/register-all.sh` 就能一次全注册。跑完
`curl -sf ${VLM}/v1/tasks | jq '.tasks[].name'` 应看到：

```
"summary", "engine_valves_sop",
"refrigerator_monitor", "refrigerator_monitor_en",
"daily_report", "daily_report_en",
"child_safety_monitor",           ← dynamic
"elder_wakeup_monitor",           ← dynamic
"high_altitude_monitor",          ← dynamic
"parking_safety_monitor"          ← dynamic
```

### 3.3 更新 / 删除 task

```bash
# 只改 description
curl -sS -X PATCH http://localhost:8192/v1/tasks/${TASK} \
  -H 'Content-Type: application/json' \
  -d '{"description":"v2 refined"}' | jq .

# 完全重写 4 段（同注册体形态；heat update，不用重启容器）
curl -sS -X PATCH http://localhost:8192/v1/tasks/${TASK} \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/register-${UC}.json | jq .

# 删除动态注册的 task（内置 task 会返 403 builtin_immutable）
curl -sS -X DELETE http://localhost:8192/v1/tasks/${TASK} -w "%{http_code}\n"
```

### 3.4 查看某个 task 完整 prompt（debug 用）

```bash
curl -sS http://localhost:8192/v1/tasks/${TASK} | jq -r '.content' | head -40
```

`content` 是一整段 GLOBAL_PROMPT / MACRO_CHUNK_PROMPT / LOCAL_PROMPT / T_MINUS_1_PROMPT
锚点风格的文本，格式与你 POST 时的 `content.text` **round-trip 安全**——可直接复制
再 POST/PATCH 提交更新。

---

## 4. 视频文件挂载

VLM 容器内**读不到 host 任意路径的视频**——它只能访问挂进来的 volume。看
`smart-community/docker/multilevel-video-understanding/compose.yaml`：

```yaml
volumes:
  - ${SMARTBUILDING_DATA_DIR:-${HOME}/.mcp-smartbuilding}:/data:ro
  - ${VIDEO_SUMMARY_CACHE_HOST}:/home/appuser/.cache/.multilevel-video-understanding:rw
```

- **host `~/.mcp-smartbuilding/`** → 容器 `/data/`（只读；MCP 端负责往里写 clip）。
- **host `~/.cache/.multilevel-video-understanding/`** → 容器 `~/.cache/.multilevel-video-understanding/`
  （读写；prompt registry 持久化，注册的 dynamic task 存这里，容器重启不丢）。

**规则**：任何要给 VLM 处理的视频，必须先 cp 到 `${SMARTBUILDING_DATA_DIR}`
下面，用容器内路径 `/data/...` 传给 VLM API。

```bash
# 建约定子目录（每个 use case 一个）
mkdir -p ~/.mcp-smartbuilding/test-videos/${UC}
cp /path/to/generated-video.mp4 \
   ~/.mcp-smartbuilding/test-videos/${UC}/

# 调 VLM 时用容器内路径
CONTAINER_PATH=/data/test-videos/${UC}/generated-video.mp4
```

> **注**：真实的 motion clip 由 videostream-analytics 写到
> `~/.mcp-smartbuilding/segments/<monitor_id>/motion_events/<date>/*.mp4`，
> MCP 侧 `path_remap` 会把这些 host 路径改写成 `/data/segments/...` 传给
> VLM——你不用手动 cp。§4 的 cp 主要用于**离线打样**（生成的测试视频直接
> 喂 VLM 看输出，跳过 VSA 链路）。

---

## 5. 打样 VLM 对视频的输出

VLM 服务的核心接口 `POST /v1/summary`：

```bash
curl -sS http://localhost:8192/v1/summary \
  -H "Content-Type: application/json" \
  -d "{
    \"task\": \"${TASK}\",
    \"video\": \"${CONTAINER_PATH}\",
    \"method\": \"SIMPLE\",
    \"processor_kwargs\": {\"levels\": 1, \"level_sizes\": [-1], \"process_fps\": 1}
  }" | jq .
```

**参数说明**：

| 参数 | 说明 |
|---|---|
| `task` | 已注册的 task 名（内置或 §3 动态注册） |
| `video` | 容器内路径（`/data/...`）或 https URL |
| `method` | `SIMPLE`（单 pass，快）/ `USE_VLM_T-1` / `USE_LLM_T-1` / `USE_ALL_T-1`（跨 chunk 传递上下文，慢但连贯） |
| `processor_kwargs.levels` | 汇总层数；`1` = 只调 LOCAL_PROMPT 一次；`>1` = 用 MACRO / GLOBAL |
| `processor_kwargs.level_sizes` | 每层的 chunk 大小；`[-1]` = 整段视频一 chunk |
| `processor_kwargs.process_fps` | 每秒抽几帧送 VLM。**短视频（≤ 5s）建议 2-4**，避免采样太稀漏掉关键动作 |

**响应形态**：

```json
{
  "summary": "SEVERITY: critical\nEVENT: high_altitude_throw\nDESC: ...\nMOTION_DIRECTION: downward",
  "chunks": [ ... ],
  "usage": { "prompt_tokens": 234, "completion_tokens": 45, ... },
  "latency_seconds": 3.2
}
```

**验证要点**（对新 use case 都适用）：

1. **`summary` 字段存在且非空** —— 服务运行正常
2. **格式符合 LOCAL_PROMPT 声明的字段** —— 每行 `KEY: value`，keys 与
   `schema.video_summary_tasks.extensions` 里 `required: true` 的名字对齐
   （大小写不敏感，parseSummaryFields 会规范化）
3. **VLM 语义判断合理** —— 严重度、事件类型、描述与视频内容相符

---

## 6. 与 smart-community 全链路对接

VLM 打样通过后，走 smart-community 的完整链路：

```
RTSP → VSA :8999 → clip → webhook :3101/events
                                    │
                                    ▼
                  video_summary_tasks (pending)
                                    │
                                    │ task-poller 每 5s 拉一次
                                    ▼
              POST http://localhost:8192/v1/summary
                                    │
                                    ▼
                     summary_text 写回 DB + parseSummaryFields
                                    │
                                    ▼
                  RuleContext → evaluate_rules.py
                                    │
                                    ▼
                     alerts 表 + MCP resource 通知
```

在 smart-community 端一次 startup 需要保证：

1. **VLM 服务 healthy** —— 见 §2.2
2. **task 已在 VLM 注册**（内置 or dynamic）—— 见 §3
3. **`config.yaml.example` 的 `summary_service.url` 指向 `:8192`**（默认已如此）
4. **`use_case_dict.<uc>.video_summary_task` 与 VLM 注册的 task_name 一致**
5. **`schema.video_summary_tasks.extensions` 里的 required 字段名在 LOCAL_PROMPT 里出现**

第 5 项由 `smartbuilding_use_case_validate` tool 自动校验：

```bash
# 起 MCP server 之后
curl -s -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
    "name":"smartbuilding_use_case_validate",
    "arguments":{"use_case":"'"${UC}"'"}}}' \
  | grep "^data:" | head -1 | sed 's/^data: //' | jq .
```

期望：`checks.use_case_known: true`、`checks.task_registered: true`、`checks.schema_consistent: true`。

**任一项 false 时的定位**：

| check false | 说明 | 修复 |
|---|---|---|
| `use_case_known` | `config.yaml.example` 里没有该 use case | 编辑 `use_case_dict` 加条目 |
| `task_registered` | VLM `/v1/tasks` 里找不到 task_name | 回到 §3 重新注册 |
| `schema_consistent` | LOCAL_PROMPT 里没提到 schema 里 required 的字段名 | 修改 `use-cases/<uc>/prompt.md` 或调整 schema extension |

---

## 7. 完整流程示例：新增 `<my_new_uc>` use case

假定你已经：
- 用即梦 AI 生成好视频
- 按 [use-case-adapter.md](./use-case-adapter.md) 建好 `use-cases/<my_new_uc>/evaluate_rules.py` + `prompt.md`
- 在 `config.yaml.example` 加了 `use_case_dict.<my_new_uc>` 条目

VLM 集成 5 步：

```bash
UC=my_new_uc
TASK=my_new_uc_monitor       # 匹配 use_case_dict.<uc>.video_summary_task
VIDEO_LOCAL=/path/to/my-test-video.mp4

# --- Step 1: VLM 服务已 healthy（若未起，跳到 §2.1）---
curl -sf http://localhost:8192/v1/health && echo "VLM ok"

# --- Step 2: 注册 task（复用 §3.1 通用脚本）---
# ... 用 §3.1 的 python 抽 prompt.md 段 → POST /v1/tasks ...

# --- Step 3: 视频移到 VLM 可访问的目录 ---
DEST=~/.mcp-smartbuilding/test-videos/${UC}
mkdir -p $DEST && cp $VIDEO_LOCAL $DEST/
CONTAINER_PATH=/data/test-videos/${UC}/$(basename $VIDEO_LOCAL)

# --- Step 4: 打样 VLM 输出 ---
curl -sS http://localhost:8192/v1/summary \
  -H "Content-Type: application/json" \
  -d "{\"task\":\"${TASK}\",\"video\":\"${CONTAINER_PATH}\",\"method\":\"SIMPLE\",
       \"processor_kwargs\":{\"levels\":1,\"level_sizes\":[-1],\"process_fps\":2}}" \
  | jq -r '.summary // .result.summary // empty' | tee /tmp/vlm-out-${UC}.txt

# 检查是否含 required 字段（以 SEVERITY / EVENT / DESC 为例；不同 use case 字段不同）
for f in SEVERITY EVENT DESC; do
    grep -qi "^${f}:" /tmp/vlm-out-${UC}.txt && echo "  ✓ $f" || echo "  ✗ $f missing"
done

# --- Step 5: 端到端 rule_eval（跳过 VSA，直接把 VLM 输出塞 DB 走 adapter 层）---
# 详见 use-case-adapter-gsg.md §6.
```

---

## 8. Debug 常见问题

### 8.1 vLLM 起不来 / OOM

**症状**：`docker compose logs vllm-ipex-serving | grep -i error` 里看到
`out of memory` / `SIGKILL` / `killed`。

**原因**：FP8 编译期高峰内存 30 GB+，物理内存不够（35B 尤其吃）。

**解决**：

```bash
# 加 32 GB swap（按你的环境选择 helper 或系统方式）
# 示例：sudo bash ../agent-ai.smarthome/scripts/helpers/setup-swap-32g.sh

# 或切到更小模型：set_env.sh 改 LLM_MODEL=QuantTrio/Qwen3.5-9B-AWQ
```

### 8.1.5 vllm 日志长时间不动（不是死锁）

**症状**：`docker compose logs vllm-ipex-serving` 最后一条日志停在
`Using Flash Attention backend` / `Starting to load model ...` 之类，几十
分钟无更新，但容器 status 仍是 `Up (health: starting)`。

**判定**：首次跑 35B 时，`HF_HUB_OFFLINE=0` + `HF_ENDPOINT=hf-mirror.com`
会从头拉 ~70 GB weights。HF downloader 进度条**不写到 stdout**，日志看
起来"死了"实际下载线程还在跑。

```bash
# 看下载进度
du -sh ~/models/huggingface/hub/models--Qwen--Qwen3.5-*/
ls ~/models/huggingface/hub/models--Qwen--Qwen3.5-*/blobs/*.incomplete 2>/dev/null | wc -l
docker stats --no-stream vllm-ipex-serving   # NET I/O 持续增长 = 下载中

# 阻塞式等待 ready
until curl -sf http://localhost:41091/v1/models | grep -q Qwen; do sleep 30; done && \
  echo "vLLM READY"
```

只要 `du -sh` 数字还在长 / `.incomplete` 文件还在，就是**还没下完，不是卡死**。
下载完 → vllm 自动进入 `Loading safetensors checkpoint shards`（这时 log 就
会刷进度条）→ 3-5 min 后 `Uvicorn running on 0.0.0.0:8000` → healthy →
multilevel-video-understanding 才 start。

### 8.2 `/v1/tasks` 返回空（curl 失败）或 task 名不在列表里

**症状 A**：`curl -sf http://localhost:8192/v1/tasks` exit code 7（connection refused）
或空响应。

**判定**：multilevel 还没 up。看 `docker ps`：如果 `multilevel-video-understanding-*`
status 是 `Created` 或不存在——它在等 vllm healthy 后才 start。看 §2.1 观察 vllm。

**症状 B**：`/v1/tasks` 有响应，但你要的 task_name（如 `child_safety_monitor`）
不在列表。

**判定**：这个 task 不是内置。内置只有 6 个：`summary` / `engine_valves_sop` /
`refrigerator_monitor` / `refrigerator_monitor_en` / `daily_report` / `daily_report_en`。
其他必须动态注册——回 §3。

**校验**：

```bash
curl -sS http://localhost:8192/v1/tasks | jq '.tasks[] | {name, source}'
# builtin  → source: "builtin"
# 动态注册 → source: "dynamic"
```

### 8.3 VLM 响应但 summary 里没有 required 字段

**症状**：`/v1/summary` 返回 200，`summary` 字段有内容，但缺 `SEVERITY:` /
`EVENT:` 之类关键字段。

**排查顺序**：

1. 确认注册的 task 里 LOCAL_PROMPT 真的写了字段名：
   ```bash
   curl -sS http://localhost:8192/v1/tasks/${TASK} | jq -r '.content' | head -40
   # 期望看到 LOCAL_PROMPT = '''...SEVERITY: ...''' 之类
   ```
2. 若 prompt 正确，小模型（0.8B / 9B-AWQ）理解不了枚举 → 换 35B
3. 若切换模型仍失败，简化 prompt：把 `SEVERITY: critical | warn | info` 明确
   写在最后一行，加"必须严格按上述格式返回"约束

### 8.4 短视频 VLM 判为 no_incident

**症状**：videos ≤ 5s，即梦生成的动作一闪而过；VLM 输出 `EVENT: no_incident`
（或 `uncertain`）。

**原因**：`process_fps: 1` 每秒 1 帧，4 秒视频只抽 4 帧，可能全错过关键瞬间。

**解决**：

```bash
# 提高抽帧频率
"processor_kwargs": {"levels": 1, "level_sizes": [-1], "process_fps": 4}

# 或用 ffmpeg 慢放视频到 10s
ffmpeg -i short.mp4 -filter:v "setpts=2.5*PTS" -an long.mp4
```

### 8.5 VLM 容器读不到视频（400 / file not found）

**症状**：`/v1/summary` 返回 400 `Local file not found: /data/segments/...`。
MCP task-poller log 会看到 `[task-poller] task X failed: video-summary HTTP 400`。

**排查**：

```bash
# 1) 确认容器内路径存在
CONTAINER=multilevel-video-understanding-multilevel-video-understanding-1
docker exec $CONTAINER ls /data/segments/cam_child/motion_events/$(date +%Y-%m-%d)/ 2>&1

# 2) 确认容器 mount 的 host 路径
docker inspect $CONTAINER | jq '.[0].Mounts[] | select(.Destination=="/data")'

# 3) 对比 MCP 端 SMARTBUILDING_DATA_DIR 与容器 mount source
echo "MCP DATA DIR: ${SMARTBUILDING_DATA_DIR:-~/.mcp-smartbuilding}"

# 4) 对比 config.yaml.example 里 path_remap
grep -A2 "path_remap" config.yaml.example
```

**§1 那条 invariant 触发了**：三者（MCP `SMARTBUILDING_DATA_DIR` /
`docker/.../set_env.sh` 里同名变量 / `config.yaml.example` 的
`path_remap.host_prefix`）**必须**指向同一个宿主机目录。

**修复流程**：

```bash
# 确认新 stack 起来了、且 mount 指向 ~/.mcp-smartbuilding
cd docker/multilevel-video-understanding
source ./set_env.sh
docker compose down && docker compose up -d
```

若之前跑的是老 stack（mount 到 `~/.openclaw/smarthome-demo/data`），先 down
掉它再起新的（见 §2 顶部）。

### 8.6 VLM 输出格式漂移（大小写 / 空格 / 中英文冒号）

**症状**：VLM 输出 `Severity: Critical`（首字母大写）或 `SEVERITY：critical`（全角冒号），
smart-community 侧 `parseSummaryFields` 抓不到值。

**处理**：`parseSummaryFields` 已经**大小写不敏感**，但**全角冒号** `：` 不识别。
在 LOCAL_PROMPT 末尾追加：

```
输出严格用半角冒号 ":" 与英文字段名（如 SEVERITY: critical）。
```

### 8.7 想验证 task prompt 效果但每次都调整需要重启

**方法**：`PATCH /v1/tasks/<name>` 更新 prompt，**不需要重启容器**：

```bash
# 用 §3.3 的 PATCH 请求，热更 task 定义
curl -sS -X PATCH http://localhost:8192/v1/tasks/${TASK} \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/register-${UC}.json | jq .

# 立刻用同一 task 重新调 /v1/summary 验证
```

### 8.8 动态注册的 task 容器重启后是否丢？

不会。§4 提到的 `VIDEO_SUMMARY_CACHE_HOST` 挂载让 registry 持久化在
`~/.cache/.multilevel-video-understanding/tasks/`。只有下面情况会丢：

- 手动 `rm -rf ~/.cache/.multilevel-video-understanding/tasks/*`
- 换宿主机（`VIDEO_SUMMARY_CACHE_HOST` 指到别的路径）
- 直接改 `set_env.sh` 里的 `VIDEO_SUMMARY_CACHE_HOST` 后 `docker compose up -d`

---

## 9. 相关文档

- **VLM 服务源码 / compose（当前使用）**：`docker/multilevel-video-understanding/` +
  `edge-ai-libraries/microservices/multilevel-video-understanding/`（submodule）
- **旧 stack（已弃用）**：sibling 仓库中的 `../agent-ai.smarthome/start-video-summary-service/end2end/`——如果之前跑过，
  用 §2 顶部命令 `docker compose down` 停掉，避免端口冲突。
- **内置 task 定义（source of truth）**：`edge-ai-libraries/microservices/multilevel-video-understanding/video_analyzer/schemas/summarization.py`
  的 `TASKNAME` enum
- **task 注册 API 契约**：`edge-ai-libraries/microservices/multilevel-video-understanding/video_analyzer/api/endpoints/tasks.py`
  + `schemas/task_registration.py`
- **本 repo 的 use case adapter 侧**：[use-case-adapter.md](./use-case-adapter.md) + [use-case-adapter-gsg.md](./use-case-adapter-gsg.md)
- **场景全景**：[use-case-catalog.md](./use-case-catalog.md)（85 case）
- **API 契约**：[apis/videostream_analytics_api.md](./apis/videostream_analytics_api.md) 是 VSA 侧
