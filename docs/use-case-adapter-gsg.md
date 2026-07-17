# Use Case Adapter — Get Started Guide (Test Recipe)

本文档面向 use case adapter 的功能验证，给出一套完整可执行的测试步骤。use case adapter 包含三个可测层，本文按层逐个覆盖：

- **Prompt 层**：VLM 拿到 clip 后按 `LOCAL_PROMPT` 的规定输出结构化字段（`SEVERITY: / EVENT: / DESC: / …`）
- **Rules 层**：`evaluate_rules.py`（可选 Python override）**或** rule-free `defaultRuleEvaluator` 通过 `payload.fields` 完成判定；产出 `{should_alert, alert_message}`；通过 MCP `smartbuilding_rule_eval` 查看时，对应字段为 `rule_result.shouldAlert` / `rule_result.alertMessage`

上游产品文档：[use-cases/README.md](../use-cases/README.md)、[docs/use-case-adapter.md](./use-case-adapter.md)、[docs/implements/schema-usecase-parser-alerts-pipeline.md](./implements/schema-usecase-parser-alerts-pipeline.md)。

---

## 完整测试流程速览

以下 5 个 Phase 覆盖 use case adapter 全部能力，按顺序跑：

| Phase | 目标 | 需要什么 | 参考章节 |
|---|---|---|---|
| **Phase 0** | 清场（可选，重新起环境时用）| 无 | §3 上面的清理命令 |
| **Phase 1** | 起底层服务（VLM / VSA / MCP / mediamtx）| Docker + NPU（可选）| §3 |
| **Phase 2** | 基线 U1–U8（3 内置 UC：fridge / child_safety / elder_wakeup）| 现有 4 条 loop 视频（已在 demo-videos/）| §5 |
| **Phase 3** | 零重启动态注册新 use case（`pet_safety` 主例 + `high_altitude` / `parking` 扩展）+ 持久化 | VLM 服务 + `--config` 启动 MCP + 现有 pet_safety.mp4 / building-throwing-2.mp4 / false-parking.mp4 | §9 |

**每个 use case 从"零"到"跑通"的核心 5 步**（§9 详解）：

1. 用 `video-summary-prompt-studio` skill（agent + router）起草 `## LOCAL_PROMPT` 骨架
2. 人工 review + refine 骨架，存到 `use-cases/<uc>/prompt.md`
3. `smartbuilding_use_case_register action=register persist=true` —— 一次搞定 schema ALTER + VLM POST /v1/tasks + inject useCaseDict + 写回 config.yaml（prompt 经 `prompt_text` 传入）
4. `smartbuilding_monitor_ctl action=register_source` —— 绑一个 RTSP monitor
5. VSA motion → task-poller → VLM → rule engine → alert，观察 `alerts` 表

**"零代码"承诺兑现进度**（对照 [gap-analysis §6](./dev/use-case-adapter-gap-analysis.md#6-验证结论adapter-框架是否达到-design-13-零代码用例创建)）：

| 维度 | 状态 |
|---|---|
| 零 TypeScript 代码 | ✅ |
| 零 curl 手工 | ✅（一次 MCP tool call）|
| 零 YAML 手工 | ✅（`persist: true` 自动写回 config.yaml.example）|
| 零 prompt 手工 | ✅ 骨架由 `video-summary-prompt-studio` skill（agent + router）生成 + ⚠️ 用户仍需人工 refine 业务细节（human-in-the-loop 设计）|
| 零 Python 手工 | ✅ 简单 UC 完全靠 `rules` dict（`child_safety` / `high_altitude_safety` / `parking_safety` 均无 override）；`fridge` 为无规则 report-only；仅 `elder_wakeup`（时间比较）保留 override |

---

## 0. 当前可跑的验证矩阵（基线）

本文档目前的**基线覆盖场景**——只包含 [demo-videos/](../demo-videos/) 里**已经有真实视频**、并且 [monitors.yaml.example](../monitors.yaml.example) 已配好 monitor 的 3 个内置 use case：

| 场景 | monitor | use case | 类型 | 使用视频 |
|---|---|---|---|---|
| Fridge | `cam_fridge` | `fridge` | report-only | `cam_fridge/demo006-2_expanded_20min_v2.mp4` |
| Child Safety | `cam_child` | `child_safety` | 内置 `rules`（无 override）| `cam_child/child_safety_demo_expanded_1h.mp4` |
| Elder Wakeup Day 1 | `cam_elder_bedroom` | `elder_wakeup` | 内置 override | `cam_elder_bedroom/day1_elder_wakeup_expanded_20min.mp4` |
| Elder Wakeup Day 2 | `cam_elder_bedroom_2` | `elder_wakeup` | 内置 override | `cam_elder_bedroom_2/day2_elder_wakeup_expanded_20min.mp4` |

扩展场景（自定义 use case `pet_safety` / `high_altitude_safety` / `parking_safety`）放在 §9
"零重启动态注册新 use case"，用 `smartbuilding_use_case_register` 一键注册 + 仓库已有的真实素材验证——
是一次完整的 "adapter 是否自足" 演练，不属于本次基线。

---

## 1. 前提条件

| 依赖 | 说明 |
|---|---|
| Node.js ≥ 18 | 运行 MCP server (`packages/mcp-server`) |
| Python ≥ 3.10 | 运行 `evaluate_rules.py` override |
| ffmpeg | 视频推流 + 帧解码 |
| MediaMTX | 本地 RTSP server |
| Videostream Analytics 服务 | 见 [vsa-gsg.md](./vsa-gsg.md) 启动 |
| VLM 服务（`multilevel-video-understanding`）| 处理 clip 并返回 `summary_text`——见 [vlm-integration-gsg.md](./vlm-integration-gsg.md) |
| 测试视频 | 见 §3；基线只需 [demo-videos/](../demo-videos/) 已有的 4 个 |

**运行时环境变量**：

```bash
export SMARTBUILDING_DATA_DIR="${HOME}/.mcp-smartbuilding"   # 可省略；默认就是该目录
```

说明：

- `SMARTBUILDING_DATA_DIR` 是 MCP server 的统一运行目录；不设置时默认就是 `${HOME}/.mcp-smartbuilding`
- 若 `multilevel-video-understanding` 跑在容器里并通过 `/data` 访问 clip，则容器挂载路径、`config.yaml.example` 里的 `summary_service.path_remap.host_prefix`，以及这里导出的 `SMARTBUILDING_DATA_DIR` 必须指向同一个宿主机目录。常见挂载方式是 `${SMARTBUILDING_DATA_DIR:-${HOME}/.mcp-smartbuilding}:/data:ro`
- **VLM 端 dynamic task 必须先注册**：`child_safety_monitor` / `elder_wakeup_monitor` 属于 dynamic task（不在 VLM builtin 列表内），MCP 启动前需先按 [vlm-integration-gsg.md §3.2](./vlm-integration-gsg.md) 的一键脚本 POST `/v1/tasks` 注册。未注册时 `/v1/summary` 会失败（常见为 400，例如 unknown task）；但 400 并不唯一指向 task 未注册，路径映射错误等也会触发 400（详见 §8.2）。

---

## 2. 基线用例矩阵

3 个内置 use case（fridge / child_safety / elder_wakeup），每个 use case 用**现有单条 demo 视频**能触发的 case 编号列表。

### 2.1 `child_safety`（defaultRuleEvaluator）

用 [demo-videos/cam_child/child_safety_demo_expanded_1h.mp4](../demo-videos/cam_child/child_safety_demo_expanded_1h.mp4)（1 小时 loop）。视频包含多段儿童行为，VSA 会按 motion + 10s segment 切成多个 clip；期望其中 **critical（如攀爬 / 摔倒）clip → 触发 alert**，**info clip → 不触发**（rule 层 severity 短路）。

| ID | 视频行为片段 | Rule 期望 | 覆盖点 |
|----|-------------|----------|--------|
| **CS-baseline** | 视频 loop 中出现的 critical 片段 | ✅ 触发 `[child_safety] <event>: critical — ...` | severity ≥ warn fire |
| **CS-suppressed** | 视频 loop 中出现的 info 片段（安静玩耍） | ❌ 不触发 | severity 阈值短路 |

groundtruth 见 [cam_child/child_safety_demo_expanded_1h_groundtruth.srt](../demo-videos/cam_child/child_safety_demo_expanded_1h_groundtruth.srt)。

### 2.2 `elder_wakeup`（script default: `07:00` + `30` minutes）

用 [demo-videos/cam_elder_bedroom/day1_elder_wakeup_expanded_20min.mp4](../demo-videos/cam_elder_bedroom/day1_elder_wakeup_expanded_20min.mp4)
（20 分钟 loop，起床动作）+ [cam_elder_bedroom_2/day2_elder_wakeup_expanded_20min.mp4](../demo-videos/cam_elder_bedroom_2/day2_elder_wakeup_expanded_20min.mp4)（同一 use case，不同 monitor）。

| ID | 视频行为片段 | Rule 期望 | 覆盖点 |
|----|-------------|-----------|--------|
| **EW-late** | `get_up` clip，实测时间已过 `expectedWakeupLocal + graceMinutes` | ✅ 触发 `late_wakeup` | 时间比较 + graceMinutes |
| **EW-ontime** | 同上 clip，实测时间在 grace 内 | ❌ 不触发 | grace period 边界 |
| **EW-still** | `still_in_bed` clip | ❌ 不触发 | event 名匹配 |
| **EW-day2** | 另一 monitor 的同 use case | ✅ 独立触发 | 多 monitor 共享 use case |

groundtruth：[day1_elder_wakeup_groundtruth.srt](../demo-videos/cam_elder_bedroom/day1_elder_wakeup_groundtruth.srt) / [day2_elder_wakeup_groundtruth.srt](../demo-videos/cam_elder_bedroom_2/day2_elder_wakeup_groundtruth.srt)。

**关于时间比较**：`elder_wakeup/evaluate_rules.py` 用 `datetime.now()` 读实时，默认使用脚本内 `07:00` + `30` 分钟。自动化测试通过环境变量 `ELDER_WAKEUP_EXPECTED_WAKEUP_LOCAL` / `ELDER_WAKEUP_GRACE_MINUTES` 制造 EW-late / EW-ontime 边界，不再通过 YAML rules 调参。

### 2.3 `fridge`（report-only）

用 [demo-videos/cam_fridge/demo006-2_expanded_20min_v2.mp4](../demo-videos/cam_fridge/demo006-2_expanded_20min_v2.mp4)（20 分钟 loop，取用/放置行为）。

`fridge` **已不再有 `evaluate_rules.py` stub，也没有 `rules` 块**（见 [config.yaml.example](../config.yaml.example) `use_case_dict.fridge`），因此走内置 `defaultRuleEvaluator`。它的 VLM task `fridge_monitor` 不产出 `SEVERITY` 行，`defaultRuleEvaluator` 在 severity 缺失时**短路返回 false** —— 这才是 fridge "只报告不告警" 的真实机制。

| ID | 视频行为片段 | Rule 期望 | 覆盖点 |
|----|-------------|-----------|--------|
| **FR-normal** | 开冰箱取物 / 放置 | ❌ 不触发（输出无 `SEVERITY` → severity 短路） | 无 severity 短路 |
| **FR-inject-critical** | 手工 UPDATE DB 塞入 `severity=critical` | ✅ **会触发** `[fridge] <event>: critical — ...` | **关键**：fridge 未声明 override，一旦有合格 severity 就走 default 触发。要硬性不告警需新增 `evaluate_rules.py`，但默认 demo 不提供该脚本。 |

groundtruth：[demo006-2_expanded_20min_v2_groundtruth.srt](../demo-videos/cam_fridge/demo006-2_expanded_20min_v2_groundtruth.srt)。

---

## 3. 启动测试环境

### 3.1 推 RTSP 流

一键把 4 个 demo 视频 loop 推到 mediamtx（脚本会自己起 mediamtx）：

```bash
cd smart-community/demo-videos
./start-streams.sh                 # 起 mediamtx + 推所有 enabled 的流
./start-streams.sh --status        # 看谁在跑
./start-streams.sh --stop          # 全停
```

推流列表 / 目标 URL / loop 与否见 [demo-videos/streams.yaml](../demo-videos/streams.yaml)。

**验证推流正常**（一定要跑，避免 §8.1 的 RTSP 404 报错）：

```bash
ffprobe -v error -rtsp_transport tcp -i rtsp://localhost:8554/live/fridge && echo OK
ffprobe -v error -rtsp_transport tcp -i rtsp://localhost:8554/live/child  && echo OK
ffprobe -v error -rtsp_transport tcp -i rtsp://localhost:8554/live/elder  && echo OK
ffprobe -v error -rtsp_transport tcp -i rtsp://localhost:8554/live/elder2 && echo OK
```

四条都返 OK 才能继续下一步。

### 3.2 启动支撑服务（3 个终端）

**T1 — Videostream Analytics 服务**

```bash
cd videostream-analytics && source .venv/bin/activate
WEBHOOK_URL=http://localhost:3101/events \
  .venv/bin/videostream-analytics serve --config config/config.yaml
```

启动日志：`Uvicorn running on http://0.0.0.0:8999`。

**T2 — VLM 服务（multilevel-video-understanding）**

按 [vlm-integration-gsg.md §2](./vlm-integration-gsg.md) 启动容器，然后**必须**跑一次 §3.2
的一键注册脚本把 3 个动态 task 注册进去：

```bash
# task 注册脚本（省略变量赋值，见 vlm-integration-gsg.md §3.2）
# 注册 3 个基线 dynamic task；扩展 UC（pet_safety / high_altitude_safety / parking_safety）
# 的 VLM task 由 §9 的 smartbuilding_use_case_register 自动 POST，无需在此预注册
for pair in \
  "fridge:fridge_monitor" \
    "child_safety:child_safety_monitor" \
    "elder_wakeup:elder_wakeup_monitor"; do
    ...
done

# 校验：应看到 builtin task + 3 baseline dynamic task
curl -sf http://localhost:8192/v1/tasks | jq '.tasks[].name'
```

`fridge` 用 dynamic task `fridge_monitor`，需要和 `child_safety_monitor` / `elder_wakeup_monitor` 一起注册。

**T3 — MCP server（含 use case adapter 装载）**

```bash
cd smart-community
export SMARTBUILDING_DATA_DIR="${HOME}/.mcp-smartbuilding"

# 直接复用仓库根目录的 monitors.yaml.example。基线用到的 4 个 monitor 已经在里面：
# - cam_child           -> rtsp://localhost:8554/live/child          (use_case=child_safety)
# - cam_elder_bedroom   -> rtsp://localhost:8554/live/elder          (use_case=elder_wakeup)
# - cam_elder_bedroom_2 -> rtsp://localhost:8554/live/elder2         (use_case=elder_wakeup)
# - cam_fridge          -> rtsp://localhost:8554/live/fridge         (use_case=fridge)

node packages/mcp-server/dist/index.js --http \
  --config config.yaml.example \
  --monitors monitors.yaml.example
```

启动日志包含：
- `[mcp-server] Streamable HTTP on http://localhost:3100/mcp`
- `[events-endpoint] Listening on port 3101`
- `[auto-register] cam_child ok`（对 videostream-analytics 完成注册；同样应看到 `cam_fridge` / `cam_elder_bedroom` / `cam_elder_bedroom_2`）

说明：

- 当前代码要求 monitor 定义放在独立的 `monitors.yaml` 文件里，通过 `--monitors <path>` 传入；`config.yaml.example` 里不能内嵌 `monitors:`
- 批量按文件管理 monitor 时，对应的 MCP tool 是 `smartbuilding_monitors_compose`；`smartbuilding_monitor_ctl` 只支持 `start | stop | register_source | unregister | status | list`

### 3.3 MCP 调用助手（重要：stateful HTTP 必须先握手）

当前 MCP server 走的是**有状态（stateful）HTTP 传输**（见 [index.ts:131](../packages/mcp-server/src/index.ts#L131)）：
每个客户端必须先发一次 `initialize` 握手拿到 `Mcp-Session-Id`，之后所有 `tools/call`
都要带上这个 header 复用会话。**直接单发 `tools/call`（不带 session）会被拒绝**，返回：

```json
{"jsonrpc":"2.0","error":{"code":-32000,"message":"Bad Request: Server not initialized"},"id":null}
```

—— 这正是"验证命令输出为空"的根因：响应里没有 `.result`，`jq '.result.content[0].text'`
自然什么都不吐。**本文所有 MCP 命令都必须先握手**。

把下面这段 helper 粘到当前 shell（只需一次），后续所有示例都用 `mcp_call` 调用：

```bash
export MCP_URL=${MCP_URL:-http://localhost:3100/mcp}
_MCP_ACCEPT="Accept: application/json, text/event-stream"

# 建立会话并把 session id 缓存到 $MCP_SID（幂等：已建立就复用）
mcp_init() {
  [ -n "$MCP_SID" ] && return 0
  local hdr; hdr=$(mktemp)
  curl -sS -D "$hdr" -o /dev/null -X POST "$MCP_URL" \
    -H "Content-Type: application/json" -H "$_MCP_ACCEPT" \
    -d '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"cli","version":"0"}}}'
  MCP_SID=$(grep -i '^mcp-session-id:' "$hdr" | awk '{print $2}' | tr -d '\r'); rm -f "$hdr"
  curl -sS -o /dev/null -X POST "$MCP_URL" \
    -H "Content-Type: application/json" -H "$_MCP_ACCEPT" -H "mcp-session-id: $MCP_SID" \
    -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'
  export MCP_SID
  echo "[mcp] session=$MCP_SID" >&2
}

# mcp_call <tool_name> <arguments-json> —— 打印 SSE 响应里的 data 行，交给 jq 解析
mcp_call() {
  mcp_init
  jq -n --arg n "$1" --argjson a "$2" \
    '{jsonrpc:"2.0",id:1,method:"tools/call",params:{name:$n,arguments:$a}}' \
  | curl -sS -X POST "$MCP_URL" \
      -H "Content-Type: application/json" -H "$_MCP_ACCEPT" -H "mcp-session-id: $MCP_SID" \
      --data-binary @- \
  | grep '^data:' | head -1 | sed 's/^data: //'
}
```

**先单独跑一次握手**（别放进管道里——管道左侧在子 shell 执行，导出的 `MCP_SID` 拿不回父 shell）：

```bash
mcp_init      # 打印 [mcp] session=<uuid>
```

之后统一这样调用。tool 的结构化结果在 `.result.content[0].text`，本身是一段 JSON 字符串，
需要再 `fromjson` 解一层：

```bash
mcp_call smartbuilding_use_case_validate '{"use_case":"child_safety"}' \
  | jq '.result.content[0].text | fromjson'
# 期望：{"valid": true, "checks": {"use_case_known": true, "task_registered": true, "schema_consistent": true}}
```

> 本文后面凡是"`curl -s -X POST .../mcp ... tools/call`"的示例，都等价于一句
> `mcp_call <name> '<arguments-json>'`。若你坚持保留原始 curl 写法，记得**每个**请求
> 都带上 `-H "mcp-session-id: $MCP_SID"`，并在最前面先跑过 `mcp_init`。
> 会话闲置超时会被回收（见 config `mcp.sessionIdleTimeoutMs`），报 `Server not initialized`
> 时重跑一次 `unset MCP_SID; mcp_init` 即可。

---

## 4. VLM 输出校验前置

use case adapter 的 rule 层依赖 VLM 输出格式；正式测规则前先确认 prompt 有效。

先做一个 **API 能力预检**（必须通过）：

```bash
# 预期至少包含 /v1/tasks、/v1/tasks/{name}、/v1/summary
curl -sS http://localhost:8192/v1/openapi.json \
  | jq -r '.paths | keys[]' \
  | grep -E '^/v1/tasks|^/v1/summary'
```

若这里看不到 `/v1/tasks`（或直接 404），说明你当前连到的是**旧版摘要服务**（仅支持 `/v1/summary`，会忽略 dynamic task prompt），
这时 `task=child_safety_monitor` 也只会返回通用自然语言描述，不可能产出 `SEVERITY/EVENT/DESC`。

修复：切到支持 task registry 的 multilevel-video-understanding 版本（见 [vlm-integration-gsg.md §2](./vlm-integration-gsg.md#2-启动-vlm-服务) 重启），
并重新执行 [vlm-integration-gsg.md §3.2](./vlm-integration-gsg.md#32-一键注册全部-4-个-use-case本-repo-常用脚本可直接跑)
把 `child_safety_monitor` 等 dynamic task 重新注册后，再继续本节打样。

```bash
# 直接对 VLM 服务打样，看它对现有 demo 视频的输出
export SMARTBUILDING_DATA_DIR="${SMARTBUILDING_DATA_DIR:-$HOME/.mcp-smartbuilding}"

# 1) 找一个真实 clip（VSA 触发 motion 后 20-40s 才会有）
HOST_CLIP=$(ls "$SMARTBUILDING_DATA_DIR/segments/cam_child/motion_events/"*/*.mp4 2>/dev/null | head -1)
[ -z "$HOST_CLIP" ] && { echo "no clip yet — VSA hasn't emitted any motion event"; exit 1; }

# 2) 转成容器内路径（host_prefix → /data）
CONTAINER_CLIP="/data${HOST_CLIP#$SMARTBUILDING_DATA_DIR}"
echo "using $CONTAINER_CLIP"

# 3) 打样。注意两点：
#    - 用 -sS（不是 -sf）—— -f 会让 HTTP 4xx/5xx 时 body 也不吐；空 stdin 进
#      python -m json.tool 会得到误导性的 "Expecting value: line 1 column 1"
#    - json.tool 默认会把中文转成 \uXXXX；加 --no-ensure-ascii 才能直接看到中文
#    - 一定要显式传 method + processor_kwargs，与 task-poller 生产路径对齐；不传
#      method 时服务端会走一个 broken 默认（返 "Unsupported summarization method:
#      SUMMARIZATION_METHOD_TYPE.USE_ALL_T_1" —— 下划线 vs 连字符大小写 bug）
curl -sS -X POST http://localhost:8192/v1/summary \
  -H "Content-Type: application/json" \
  -d "{
    \"video\": \"$CONTAINER_CLIP\",
    \"task\": \"child_safety_monitor\",
    \"method\": \"SIMPLE\",
    \"processor_kwargs\": {\"levels\": 1, \"level_sizes\": [-1], \"process_fps\": 2}
  }" | python3 -m json.tool --no-ensure-ascii
```

如果只想看 VLM 输出文本，也可以把最后一段换成 `| jq -r '.summary'`。

期望 `summary_text` 包含（大小写不敏感）：

- `SEVERITY: critical | warn | info`
- `EVENT: <event 名>`
- `DESC: <一句话描述>`

若字段缺失，说明 prompt 与 schema 不匹配 —— 用 [use-case-adapter.md §3.2](./use-case-adapter.md) 的 `smartbuilding_use_case_validate` 定位问题。

**若返回不是预期 JSON，先看错误 body**：`-sf` 会吞掉错误 body 让 python 报
"Expecting value: line 1 column 1" —— 换 `-v` 看完整 HTTP 交互：

```bash
curl -v -X POST http://localhost:8192/v1/summary \
  -H "Content-Type: application/json" \
  -d "{\"video\": \"$CONTAINER_CLIP\", \"task\": \"child_safety_monitor\"}" 2>&1 | tail -30
```

`< HTTP/1.1 <code>` 那行 + 下面的 JSON body 会告诉你根因（`Local file not found`
→ 三方 host_prefix 不一致；`task not found` → VLM task 没注册；详见 §8.2）。

---

## 5. 功能验证（U1 – U8，基线）

启动完 §3 之后，逐个 case 执行。

### U1. `child_safety`：critical 触发

`start-streams.sh` 已经把 `child_safety_demo_expanded_1h.mp4` loop 推到
`rtsp://localhost:8554/live/child`。等 20-40 秒让 VSA motion + prefilter 出第一个
带 person 的 clip，然后：

```bash
# 查最新 alert（先按 §3.3 跑过 mcp_init）
mcp_call smartbuilding_alert_query '{"monitor_id":"cam_child","action":"latest","limit":1}' \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
for c in d.get('result',{}).get('content',[]):
    if c.get('type')=='text': print(c['text'])
"
```

期望：一条 alert，`description` 以 `[child_safety] <event>: critical —` 开头。

### U2. `child_safety`：info 短路

同一 loop 视频里必然还会切出一批 severity=info 的 clip（例如安静玩耍片段）。

```bash
# 直接查 video_summary_tasks，找 severity=info 的行
python3 -c "
import sqlite3, os
con = sqlite3.connect(f\"{os.environ['SMARTBUILDING_DATA_DIR']}/smartbuilding.db\")
for r in con.execute(\"\"\"SELECT id, event, severity, desc
                          FROM video_summary_tasks
                          WHERE monitor_id='cam_child' AND severity='info'
                          ORDER BY id DESC LIMIT 3\"\"\"):
    print(r)
"
```

对其中任一 `severity=info` 的 task_id 跑 `smartbuilding_rule_eval`，期望
`rule_result.shouldAlert=false`。

### U3. `child_safety`：Prefilter 前置过滤（可选）

当 [monitors.yaml.example](../monitors.yaml.example) `cam_child.prefilter.enabled=true`
时，画面里没 person / 目标类的 motion 事件被 prefilter 直接删掉。查
`motion_events/<date>/*.mp4` 无对应文件即可确认（无需再单独推空场景视频）。

### U4. `elder_wakeup`：late_wakeup 触发

**先把 rules 改成让"当前时间"必然被判"晚起"**：

```bash
vim config.yaml.example
# use_case_dict.elder_wakeup.rules:
#   expectedWakeupLocal: "00:00"
#   graceMinutes: 0

# 重启 MCP
node packages/mcp-server/dist/index.js --http \
  --config config.yaml.example \
  --monitors monitors.yaml.example
```

`expectedWakeupLocal="00:00"` 且 `graceMinutes=0` 时，任意实际时刻的 `get_up`
clip 都会被判 late。等 loop 视频里下一个 wakeup clip 处理完，查 alerts：期望有
`[elder_wakeup] late_wakeup: warn —` 一条。

### U5. `elder_wakeup`：on_time 不触发

把同一处 rules 改为 `expectedWakeupLocal="23:59", graceMinutes=59`，然后重启
MCP。期望 alerts 无新增。

### U6. `elder_wakeup`：event 短路

同 loop 里必然还有 `still_in_bed` clip，rule 层因 `event != get_up` 直接短路 return。

### U7. `fridge`：report-only + 无抑制规则

`cam_fridge` loop 推冰箱视频；正常运行期望 alerts 无新增——因为 `fridge_monitor` 输出不含 `SEVERITY`，`defaultRuleEvaluator` 在 severity 检查处短路（见 §2.3）。

**FR-inject-critical**：手工塞一条带 `severity=critical` 的 task，再 dry-run `smartbuilding_rule_eval`。**注意与旧文档不同**：fridge 已无 stub，此时 `shouldAlert` 会是 **true**——用来印证"fridge 没声明任何抑制规则"这一事实。

```bash
mcp_init   # §3.3，若还没握手

# 确保 DB 路径环境变量存在（未设置时使用默认目录）
export SMARTBUILDING_DATA_DIR="${SMARTBUILDING_DATA_DIR:-$HOME/.mcp-smartbuilding}"
DB_PATH="$SMARTBUILDING_DATA_DIR/smartbuilding.db"
[ -f "$DB_PATH" ] || { echo "DB not found: $DB_PATH"; exit 1; }

# 手工构造 completed task（假装 VLM 输出了 critical），把 task_id 抓成 shell 变量
TASK_ID=$(python3 - <<'PY'
import sqlite3, os
con = sqlite3.connect(f"{os.environ['SMARTBUILDING_DATA_DIR']}/smartbuilding.db")
con.execute("""INSERT INTO video_summary_tasks
    (monitor_id, event_id, status, summary_text, event, severity, desc, created_at)
    VALUES ('cam_fridge', NULL, 'completed',
            'SEVERITY: critical\nEVENT: food_critical\nDESC: pretend',
            'food_critical', 'critical', 'pretend', datetime('now'))""")
con.commit()
row = con.execute("SELECT id FROM video_summary_tasks WHERE monitor_id='cam_fridge' ORDER BY id DESC LIMIT 1").fetchone()
print(row[0])
PY
)
echo "task_id=$TASK_ID"
[ -n "$TASK_ID" ] || { echo "insert failed: TASK_ID is empty"; exit 1; }

# rule_eval dry-run（不 create_alert）—— 这里不写 alert，只看判定
mcp_call smartbuilding_rule_eval "$(jq -n --argjson t "$TASK_ID" '{monitor_id:"cam_fridge",task_id:$t}')" \
  | jq '.result.content[0].text | fromjson | {rule_result, alert_created}'
```

期望响应含 `"rule_result": {"shouldAlert": true, "alertMessage": "[fridge] food_critical: critical — pretend"}`（dry-run 下 `alert_created` 为 `null`，不落 DB）。

> 想让 fridge 即使遇到 critical 也恒不告警，需要新增 `evaluate_rules.py` no-alert override；默认 demo 不提供该脚本，而是保持 `prompt.md` 不产出 `SEVERITY` 行。测试完记得 `DELETE FROM video_summary_tasks WHERE id=<TASK_ID>` 清理这条假数据。

### U8. rule_eval：dry-run vs create_alert=true

**目的**：验证 rule_eval 两种模式的语义。dry-run 只返回 evaluator 判定不写 DB；
create_alert=true 才落 alerts 表。连续两次 `create_alert:true` 会各自写入一条
alert（rule 层不做去重），用户通知层去重由 subscription / client 侧策略处理。

```bash
export SMARTBUILDING_DATA_DIR="${SMARTBUILDING_DATA_DIR:-$HOME/.mcp-smartbuilding}"

# 1) 抓一条 critical task 并把 id 存进 shell 变量（不要用 <some_id> 占位符原样粘贴）
TASK_ID=$(sqlite3 "$SMARTBUILDING_DATA_DIR/smartbuilding.db" \
  "SELECT id FROM video_summary_tasks WHERE monitor_id='cam_child' AND severity='critical' AND status='completed' ORDER BY id DESC LIMIT 1;")
echo "TASK_ID=$TASK_ID"

# 2) 记录 create_alert 前 cam_child alerts 总数
BEFORE=$(sqlite3 "$SMARTBUILDING_DATA_DIR/smartbuilding.db" \
  "SELECT COUNT(*) FROM alerts WHERE monitor_id='cam_child';")
echo "alerts BEFORE = $BEFORE"

# 3) Dry-run —— 不传 create_alert
mcp_call smartbuilding_rule_eval "$(jq -n --argjson t "$TASK_ID" '{monitor_id:"cam_child",task_id:$t}')" \
  | jq '.result.content[0].text | fromjson | {rule_result, alert_created, alert_id}'

# 4) 中间校验：alerts 总数没变
MID=$(sqlite3 "$SMARTBUILDING_DATA_DIR/smartbuilding.db" \
  "SELECT COUNT(*) FROM alerts WHERE monitor_id='cam_child';")
echo "alerts AFTER dry-run = $MID  (期望 = BEFORE = $BEFORE)"

# 5) create_alert=true —— 真写 alert
mcp_call smartbuilding_rule_eval "$(jq -n --argjson t "$TASK_ID" '{monitor_id:"cam_child",task_id:$t,create_alert:true}')" \
  | jq '.result.content[0].text | fromjson | {rule_result, alert_created, alert_id}'

# 6) 最终校验：alerts +1
AFTER=$(sqlite3 "$SMARTBUILDING_DATA_DIR/smartbuilding.db" \
  "SELECT COUNT(*) FROM alerts WHERE monitor_id='cam_child';")
echo "alerts AFTER create_alert=true = $AFTER  (期望 = BEFORE + 1 = $((BEFORE+1)))"
```

**期望**：
- Dry-run 返回 `rule_result.shouldAlert=true, alert_created=null` → alerts 总数**不变**
- create_alert=true 返回 `alert_created=true, alert_id=<新 id>` → alerts 总数**+1**（rule 层不做去重，每次 `create_alert=true` 都会新增一条）

---

## 6. 验收清单（基线）

| # | 项目 | 期望 |
|---|-----|------|
| U1 | child_safety critical | `[child_safety] <event>: critical — ...` 存在 |
| U2 | child_safety info 短路 | severity=info 的 task rule_eval `shouldAlert=false` |
| U3 | prefilter | motion_events 目录里无对应 clip 或 events 无对应行 |
| U4 | elder_wakeup late | `[elder_wakeup] late_wakeup: warn — ...` 存在 |
| U5 | elder_wakeup grace | alerts 无新增 |
| U6 | elder_wakeup event 短路 | alerts 无新增 |
| U7 | fridge report-only | 正常无 `SEVERITY` → 不触发；注入 `severity=critical` 后 rule_eval 返回 `shouldAlert: true`（fridge 未声明任何抑制规则，非旧版 stub）|
| U8 | rule_eval | dry-run 只返回 evaluator 结果不写 DB；create_alert=true 时写 DB（rule 层不做去重，每次都 +1）|

---

## 7. 相关文档

- **契约层**：[apis/videostream_analytics_api.md](./apis/videostream_analytics_api.md)
- **VSA 联调**：[vsa-gsg.md](./vsa-gsg.md)
- **VLM 联调 / task 注册**：[vlm-integration-gsg.md](./vlm-integration-gsg.md)
- **VSA 实现**：[implements/videostream-analytics-microservice.md](./implements/videostream-analytics-microservice.md)
- **Use case adapter 使用手册**：[use-case-adapter.md](./use-case-adapter.md)
- **端到端 schema→parser→alert 数据流**：[implements/schema-usecase-parser-alerts-pipeline.md](./implements/schema-usecase-parser-alerts-pipeline.md)
- **override 协议**：[../use-cases/README.md](../use-cases/README.md)

---

## 8. 常见问题

### 8.1 RTSP 报 `DESCRIBE failed: 404 Not Found` / `Cannot open RTSP`

现象：MCP / VSA log 里刷屏

```
[stream_monitor.continuous_recorder] ERROR: [cam_fridge] Recorder error: Cannot open RTSP: rtsp://localhost:8554/live/fridge
[rtsp @ 0x...] method DESCRIBE failed: 404 Not Found
```

**根因**：mediamtx 已经启动（TCP 连接建得起来，所以能收到 404 —— 如果 mediamtx
没起会是 `Connection refused`），但 **`/live/fridge` 这条 path 目前没有任何
publisher**——ffmpeg 推流没在跑，或跑失败了。

排查：

```bash
cd smart-community/demo-videos
./start-streams.sh --status        # 看每条流的 pid
cat .run/cam_fridge.log            # 看 ffmpeg 错在哪
cat .run/_mediamtx.log             # 看 mediamtx 有没有 error
```

`--status` 里如果一片 `dead (stale pidfile)`，就是 ffmpeg 全挂了；常见原因：

- 视频文件不存在（`skip <sid>: file not found` 会打到 log）
- mediamtx 还没 bind :8554，ffmpeg 起太早——`start-streams.sh` 里有 2s 内的 poll 兜底，如果还不行手动 `./start-streams.sh --stop && ./start-streams.sh` 重来
- 另一个进程占了 :8554（`ss -tln | grep 8554`）
- 手动 `ffmpeg ... &` 推流（如 §9.3 步骤 B / §9.7 的 pet / high_altitude / parking）时**缺 `-nostdin`**：后台 ffmpeg 去读控制终端 stdin，被 `SIGTTIN` 挂起（`ps -o pid,stat,cmd -C ffmpeg` 看到状态 **`T`**），进程还在但没推流 → 对应 path 返 404。加 `-nostdin` 并 `</dev/null` 重定向即可（`pkill -f 'ffmpeg.*live/pet'` 慎用——`-f` 会连正在执行该命令的 shell 一起匹配杀掉，按 PID 或进程名清理）

修好之后 `ffprobe -v error -rtsp_transport tcp -i rtsp://localhost:8554/live/fridge && echo OK`
返 OK，MCP 那边 recorder 会自动 reconnect（默认 10s 一次）。

### 8.2 multilevel-video-understanding `POST /v1/summary` 返 400 Bad Request

现象：容器日志

```
multilevel-video-understanding-1  | INFO:     172.19.0.1:59052 - "POST /v1/summary HTTP/1.1" 400 Bad Request
```

MCP 侧对应报错：`video-summary HTTP 400: <detail>`（详见
[packages/tools/src/clients/video-summary-client.ts](../packages/tools/src/clients/video-summary-client.ts)）。

400 有两个高频根因，按顺序排：

**根因 A（最常见）：task 未注册**

`child_safety_monitor` / `elder_wakeup_monitor` / `high_altitude_monitor` /
`parking_safety_monitor` 都不是 VLM 内置 task，必须先 POST `/v1/tasks` 注册进去。

```bash
# 看现在注册了什么
curl -sf http://localhost:8192/v1/tasks | jq '.tasks[].name'
# 只有 6 个 builtin？跑一键注册脚本（详见 vlm-integration-gsg.md §3.2）
```

跑完应能看到 `child_safety_monitor` / `elder_wakeup_monitor` 等 dynamic 项。

**根因 B：容器读不到 clip 文件**

400 response body 会写 `Local file not found: /data/segments/...` 之类。
起因是 host `~/.mcp-smartbuilding/` 没挂载到容器 `/data/`，或
[config.yaml.example](../config.yaml.example) 里 `summary_service.path_remap` 缺失/写错。

三处必须指向**同一个 host 目录**：

- MCP 端环境变量：`SMARTBUILDING_DATA_DIR=$HOME/.mcp-smartbuilding`
- `docker/multilevel-video-understanding/set_env.sh` 里的同名变量
- `config.yaml.example`：
  ```yaml
  summary_service:
    path_remap:
      host_prefix: ${HOME}/.mcp-smartbuilding
      container_prefix: /data
  ```

对齐后 `docker compose up` 重启 multilevel 容器。

**如何进一步定位 A vs B**：

```bash
# 让 VLM 直接告诉你 400 原因
curl -v -X POST http://localhost:8192/v1/summary \
  -H "Content-Type: application/json" \
  -d '{"video":"/data/no-such-file.mp4","task":"child_safety_monitor"}' 2>&1 | tail -20
```

- `unknown task` → 根因 A
- `Local file not found` → 根因 B（这里给的 fake 路径就会返这个）

### 8.3 VLM 输出格式与 prompt 期望不符

现象：alerts 表始终为空，即使 `severity` 应该 critical。

排查：
1. `smartbuilding_use_case_validate use_case=<uc>` 检查 `LOCAL_PROMPT` 是否包含 required 字段名
2. 直接 `curl POST /v1/summary` 打样 VLM（§4），确认返回文本里有 `SEVERITY:` / `EVENT:` / `DESC:`
3. 查 `video_summary_tasks` 的扩展列（`event` / `severity` / `desc`）是否被 parser 填了：

```bash
python3 -c "
import sqlite3, os
con = sqlite3.connect(f\"{os.environ['SMARTBUILDING_DATA_DIR']}/smartbuilding.db\")
for r in con.execute(\"SELECT id, event, severity, desc FROM video_summary_tasks ORDER BY id DESC LIMIT 3\"):
    print(r)
"
```

若扩展列都是 `NULL`，parser 没抓到；检查 config.yaml.example 里 `schema.video_summary_tasks.extensions` 是否列出这些字段。

### 8.4 elder_wakeup 时间比较不可控

override 用 `datetime.now()` 读实时。测试时用**热改 rules**（改 `expectedWakeupLocal` / `graceMinutes` 制造边界条件）+ 重启 MCP 覆盖。生产用途本身依赖真实时间，无需处理。

### 8.5 alerts 表迟迟没数据

按顺序排查：
1. VSA 是否发了 webhook？（查 VSA log 里 `Emitted motion`）
2. MCP `/events` 是否收到？（查 MCP log `[events-endpoint] received event`）
3. task 是否 completed？（`SELECT status FROM video_summary_tasks`）
4. rule engine 是否返回 shouldAlert=true？（用 `smartbuilding_rule_eval` dry-run 复现）

任一环节断，问题聚焦到那一层，往上游查。

### 8.6 prompt.md 编写自查项

prompt 由 `video-summary-prompt-studio` skill（agent + router）起草，skill 已把下列校验作为
**invariant** 内联，起草/POST 前自动自查；手写 `prompt.md` 时也照此对照。服务端 `POST /v1/tasks`
还会对缺失 anchor 返回 422 + 参考模板兜底。

| 问题 | 含义 | 处理 |
|---|---|---|
| 三反引号 code fence | prompt 里有 ```，会被 `/v1/tasks` 拒收（`banned_token`） | **必须**删掉 code fence |
| `A \| B \| C` pipe 枚举 | 小 VLM 可能照抄 pipe 枚举 | **建议** refine 成逐行取值范围 |
| event 名遗漏 | 某些 event 没进 prompt | **必须**补上遗漏的 event |
| anchor 大小写 / 必填 placeholder 缺失 | `LOCAL_PROMPT` 等锚点大小写敏感；`{st_tm}` 等占位符必填 | 按 skill invariant 表对照修正 |

---

## 9. 零重启动态注册新 use case

### 9.0 从零完整步骤速览（Phase 0–5，`pet_safety.mp4`）

> 这是"新增一个 use case，从零到跑通"的**压缩版流程图**。
> 每个 Phase 的**完整可复制命令**在下面 §9.3 的步骤 A0–E 里；本速览只列顺序、关键参数与易踩坑点。
> 所有 MCP 命令前先按 §3.3 跑一次 `mcp_init`。
> 目标兑现 Design §5.2 承诺：**零 TS 代码 / 零手工 curl VLM / 零手写 YAML / 零 prompt 从空白写 / 零 Python override**（简单阈值类 UC）。

**管线**：`ffmpeg 推流 → MediaMTX → VSA motion → webhook → MCP 建 task → poller 切 clip → POST /v1/summary（video-summary/multilevel）→ schema-aware parser 抽字段 → defaultRuleEvaluator（或 evaluate_rules.py）→ alert`。

#### Phase 0 — 起 4 个服务（都不为 pet_safety 改配置，这才叫"从零"）

按此顺序（详见 §3）：

1. **MediaMTX + 推流**：`cd demo-videos && ./start-streams.sh`（脚本自起 mediamtx，配置在 `videostream-analytics/tools/mediamtx.yml`）。pet 视频可另行 `ffmpeg -nostdin -re -stream_loop -1 -i demo-videos/cam_pet/pet_safety.mp4 -c copy -f rtsp rtsp://localhost:8554/live/pet </dev/null &`（放到 Phase 4 推也行；`-nostdin` 必加，否则后台 ffmpeg 被 SIGTTIN 挂起 → RTSP 404）。
2. **VSA `:8999`**：本地 `cd videostream-analytics && .venv/bin/videostream-analytics serve --config config/config.yaml`，或 `docker compose -f videostream-analytics/docker/docker-compose.yaml up -d`。
3. **VLM stack**：`cd docker/video-summary && source set_env.sh && docker compose -f compose.yaml up -d` → vLLM `:41091` + multilevel `:8192`，等 healthy。
   - ⚠️ 目录是 **`docker/video-summary/`**、compose 文件是 **`compose.yaml`**。
4. **MCP `:3100`+`:3101`**：`node packages/mcp-server/dist/index.js --http --config config.yaml.example --monitors monitors.yaml.example`。
   - 当前 [monitors.yaml.example](../monitors.yaml.example) 只含 4 个基线 monitor（`cam_fridge` / `cam_child` / `cam_elder_bedroom` / `cam_elder_bedroom_2`。只要这 4 条流都在推（§3.1 已验证），带 `--monitors monitors.yaml.example` 启动即可，不会有 RTSP 噪声。
   - ⚠️ 若只想单验 pet_safety、又不想拉起这 4 个基线 monitor，可省略 `--monitors`（启动后只靠 §9.3 步骤 B 动态注册 `cam_pet`）；`cam_pet` **不要**写进 `monitors.yaml.example`，否则未 persist use case 时重启会因 unknown use_case 退出（见 §9.4）。
   - ⚠️ config.yaml.example 里**没有预置** pet_safety（只有 fridge/child_safety/elder_wakeup）——它靠 Phase 2 的 `register persist:true` 动态写入。

#### Phase 1 — 素材（仓库已备好，无需生成）

`use-cases/pet_safety/{prompt.md, evaluate_rules.py}` + `demo-videos/cam_pet/pet_safety.mp4` 均已在仓库中。

#### Phase 2 —（可选）生成 prompt 骨架 + 零重启注册

- **（可选）起草 prompt 骨架**：用 `video-summary-prompt-studio` skill（agent + router）产出 `## LOCAL_PROMPT` 骨架，存到 `use-cases/pet_safety/prompt.md` 后人工 refine（自查项见 §8.6）。不想用可直接手写 prompt.md。
- **`action=register`（§9.3 步骤 A）一次干 4 件事**（persist 是可跳过的第 5 件）：
  1. `schema_extensions` → `ALTER TABLE video_summary_tasks ADD COLUMN`（幂等）+ merge 到内存 schema
  2. `prompt_text` → POST `/v1/tasks`（409 自动 PATCH）
  3. 注入内存 `use_case_dict[pet_safety]`（task-poller 下一轮 poll 即见）
  4. 复核 `use_case_validate`（结果在 `steps.validate`）
  5. `persist:true` → 用 yaml Document API 写回 `config.yaml.example`（`steps.config_yaml=written`）
  - **零 Python**：不传 `evaluate_rules_path`；靠内置 `defaultRuleEvaluator` 对 `severity=warn|critical` 触发告警。
  - **自定义规则**：需要 event/zone 过滤、时间比较或自定义 alert message 时，传 `evaluate_rules_path` 指向 agent 生成的 `evaluate_rules.py`。
  - **零 YAML 手工**：传 `persist:true`（前提 MCP 启动带了 `--config`）。不 persist 时只改内存，MCP 重启即丢，且引用它的 monitor 会让 MCP 因 unknown use_case 退出。

#### Phase 3 —（可选）单独给 VLM 打样

拿一个真实 clip（VSA motion 后 20–40s 才有），POST `:8192/v1/summary`，看输出有没有 `SEVERITY: / EVENT: / DESC: / PET_ZONE:`。**务必显式传 `method:"SIMPLE"` + `processor_kwargs`**，否则服务端走 broken 默认（报 `Unsupported summarization method: ...USE_ALL_T_1` 的连字符/下划线 bug）。命令见 §4。

#### Phase 4 — 加 monitor + 推流（§9.3 步骤 B）

`smartbuilding_monitor_ctl action=register_source`（`monitor_id=cam_pet`, `use_case=pet_safety`, `source_url=rtsp://localhost:8554/live/pet`, `pipeline_config={motion,prefilter,recording,segment}`）——内部自动跑 `use_case_validate`（此时 useCaseDict 已有 pet_safety，通过）。若 Phase 0 没推 pet 流，此时用 ffmpeg 推。

#### Phase 5 — 观察落库（§9.3 步骤 C）

- `video_summary_tasks`：`pending→completed`，且结构化列 `event/severity/desc/pet_zone` 被 schema-aware parser 填好。
- `segments/cam_pet/motion_events/<date>/*.mp4`：clip 落 host。
- `alerts` + `smartbuilding_alert_query action=latest`：应见 `[pet_safety] pet_escape: warn — ... (zone=阳台)`。
  - ⚠️ `alerts` 是瘦表，**没有** event/severity/pet_zone 列——结构化字段在 `video_summary_tasks`，查 SQLite 需 `LEFT JOIN video_summary_tasks t ON t.id=a.task_id`（见 §9.3 步骤 C 末尾）。

**退路**：motion 不触发（loop 视频画面变化太小）→ 退到手塞 task + `smartbuilding_rule_eval` 单独验规则层（见 §5 U7 / U8 与 [use-case-register-verification.md §8](./dev/use-case-register-verification.md)）。

**清场**：§9.3 步骤 E（停 monitor / 删关联表 / `unregister persist:true`）。

> 想要每一步的"期望输出 JSON + 失败定位 + 参数负例 + persist 重启恢复"，配合读
> [dev/use-case-register-verification.md](./dev/use-case-register-verification.md)（该文档是本节的详细验证对照版）。

---

### 9.1 背景

MCP server 启动时把 `config.yaml` 的 `use_case_dict` 一次性快照到 `ServerConfig.useCaseDict`
（详见 [packages/mcp-server/src/config.ts:180](../packages/mcp-server/src/config.ts#L180)），
然后**按引用**传给所有 tool handler、[task-poller.ts:76](../packages/mcp-server/src/video-worker/task-poller.ts#L76)、
`WorkerService`。这意味着：

- 修改 `config.yaml` 后**不重启就不生效**
- 但**运行时直接 mutate `config.useCaseDict[name] = entry`** 会立即被所有下游看到（task-poller 每次 poll 都新读 `this.config.useCaseDict[useCase]`，不是启动时快照）
- 同样：`schema.video_summary_tasks.extensions` 底层是通过 `PRAGMA table_info` + `ALTER TABLE ADD COLUMN` 幂等应用（[schema-manager.ts:92](../packages/db/src/schema-manager.ts#L92)），运行时再次调用 `applySchema` 安全
- VLM `/v1/tasks` 本来就热更新（`POST` / `PATCH` / `DELETE`，state 持久化到容器内 `~/.cache/.multilevel-video-understanding/tasks/`）

基于这三点，`smartbuilding_use_case_register` 这个 MCP tool 把三层的操作打包成一步。

### 9.2 `smartbuilding_use_case_register` 工作原理

`action=register` 内部按顺序执行 4 步：

1. **Schema 扩展**：如果传了 `schema_extensions=[{name, type, required}, ...]`，对 `video_summary_tasks` 表跑 `ALTER TABLE ADD COLUMN`（列已存在则跳过），同时把这些扩展 merge 到 `config.schema.video_summary_tasks.extensions` 内存副本里，保证后续 `use_case_validate` 的 required-field 检查能看到
2. **VLM task 注册**：如果传了 `prompt_text`，POST `/v1/tasks`；收到 `409 Conflict` 时自动 PATCH。`prompt_text` 支持两种格式：
   - Markdown 带 `## LOCAL_PROMPT` / `## GLOBAL_PROMPT` 段（同 [use-cases/<uc>/prompt.md](../use-cases/) 文件格式）—— tool 会自动拼装成 4 常量 Python 源码
   - 已经拼好的 4 常量源码（含 `GLOBAL_PROMPT = '''...'''` 字样）—— 原样透传
3. **注入内存 `use_case_dict`**：把 `{video_summary_task, description, evaluate_rules_path, ...}` 组成的 entry `config.useCaseDict[use_case] = entry`；task-poller 下一轮 poll 就能读到
4. **调 `use_case_validate` 复核**：把三步的效果串起来检查一次，结果放在 `steps.validate` 里返回

`action=unregister`：DELETE `/v1/tasks/<name>` + `delete config.useCaseDict[name]`。schema 扩展列**不回滚**（sqlite 没法 drop column 而不破坏数据）。

**当 `persist: true`** 时，register 和 unregister 都会用 yaml `Document` API 把改动**写回 `--config` 指定的 config.yaml 文件**（注释和字段顺序保留）—— MCP 重启后仍在，不再是 in-memory-only。

**prompt 起草**：Design §5.2 Step 3 "LLM 生成 VIDEO_SUMMARY prompt" 由 `video-summary-prompt-studio`
skill（agent + router）承担——agent 起草 `## LOCAL_PROMPT`，用户 review + refine 后经 `action=register`
的 `prompt_text` 落地。prompt 静态校验规则内联在 skill invariant 里（见 §8.6）。

### 9.3 零代码 + 零重启操作步骤（`pet_safety` 实测例子）

本节以 `pet_safety` 为例走一遍完整链路，验证 Design §5.2 的承诺：**新增一个 use case 不改 TypeScript、不手写 YAML、不手工注册 VLM task**。简单 warn/critical 严重级 use case 可直接使用内置 `defaultRuleEvaluator`；需要 event/zone 过滤时由 agent 生成 `evaluate_rules.py`。

单验 `pet_safety` 时只需动态注册 `cam_pet`。是否带 `--monitors monitors.yaml.example` 启动都可以：带上会同时拉起 4 个基线 monitor（前提是它们的流都在推）；只想验 `cam_pet` 就省略 `--monitors`。**不要**把 `cam_pet` 写进 `monitors.yaml.example`，它由步骤 B 动态注册。推荐启动顺序：

1. 启动 MediaMTX 并推 `rtsp://localhost:8554/live/pet`
2. 启动 VSA `:8999`
3. 启动 VLM stack：multilevel `:8192` + vLLM `:41091`
4. 启动 MCP：`node packages/mcp-server/dist/index.js --http --config config.yaml.example`
5. 用 `smartbuilding_monitor_ctl register_source` 动态注册 `cam_pet`

#### 步骤 A0 —（推荐）用 `video-summary-prompt-studio` skill 生成 prompt.md 骨架

`video-summary-prompt-studio` skill（agent + router 自动选型/回退）负责起草：给 skill "3 个语义输入"
（use case 名 + 一句描述 + event_types 表 + 可选 schema_extensions），agent 起草遵循 prompt writing
convention 的 `## LOCAL_PROMPT` 骨架（无 `A | B | C` 枚举、无 code fence、含正/反输出示例），并按 skill
invariant 自查 anchor/placeholder/banned token。产物存到 `use-cases/pet_safety/prompt.md`。

以 pet_safety 为例，交给 skill 的语义输入：

- **use_case**：`pet_safety`
- **description**：监控家里的宠物是否处于危险状态（被卡住/困住/异常挣扎/尝试逃离/正常休息玩耍）
- **event_types**：`pet_stuck`(critical) / `pet_escape`(warn) / `pet_normal`(info) / `no_incident`(info)
- **schema_extensions**：`severity`(text, 可选) / `event`(text, 必填) / `desc`(text, 必填) / `pet_zone`(text, 可选)

然后 review `use-cases/pet_safety/prompt.md`，人工 refine 业务边界（例如补充"宠物在门缝里挣扎"、"宠物爬向阳台栏杆"等具体例子）；但不需要从空白手写 prompt。

> **不想用 skill？** 完全跳过 §A0，直接进 §A（手写 prompt.md）。register 只需要 `prompt_text`，不关心 prompt 怎么来的。

#### 步骤 A — 注册 use case

这一步使用 agent 生成的 `use-cases/pet_safety/evaluate_rules.py`，因为 pet_safety 需要过滤 `pet_normal` / `no_incident` 并在 alert message 中携带 `pet_zone`。如果你的 use case 只需要 `severity=warn|critical` 触发告警，可以省略 `evaluate_rules_path`。

```bash
PROMPT_TEXT=$(cat use-cases/pet_safety/prompt.md)

mcp_call smartbuilding_use_case_register "$(jq -n --arg pt "$PROMPT_TEXT" '{
  action: "register",
  use_case: "pet_safety",
  video_summary_task: "pet_safety_monitor",
  description: "Pet safety monitoring (dynamic)",
  evaluate_rules_path: "./use-cases/pet_safety/evaluate_rules.py",
  summarize: {
    method: "SIMPLE",
    processor_kwargs: { levels: 1, level_sizes: [-1], process_fps: 2 }
  },
  reports: { data_source: "alerts", default_type: "daily", filter: {} },
  prompt_text: $pt,
  schema_extensions: [
    { name: "severity", type: "text", required: false },
    { name: "event", type: "text", required: true },
    { name: "desc", type: "text", required: true },
    { name: "pet_zone", type: "text", required: false }
  ],
  persist: true,
  overwrite: true
}')" | jq '.result.content[0].text | fromjson'
```

> **`persist: true`** — 让 tool 用 yaml Document API 把 use case 条目写回
> `config.yaml.example`，注释和字段顺序保留。这样 MCP 重启后 use case 依然
> 在磁盘 config 里；引用它的 monitor 也能在重启后继续加载。
> 前提：MCP 启动时用了 `--config <path>` 参数。若省略 `persist` 参数，只改
> 内存（`steps.config_yaml: "skipped"` 会出现在返回体里）。

**期望输出**（关键字段）：

```json
{
  "action": "register",
  "use_case": "pet_safety",
  "ok": true,
  "steps": {
    "schema": {
      "added": [
        "video_summary_tasks.severity",
        "video_summary_tasks.event",
        "video_summary_tasks.desc",
        "video_summary_tasks.pet_zone"
      ],
      "warnings": []
    },
    "vlm_task": "registered",
    "use_case_dict": "added",
    "config_yaml": "written",
    "validate": {
      "valid": true,
      "use_case": "pet_safety",
      "video_summary_task": "pet_safety_monitor",
      "checks": {
        "use_case_known": true,
        "task_registered": true,
        "schema_consistent": true
      }
    }
  },
  "warnings": [],
  "errors": []
}
```

如果 `pet_zone` 列已经存在（例如你重跑），`schema.added` 会是空数组；如果 task
已经注册过，`vlm_task` 会是 `"updated"`（自动走了 PATCH 分支）。
`config_yaml: "written"` 表示 `config.yaml.example` 已同步落盘（配了 `persist:true` 且 MCP 启动时带了 `--config`）；不传 `persist:true` 或 MCP 未带 `--config` 时值为 `"skipped"`。

#### 步骤 B — 加 monitor 并让它开始跑

现有 MCP 依然在跑，直接调 `smartbuilding_monitor_ctl register_source`——它内部会跑
`use_case_validate`（此时 `use_case_dict` 里已经有 `pet_safety`，validate 通过）：

```bash
# 先把宠物视频推到 mediamtx（生成一个新 stream path）
# 这里假设你已经准备了 demo-videos/cam_pet/pet_safety.mp4
# 关键：-nostdin + </dev/null——否则后台 ffmpeg 会去读控制终端 stdin 被 SIGTTIN 挂起
#       （ps 看到状态 T），根本没推流，VSA 侧表现为 RTSP DESCRIBE 404（见 §8.1）
mkdir -p demo-videos/.run
ffmpeg -nostdin -re -stream_loop -1 -i demo-videos/cam_pet/pet_safety.mp4 \
  -c copy -f rtsp -rtsp_transport tcp rtsp://localhost:8554/live/pet \
  </dev/null > demo-videos/.run/cam_pet.log 2>&1 &

# 用 MCP tool 添加 monitor
mcp_call smartbuilding_monitor_ctl '{
  "action":"register_source",
  "monitor_id":"cam_pet",
  "source_url":"rtsp://localhost:8554/live/pet",
  "use_case":"pet_safety",
  "pipeline_config":{
    "motion":{"enabled":true,"diff_threshold":15,"area_ratio":0.003,"stable_frames":30},
    "prefilter":{"enabled":false},
    "recording":{"enabled":true,"interval_seconds":60},
    "segment":{"max_duration":10,"min_duration":1.0}
  }
}' | jq '.result.content[0].text | fromjson'
```

**期望输出**：`{ success: true, monitor_id: "cam_pet", status: "online", ... }`。

约 20-40 秒后应能在 `alerts` 表 / `smartbuilding_alert_query` 里看到 pet_safety 的告警
（如果视频里有 critical 事件）。

#### 步骤 C — 验证 task / alert 落库

查 VLM summary 结果是否被 parser 写入 `video_summary_tasks` 扩展列：

```bash
export SMARTBUILDING_DATA_DIR="${SMARTBUILDING_DATA_DIR:-$HOME/.mcp-smartbuilding}"

sqlite3 "$SMARTBUILDING_DATA_DIR/smartbuilding.db" \
  "SELECT id, monitor_id, status, event, severity, desc, pet_zone, created_at
   FROM video_summary_tasks
   WHERE monitor_id='cam_pet'
   ORDER BY id DESC
   LIMIT 20;"
```

期望类似（时间戳为示例）：

```text
1026|cam_pet|completed|pet_escape|warn|宠物从室内走向阳台，并攀爬上了阳台栏杆，存在高空坠落风险|阳台|2026-01-01 14:42:34
```

含义：`event=pet_escape` 是 VLM 识别的事件类型，`severity=warn` 达到告警阈值，`desc` 是描述，`pet_zone=阳台` 是动态 schema 扩展列落库结果。

查 alert 推荐用 MCP tool：

```bash
mcp_call smartbuilding_alert_query '{"monitor_id":"cam_pet","action":"latest","limit":5}' \
  | jq '.result.content[0].text | fromjson'
```

成功输出中应看到：

```text
[pet_safety] pet_escape: warn — 宠物从室内走向阳台，并攀爬上了阳台栏杆，存在高空坠落风险 (zone=阳台)
```

如果直接查 SQLite，注意 `alerts` 是 use-case-agnostic 瘦表，**没有** `source_id` / `event` / `severity` / `pet_zone` / `acked` 列。结构化字段在 `video_summary_tasks` 上，需要 JOIN：

```bash
sqlite3 "$SMARTBUILDING_DATA_DIR/smartbuilding.db" \
  "SELECT
     a.id,
     a.monitor_id,
     a.use_case,
     t.event,
     t.severity,
     t.pet_zone,
     a.description,
     a.created_at,
     CASE WHEN a.ack_at IS NULL THEN 0 ELSE 1 END AS acked
   FROM alerts a
   LEFT JOIN video_summary_tasks t ON t.id = a.task_id
   WHERE a.monitor_id='cam_pet'
   ORDER BY a.id DESC
   LIMIT 5;"
```

#### 步骤 D — 定位常见实测错误

| 现象 | 原因 | 处理 |
|---|---|---|
| `The model default does not exist` | `config.yaml.example` 的 `vlm_service.model` 与 `:41091/v1/models` 返回的真实模型名不一致 | 改成真实模型名（如 `Qwen/Qwen3.5-35B-A3B`）并重启 MCP |
| `SyntaxError ... "task_id":}` | shell 变量 `TASK_ID` 为空，拼出的 JSON 非法 | 先 `echo "$TASK_ID"`；推荐用 `jq -n --argjson task_id "$TASK_ID"` 组请求 |
| `task-poller task ... failed: fetch failed` | task-poller 调 `:8192/v1/summary` 时服务暂不可用或连接失败 | 查 `curl -sf http://localhost:8192/v1/health` 和 vLLM `/v1/models`；单条 failed 后有 completed task 一般不影响主链路 |
| `FOREIGN KEY constraint failed` when `monitor_ctl unregister` | `cam_pet` 已有 events/tasks/alerts/recordings 引用，直接删除 monitors 被外键挡住 | 生产场景用 `stop` 保留历史；测试清场需先删关联表再删 monitor |

#### 步骤 E — 停止或清场

生产/演示场景只停止 monitor，保留历史数据：

```bash
mcp_call smartbuilding_monitor_ctl '{"action":"stop","monitor_id":"cam_pet"}' \
  | jq '.result.content[0].text | fromjson'
```

如果是测试清场，先停 VSA source，再按依赖顺序删历史数据：

```bash
curl -sS -X DELETE http://localhost:8999/sources/cam_pet || true

sqlite3 "$SMARTBUILDING_DATA_DIR/smartbuilding.db" <<'SQL'
PRAGMA foreign_keys = ON;
DELETE FROM alerts WHERE monitor_id = 'cam_pet';
DELETE FROM reports WHERE monitor_id = 'cam_pet';
DELETE FROM recordings WHERE monitor_id = 'cam_pet';
DELETE FROM plans WHERE monitor_id = 'cam_pet';
DELETE FROM monitor_state WHERE monitor_id = 'cam_pet';
DELETE FROM video_summary_tasks WHERE monitor_id = 'cam_pet';
DELETE FROM events WHERE monitor_id = 'cam_pet';
DELETE FROM monitors WHERE id = 'cam_pet';
SQL
```

最后再 unregister use case（会删除 VLM dynamic task，并在 `persist:true` 时从 config.yaml 删除 use_case_dict entry）：

```bash
mcp_call smartbuilding_use_case_register '{"action":"unregister","use_case":"pet_safety","persist":true}' \
  | jq '.result.content[0].text | fromjson'
```

**期望输出**：

```json
{
  "action": "unregister",
  "use_case": "pet_safety",
  "ok": true,
  "steps": {
    "vlm_task": "deleted",
    "use_case_dict": "removed",
    "config_yaml": "removed"
  },
  "warnings": [],
  "errors": []
}
```

### 9.4 重启后会不会消失

| 层 | 重启后是否保留 |
|---|---|
| VLM `/v1/tasks/<name>` | ✅ 保留（写入容器 `~/.cache/.multilevel-video-understanding/tasks/`）|
| DB schema 扩展列 | ✅ 保留（`ALTER TABLE` 已落盘）|
| `config.useCaseDict[<name>]` | ✅/❌ `persist:true` 时保留；不 persist 时只在内存里，MCP 重启会丢 |
| Monitor（通过 monitor_ctl register_source 加的） | ✅ 保留（写入 SQLite `monitors` 表）|

所以本节推荐的 `register persist:true` 路径下，MCP 重启后能从 `config.yaml.example` 重新加载 `pet_safety`。如果注册时没有 persist，数据库里 `cam_pet`、VLM task、schema 列仍在，但 MCP 重启后会因为找不到 `pet_safety` use case 而抛 `monitors reference unknown use_case keys` 并退出（[index.ts:64-68](../packages/mcp-server/src/index.ts#L64-L68)）。

**修复方式**（两种）：
- **推荐（`persist: true` 自动，已实现）**：register 时传 `persist: true`，tool 会用 yaml Document API 把条目**同步写回 `config.yaml.example`**（保留注释和字段顺序）。重启后 MCP 自动从磁盘加载，无缝继续
- **临时**（不能或不想 persist 时）：先 unregister monitor（`cam_pet`），再重启 MCP，之后再 register_use_case + register_source

### 9.5 关联 tool 一览

| Tool | action | 什么时候用 |
|---|---|---|
| `smartbuilding_use_case_register` | `register` | 一次搞定：schema ALTER + VLM POST /v1/tasks + inject useCaseDict + 可选 `persist=true` 写回 config.yaml（prompt 经 `prompt_text` 传入）|
| `smartbuilding_use_case_register` | `unregister` | 反向清除：DELETE /v1/tasks + remove from useCaseDict + 可选 `persist=true` 从 config.yaml 删条目 |
| `smartbuilding_use_case_validate` | — | 校验现有 use case 的三层（存在 / VLM task 注册 / prompt schema）|
| `smartbuilding_video_summary_task` | `list` / `get` / `delete` | 直接管理 VLM `/v1/tasks`：list 看全部、get 看单条 4 常量、delete 单条 dynamic |
| `smartbuilding_monitor_ctl` | `register_source` 等 | 加/减 monitor；`register_source` 内部自动跑 use_case_validate |
| `smartbuilding_monitors_compose` | `up/down/...` | 批量按 `monitors.yaml` 起 monitor |
| `smartbuilding_rule_eval` | — | dry-run 一个 completed task 看 rule 层判定，不写 DB；`create_alert=true` 时落 alert（rule 层不做去重）|

### 9.6 `pet_safety` 验收结论

跑通后各层证据，证明动态注册链路完整：

| 层 | 证据 | 结论 |
|---|---|---|
| Prompt 起草 | `use-cases/pet_safety/prompt.md` 由 `video-summary-prompt-studio` skill（agent + router）生成，skill invariant 自查 | 零 prompt 从空白手写成立 |
| VLM task | `register` 返回 `vlm_task=registered/updated`，`use_case_validate.valid=true` | 零手工 VLM curl 成立 |
| Schema | `video_summary_tasks.pet_zone` 可查询，值为 `阳台` | 动态 schema 扩展生效 |
| Parser | `summaryText` 中 `pet_zone: 阳台` 被写入 DB `pet_zone` 列 | schema-aware parser 生效 |
| Rules | 不传 `evaluate_rules_path`，alert 仍生成 `(zone=阳台)` | 零 Python override 成立 |
| Alert | `smartbuilding_alert_query latest` 返回 `[pet_safety] pet_escape: warn — ... (zone=阳台)` | VSA → MCP → VLM → rule → alert 全链路通过 |
| Persistence | `persist:true` 写回 config.yaml | 零 YAML 手工成立 |

### 9.7 更多扩展 use case（high_altitude_safety / parking_safety）

`high_altitude_safety`（高空抛物）和 `parking_safety`（违章停车）与 `pet_safety` 一样，是**仓库已备 `prompt.md`** 的扩展 use case。需要方向/zone 过滤时应由 agent 生成 `evaluate_rules.py`：

- `high_altitude_safety` 的 override 验证方向约束
- `parking_safety` 的 override 验证 zone 拼接进 alert 消息 + zone 白名单短路

验证流程与 §9.3 `pet_safety` **完全一致**（`register` → `register_source` → 观察落库），只换 prompt / rules / schema / 视频；真实素材已在仓库，**无需生成**：

| use case | prompt（已在仓库）| 真实视频（已在仓库）| 推流 path |
|---|---|---|---|
| high_altitude_safety | `use-cases/high_altitude_safety/prompt.md` | `demo-videos/cam_ha_test/building-throwing-2.mp4` | `rtsp://localhost:8554/live/high_altitude` |
| parking_safety | `use-cases/parking_safety/prompt.md` | `demo-videos/cam_parking/false-parking.mp4` | `rtsp://localhost:8554/live/parking` |

> 前置：先按 §3.3 跑过 `mcp_init`，并 `export SMARTBUILDING_DATA_DIR="${SMARTBUILDING_DATA_DIR:-$HOME/.mcp-smartbuilding}"`。
> VLM 端 `high_altitude_monitor` / `parking_safety_monitor` 两个 dynamic task 由 `register` 的 `prompt_text` 自动 POST `/v1/tasks`（409 自动 PATCH），无需手工 curl。

#### 9.7.1 high_altitude_safety（验证方向约束）

**注册（需要 evaluate_rules.py）**：

```bash
PROMPT_TEXT=$(cat use-cases/high_altitude_safety/prompt.md)
mcp_call smartbuilding_use_case_register "$(jq -n --arg pt "$PROMPT_TEXT" '{
  action:"register",
  use_case:"high_altitude_safety",
  video_summary_task:"high_altitude_monitor",
  description:"High-altitude object throwing detection (dynamic)",
  evaluate_rules_path:"./use-cases/high_altitude_safety/evaluate_rules.py",
  summarize:{ method:"SIMPLE", processor_kwargs:{ levels:1, level_sizes:[-1], process_fps:2 } },
  prompt_text:$pt,
  schema_extensions:[ { name:"motion_direction", type:"text", required:false } ],
  persist:true, overwrite:true
}')" | jq '.result.content[0].text | fromjson | {ok, steps}'
```

期望 `steps.vlm_task=registered`、`steps.schema.added=["video_summary_tasks.motion_direction"]`、`steps.validate.valid=true`。

**加 monitor + 推真实素材**：

```bash
mkdir -p demo-videos/.run
ffmpeg -nostdin -re -stream_loop -1 -i demo-videos/cam_ha_test/building-throwing-2.mp4 \
  -c copy -f rtsp -rtsp_transport tcp rtsp://localhost:8554/live/high_altitude \
  </dev/null > demo-videos/.run/cam_high_altitude.log 2>&1 &

mcp_call smartbuilding_monitor_ctl '{
  "action":"register_source",
  "monitor_id":"cam_high_altitude",
  "source_url":"rtsp://localhost:8554/live/high_altitude",
  "use_case":"high_altitude_safety",
  "pipeline_config":{
    "motion":{"enabled":true,"diff_threshold":25},
    "prefilter":{"enabled":false},
    "recording":{"enabled":true,"interval_seconds":60},
    "segment":{"max_duration":10}
  }
}' | jq '.result.content[0].text | fromjson'
```

**正例验证**（约 20–40s 后 VSA motion 出 clip）：

```bash
mcp_call smartbuilding_alert_query '{"monitor_id":"cam_high_altitude","action":"latest","limit":1}' \
  | jq -r '.result.content[0].text'
# 期望 description 以 [high_altitude_safety] high_altitude_throw: critical — 开头

sqlite3 "$SMARTBUILDING_DATA_DIR/smartbuilding.db" \
  "SELECT id,event,severity,motion_direction,desc FROM video_summary_tasks
   WHERE monitor_id='cam_high_altitude' ORDER BY id DESC LIMIT 1;"
# 期望 event=high_altitude_throw, motion_direction=downward
```

**反例验证方向短路**（仓库无 upward 真实视频，手塞一条 upward task 再 dry-run，印证 override 会拒绝 upward）：

```bash
TASK_ID=$(python3 - <<'PY'
import sqlite3, os
con = sqlite3.connect(f"{os.environ['SMARTBUILDING_DATA_DIR']}/smartbuilding.db")
con.execute("""INSERT INTO video_summary_tasks
  (monitor_id, status, summary_text, event, severity, motion_direction, desc, created_at)
  VALUES ('cam_high_altitude','completed',
          'SEVERITY: critical\nEVENT: high_altitude_throw\nDESC: pretend\nMOTION_DIRECTION: upward',
          'high_altitude_throw','critical','upward','pretend', datetime('now'))""")
con.commit()
print(con.execute("SELECT id FROM video_summary_tasks WHERE monitor_id='cam_high_altitude' ORDER BY id DESC LIMIT 1").fetchone()[0])
PY
)
mcp_call smartbuilding_rule_eval "$(jq -n --argjson t "$TASK_ID" '{monitor_id:"cam_high_altitude",task_id:$t}')" \
  | jq '.result.content[0].text | fromjson | {rule_result}'
# 期望 rule_result.shouldAlert=false
# 清理：sqlite3 "$SMARTBUILDING_DATA_DIR/smartbuilding.db" "DELETE FROM video_summary_tasks WHERE id=$TASK_ID;"
```

#### 9.7.2 parking_safety（验证 zone 过滤 + alert message extra）

**注册**：

```bash
PROMPT_TEXT=$(cat use-cases/parking_safety/prompt.md)
mcp_call smartbuilding_use_case_register "$(jq -n --arg pt "$PROMPT_TEXT" '{
  action:"register",
  use_case:"parking_safety",
  video_summary_task:"parking_safety_monitor",
  description:"Parking violation detection (dynamic)",
  evaluate_rules_path:"./use-cases/parking_safety/evaluate_rules.py",
  summarize:{ method:"SIMPLE", processor_kwargs:{ levels:1, level_sizes:[-1], process_fps:2 } },
  prompt_text:$pt,
  schema_extensions:[
    { name:"parking_zone", type:"text", required:false },
    { name:"motion_direction", type:"text", required:false }
  ],
  persist:true, overwrite:true
}')" | jq '.result.content[0].text | fromjson | {ok, steps}'
```

**加 monitor + 推真实素材**：

```bash
mkdir -p demo-videos/.run
ffmpeg -nostdin -re -stream_loop -1 -i demo-videos/cam_parking/false-parking.mp4 \
  -c copy -f rtsp -rtsp_transport tcp rtsp://localhost:8554/live/parking \
  </dev/null > demo-videos/.run/cam_parking.log 2>&1 &

mcp_call smartbuilding_monitor_ctl '{
  "action":"register_source",
  "monitor_id":"cam_parking",
  "source_url":"rtsp://localhost:8554/live/parking",
  "use_case":"parking_safety",
  "pipeline_config":{
    "motion":{"enabled":true,"diff_threshold":25},
    "prefilter":{"enabled":false},
    "recording":{"enabled":true,"interval_seconds":60},
    "segment":{"max_duration":10}
  }
}' | jq '.result.content[0].text | fromjson'
```

**正例验证**：alert 消息应带 `alertMessageExtraField` 拼接的 `(zone=…)`：

```bash
mcp_call smartbuilding_alert_query '{"monitor_id":"cam_parking","action":"latest","limit":1}' \
  | jq -r '.result.content[0].text'
# 期望类似 [parking_safety] fire_lane_parking: critical — ... (zone=fire_lane)
```

**反例验证 `excludeZones` 短路**（给 rules 补 `excludeZones` 重注册，再手塞一条 handicapped task dry-run）：

```bash
# 1) 给 parking_safety 的 rules 增补 excludeZones=[handicapped] 后重注册（overwrite 覆盖内存 + 写回 config）
#    传完整 entry，避免 overwrite 丢字段
PROMPT_TEXT=$(cat use-cases/parking_safety/prompt.md)
mcp_call smartbuilding_use_case_register "$(jq -n --arg pt "$PROMPT_TEXT" '{
  action:"register",
  use_case:"parking_safety",
  video_summary_task:"parking_safety_monitor",
  description:"Parking violation detection (dynamic)",
    evaluate_rules_path:"./use-cases/parking_safety/evaluate_rules.py",
  summarize:{ method:"SIMPLE", processor_kwargs:{ levels:1, level_sizes:[-1], process_fps:2 } },
  prompt_text:$pt,
  schema_extensions:[
    { name:"parking_zone", type:"text", required:false },
    { name:"motion_direction", type:"text", required:false }
  ],
  persist:true, overwrite:true
}')" | jq '.result.content[0].text | fromjson | .steps.use_case_dict'

# 2) 手塞一条 handicapped 的 completed task
TASK_ID=$(python3 - <<'PY'
import sqlite3, os
con = sqlite3.connect(f"{os.environ['SMARTBUILDING_DATA_DIR']}/smartbuilding.db")
con.execute("""INSERT INTO video_summary_tasks
  (monitor_id, status, summary_text, event, severity, parking_zone, desc, created_at)
  VALUES ('cam_parking','completed',
          'SEVERITY: warn\nEVENT: handicapped_spot_parking\nDESC: pretend\nPARKING_ZONE: handicapped',
          'handicapped_spot_parking','warn','handicapped','pretend', datetime('now'))""")
con.commit()
print(con.execute("SELECT id FROM video_summary_tasks WHERE monitor_id='cam_parking' ORDER BY id DESC LIMIT 1").fetchone()[0])
PY
)
mcp_call smartbuilding_rule_eval "$(jq -n --argjson t "$TASK_ID" '{monitor_id:"cam_parking",task_id:$t}')" \
  | jq '.result.content[0].text | fromjson | {rule_result}'
# 期望 rule_result.shouldAlert=false
# 清理：sqlite3 "$SMARTBUILDING_DATA_DIR/smartbuilding.db" "DELETE FROM video_summary_tasks WHERE id=$TASK_ID;"
```

#### 9.7.3 清场

与 §9.3 步骤 E 相同，只把 `pet_safety` / `cam_pet` 换成对应 use case / monitor：

```bash
mcp_call smartbuilding_monitor_ctl '{"action":"stop","monitor_id":"cam_high_altitude"}' \
  | jq '.result.content[0].text | fromjson'
mcp_call smartbuilding_use_case_register '{"action":"unregister","use_case":"high_altitude_safety","persist":true}' \
  | jq '.result.content[0].text | fromjson'
# parking_safety / cam_parking 同理
```

