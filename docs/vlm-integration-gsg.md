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

VLM 由两个 Docker 容器组成，用 docker compose 编排在 `agent-ai.smarthome/start-video-summary-service/end2end/`：

```
┌──────────────────────────────────────────────────────────┐
│  vllm-ipex-serving   (Intel XPU + FP8 vLLM)              │
│  外部端口 :41091 → 容器内 :8000                            │
│  跑 Qwen/Qwen3.5-* 模型（默认 0.8B 小模型；可切 9B / 35B）  │
│  首次启动做 FP8 编译，3-20 分钟                            │
└──────────────▲───────────────────────────────────────────┘
               │  HTTP /v1/chat/completions（app-network 内）
               │
┌──────────────┴───────────────────────────────────────────┐
│  multilevel-video-understanding                           │
│  外部端口 :8192 → 容器内 :8000                             │
│  视频 clip → ffmpeg 抽帧 → 组合 chat/completions →         │
│    按 task prompt 输出 summary_text                       │
│  内置 task：refrigerator_monitor / child_safety_monitor    │
│              / elder_wakeup_monitor                        │
│  运行时可通过 POST /v1/tasks 动态注册新 task                │
└──────────────────────────────────────────────────────────┘
```

**硬性依赖**：

| 依赖 | 说明 |
|---|---|
| Intel XPU / iGPU | `/dev/dri/renderD128` 必须存在 |
| Docker + compose v2 | 用 `docker compose`（不是 `docker-compose`）|
| `HF_HOME` 目录 | 默认 `~/models/huggingface`；首次会拉模型（几 GB - 几十 GB） |
| `edge-ai-libraries` submodule | compose 里 build context 引用它，需保证 checkout 完成 |
| 可选：swap 32 GB | 大模型 (35B) 编译期内存高峰会 OOM，`agent-ai.smarthome/scripts/helpers/setup-swap-32g.sh` |

**smart-community 侧对应配置**（`config.yaml.example`）：

```yaml
summary_service:
  url: http://localhost:8192          # multilevel-video-understanding
vlm_service:
  url: http://localhost:41091/v1      # vllm-ipex-serving 直连（scene_query 用）
  model: default
  max_edge_px: 720
```

`summary_service.url` 是 task-poller 消费的服务端点；`vlm_service.url` 是
`smartbuilding_scene_query` 单帧问答的直连端点（本文档主要关注前者）。

---

## 2. 启动 VLM 服务

### 2.1 首次启动

```bash
cd /home/user/jie/smarthome/agent-ai.smarthome/start-video-summary-service/end2end

# 1) 建模型缓存目录
mkdir -p ~/models/huggingface

# 2) 加载环境（暴露 XPU 组 / 模型名 / 端口 / SMARTHOME_DATA_DIR 等）
source set_env.sh

# 3) 起容器（首次 3-20 分钟，因为要 FP8 编译）
docker compose up -d

# 4) 观察启动进度
docker compose logs -f vllm-ipex-serving
# 等看到 "Uvicorn running on http://0.0.0.0:8000" 表示 vLLM 起来了；
# multilevel-video-understanding 会等 vLLM healthy 后再启动
```

### 2.2 探活

```bash
# vLLM 层（模型是否加载好）
curl -sf http://localhost:41091/v1/models | jq .
# 期望：{"data": [{"id": "Qwen/Qwen3.5-0.8B", ...}], ...}

# multilevel-video-understanding 层
curl -sf http://localhost:8192/v1/health
# 期望：{"status": "ok"} 或类似
```

### 2.3 停 / 重启

```bash
cd /home/user/jie/smarthome/agent-ai.smarthome/start-video-summary-service/end2end
docker compose down                            # 停两个
docker compose restart multilevel-video-understanding   # 仅重启 video 服务
docker compose logs -f --tail=100 multilevel-video-understanding
```

**注意**：`vllm-ipex-serving` 冷启动很贵（FP8 编译），除非切换模型，日常调
prompt / task 只重启 `multilevel-video-understanding`。

### 2.4 切换模型

修改 `end2end/set_env.sh`：

```bash
# 快速迭代（对硬件要求低，回答质量一般）
export LLM_MODEL=Qwen/Qwen3.5-0.8B

# 中等（准确率更好）
export LLM_MODEL=Qwen/Qwen3.5-9B
export MAX_MODEL_LEN=49152

# 高质量（35B FP8，需要 64+ GB 内存）
export LLM_MODEL=Qwen/Qwen3.5-35B-A3B
export MAX_MODEL_LEN=61440
```

改完 `source set_env.sh && docker compose up -d` 触发重建。

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

注册方式两种：`autogen`（服务端 LLM 自动补齐 4 段）或 `full`（客户端提交完整 4 段）。**smart-community 的 prompt.md** 通常已经准备好前两段（LOCAL / GLOBAL），推荐 `full` 模式。

### 3.1 通用注册脚本

以 use case `<uc_name>` + prompt 文件 `use-cases/<uc_name>/prompt.md` 为例：

```bash
UC=high_altitude_safety                    # 与 config.yaml use_case_dict.<uc> 对应
TASK=high_altitude_monitor                 # 与 use_case_dict.<uc>.video_summary_task 对应
PROMPT_MD=/home/user/jie/smarthome/smart-community/use-cases/${UC}/prompt.md

# 从 prompt.md 抽 LOCAL_PROMPT 与 GLOBAL_PROMPT 段（按 `## <NAME>` 分段）
python3 - <<PY > /tmp/register-${UC}.json
import re, json, pathlib

md = pathlib.Path("$PROMPT_MD").read_text(encoding="utf-8")
sections = {}
current, buf = None, []
for line in md.splitlines():
    m = re.match(r"^##\s+([A-Z_]+)\s*\$", line)
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

### 3.2 更新 / 删除 task

```bash
# 只改 description
curl -sS -X PATCH http://localhost:8192/v1/tasks/${TASK} \
  -H 'Content-Type: application/json' \
  -d '{"description":"v2 refined"}' | jq .

# 完全重写 4 段（同注册体形态）
curl -sS -X PATCH http://localhost:8192/v1/tasks/${TASK} \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/register-${UC}.json | jq .

# 删除动态注册的 task（内置 task 会 403）
curl -sS -X DELETE http://localhost:8192/v1/tasks/${TASK} -w "%{http_code}\n"
```

---

## 4. 视频文件挂载

VLM 容器内**读不到 host 任意路径的视频**——它只能访问挂进来的 volume。看 `compose.yaml`：

```yaml
volumes:
  - ${SMARTHOME_DATA_DIR:-${HOME}/.openclaw/smarthome-demo/data}:/data:rw
```

**host `~/.openclaw/smarthome-demo/data/`** 映射到**容器内 `/data/`**。

**规则**：任何要给 VLM 处理的视频，必须先 cp 到 `${SMARTHOME_DATA_DIR}` 下面，
用容器内路径 `/data/...` 传给 VLM API。

```bash
# 建约定子目录（每个 use case 一个）
mkdir -p ~/.openclaw/smarthome-demo/data/test-videos/${UC}
cp /path/to/generated-video.mp4 \
   ~/.openclaw/smarthome-demo/data/test-videos/${UC}/

# 调 VLM 时用容器内路径
CONTAINER_PATH=/data/test-videos/${UC}/generated-video.mp4
```

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
| `method` | `SIMPLE`（单 pass，快）/ `USE_ALL_T-1`（chunk 之间用上一段结果，慢但连贯） |
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
2. **task 已在 VLM 注册** —— 见 §3
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
VIDEO_LOCAL=/home/user/jie/smarthome/my-test-video.mp4

# --- Step 1: VLM 服务已 healthy（若未起，跳到 §2.1）---
curl -sf http://localhost:8192/v1/health && echo "VLM ok"

# --- Step 2: 注册 task（复用 §3.1 通用脚本）---
# ... 用 §3.1 的 python 抽 prompt.md 段 → POST /v1/tasks ...

# --- Step 3: 视频移到 VLM 可访问的目录 ---
DEST=~/.openclaw/smarthome-demo/data/test-videos/${UC}
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

**原因**：FP8 编译期高峰内存 30 GB+，物理内存不够。

**解决**：

```bash
# 加 32 GB swap
sudo bash /home/user/jie/smarthome/agent-ai.smarthome/scripts/helpers/setup-swap-32g.sh

# 或切换到更小模型（set_env.sh 改 LLM_MODEL=Qwen/Qwen3.5-0.8B, GPU_MEM_UTIL=0.5）
```

### 8.2 VLM 响应但 summary 里没有 required 字段

**症状**：`/v1/summary` 返回 200，`summary` 字段有内容，但缺 `SEVERITY:` /
`EVENT:` 之类关键字段。

**排查顺序**：

1. 确认注册的 task 里 LOCAL_PROMPT 真的写了字段名：
   ```bash
   curl -sS http://localhost:8192/v1/tasks/${TASK} | jq -r '.content.local' | head -20
   ```
2. 若 prompt 正确，小模型（0.8B）理解不了枚举 → 换 9B / 35B
3. 若切换模型仍失败，简化 prompt：把 `SEVERITY: critical | warn | info` 明确
   写在最后一行，加"必须严格按上述格式返回"约束

### 8.3 短视频 VLM 判为 no_incident

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

### 8.4 VLM 容器读不到视频（404 / file not found）

**症状**：`/v1/summary` 返回错误，日志显示 `no such file or directory`。

**排查**：

```bash
# 确认容器内路径存在
docker exec -it end2end-multilevel-video-understanding-1 ls /data/
# 应能看到你的 test-videos/ 子目录
```

如果没看到，检查 host 侧的 `SMARTHOME_DATA_DIR` 与 `set_env.sh` 里的值是否一致；
或者用 `docker inspect` 确认 volume 挂载正确：

```bash
docker inspect end2end-multilevel-video-understanding-1 | jq '.[0].Mounts'
```

必要时重启容器让 mount 生效：`bash restart_with_correct_mount.sh`。

### 8.5 VLM 输出格式漂移（大小写 / 空格 / 中英文冒号）

**症状**：VLM 输出 `Severity: Critical`（首字母大写）或 `SEVERITY：critical`（全角冒号），
smart-community 侧 `parseSummaryFields` 抓不到值。

**处理**：`parseSummaryFields` 已经**大小写不敏感**，但**全角冒号** `：` 不识别。
在 LOCAL_PROMPT 末尾追加：

```
输出严格用半角冒号 ":" 与英文字段名（如 SEVERITY: critical）。
```

### 8.6 想验证 task prompt 效果但每次都调整需要重启

**方法**：`PATCH /v1/tasks/<name>` 更新 prompt，**不需要重启容器**：

```bash
# 用 §3.2 的 PATCH 请求，热更 task 定义
curl -sS -X PATCH http://localhost:8192/v1/tasks/${TASK} \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/register-${UC}.json | jq .

# 立刻用同一 task 重新调 /v1/summary 验证
```

---

## 9. 相关文档

- **VLM 服务源码 / compose**：`agent-ai.smarthome/start-video-summary-service/end2end/`
- **VLM 内置 task prompt**：`agent-ai.smarthome/openclaw-smarthome-demo/prompts/tasks/`
- **本 repo 的 use case adapter 侧**：[use-case-adapter.md](./use-case-adapter.md) + [use-case-adapter-gsg.md](./use-case-adapter-gsg.md)
- **场景全景**：[use-case-catalog.md](./use-case-catalog.md)（85 case）
- **API 契约**：[apis/videostream_analytics_api.md](./apis/videostream_analytics_api.md) 是 VSA 侧；VLM 服务侧的 API 见 `agent-ai.smarthome/start-video-summary-service/example_curl.txt`
