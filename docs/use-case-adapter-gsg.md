# Use Case Adapter — Get Started Guide (Test Recipe)

本文档面向 use case adapter 的功能验证，给出一套完整可执行的测试步骤。use case adapter 包含三个可测层，本文按层逐个覆盖：

- **Prompt 层**：VLM 拿到 clip 后按 `LOCAL_PROMPT` 的规定输出结构化字段（`SEVERITY: / EVENT: / DESC: / …`）
- **Rules 层**：`evaluate_rules.py` 对 VLM 输出 + `payload.rules` 判定 Python override 协议 `{should_alert, alert_message}`；通过 MCP `smartbuilding_rule_eval` 查看时，对应字段为 `rule_result.shouldAlert` / `rule_result.alertMessage`
- **Cooldown 层**：`rules.cooldownSeconds` 抑制同 use case 短期重复告警

上游产品文档：[use-cases/README.md](../use-cases/README.md)、[docs/use-case-adapter.md](./use-case-adapter.md)、[docs/implements/schema-usecase-parser-alerts-pipeline.md](./implements/schema-usecase-parser-alerts-pipeline.md)。

---

## 0. 当前可跑的验证矩阵（基线）

本文档目前的**基线覆盖场景**——只包含 [demo-videos/](../demo-videos/) 里**已经有真实视频**、并且 [monitors.yaml.example](../monitors.yaml.example) 已配好 monitor 的 3 个内置 use case：

| 场景 | monitor | use case | 类型 | 使用视频 |
|---|---|---|---|---|
| Fridge | `cam_fridge` | `fridge` | 内置 stub | `cam_fridge/demo006-2_expanded_20min_v2.mp4` |
| Child Safety | `cam_child` | `child_safety` | 内置 override | `cam_child/child_safety_demo_expanded_1h.mp4` |
| Elder Wakeup Day 1 | `cam_elder_bedroom` | `elder_wakeup` | 内置 override | `cam_elder_bedroom/day1_elder_wakeup_expanded_20min.mp4` |
| Elder Wakeup Day 2 | `cam_elder_bedroom_2` | `elder_wakeup` | 内置 override | `cam_elder_bedroom_2/day2_elder_wakeup_expanded_20min.mp4` |

其他扩展场景（细分正/反例、自定义 use case `high_altitude_safety` / `parking_safety`）
放在 §9 "扩展验证"，跑之前需要**先自己生成对应视频 + 补 monitor 条目 + 注册 VLM task**——
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
- **VLM 端 dynamic task 必须先注册**：`child_safety_monitor` / `elder_wakeup_monitor` 不是 VLM 内置 task，MCP 启动前必须先按 [vlm-integration-gsg.md §3.2](./vlm-integration-gsg.md) 的一键脚本 POST `/v1/tasks` 注册进去，否则 `/v1/summary` 会返 400（详见 §8.5）

---

## 2. 基线用例矩阵

3 个内置 use case（fridge / child_safety / elder_wakeup），每个 use case 用**现有单条 demo 视频**能触发的 case 编号列表。要拆分成细粒度正/反例（CS-1..CS-4 等）看 §9.1。

### 2.1 `child_safety`（`severityThreshold=warn`）

用 [demo-videos/cam_child/child_safety_demo_expanded_1h.mp4](../demo-videos/cam_child/child_safety_demo_expanded_1h.mp4)（1 小时 loop）。视频包含多段儿童行为，VSA 会按 motion + 10s segment 切成多个 clip；期望其中 **critical（如攀爬 / 摔倒）clip → 触发 alert**，**info clip → 不触发**（rule 层 severity 短路）。

| ID | 视频行为片段 | Rule 期望 | 覆盖点 |
|----|-------------|----------|--------|
| **CS-baseline** | 视频 loop 中出现的 critical 片段 | ✅ 触发 `[child_safety] <event>: critical — ...` | severity ≥ warn fire |
| **CS-suppressed** | 视频 loop 中出现的 info 片段（安静玩耍） | ❌ 不触发 | severity 阈值短路 |

groundtruth 见 [cam_child/child_safety_demo_expanded_1h_groundtruth.srt](../demo-videos/cam_child/child_safety_demo_expanded_1h_groundtruth.srt)。

### 2.2 `elder_wakeup`（`expectedWakeupLocal=07:00, graceMinutes=30`）

用 [demo-videos/cam_elder_bedroom/day1_elder_wakeup_expanded_20min.mp4](../demo-videos/cam_elder_bedroom/day1_elder_wakeup_expanded_20min.mp4)
（20 分钟 loop，起床动作）+ [cam_elder_bedroom_2/day2_elder_wakeup_expanded_20min.mp4](../demo-videos/cam_elder_bedroom_2/day2_elder_wakeup_expanded_20min.mp4)（同一 use case，不同 monitor，验证 monitor-scoped cooldown）。

| ID | 视频行为片段 | Rule 期望 | 覆盖点 |
|----|-------------|-----------|--------|
| **EW-late** | `get_up` clip，实测时间已过 `expectedWakeupLocal + graceMinutes` | ✅ 触发 `late_wakeup` | 时间比较 + graceMinutes |
| **EW-ontime** | 同上 clip，实测时间在 grace 内 | ❌ 不触发 | grace period 边界 |
| **EW-still** | `still_in_bed` clip | ❌ 不触发 | event 名匹配 |
| **EW-day2** | 另一 monitor 的同 use case | ✅ 独立触发 & 独立 cooldown | 多 monitor 共享 use case |

groundtruth：[day1_elder_wakeup_groundtruth.srt](../demo-videos/cam_elder_bedroom/day1_elder_wakeup_groundtruth.srt) / [day2_elder_wakeup_groundtruth.srt](../demo-videos/cam_elder_bedroom_2/day2_elder_wakeup_groundtruth.srt)。

**关于时间比较**：`elder_wakeup/evaluate_rules.py` 用 `datetime.now()` 读实时。当前 MCP tool 里**没有** `smartbuilding_monitor_ctl update_pipeline` 这类热更新 action；要在任意时间测试 EW-late / EW-ontime，推荐直接修改 `config.yaml.example` 中 `use_case_dict.elder_wakeup.rules.expectedWakeupLocal` / `graceMinutes` 后重启 MCP。若后续需要注入测试时间，可单独扩展 override 去读取 `payload.rules.now_override_local`（本轮**不引入**）。

### 2.3 `fridge`（无告警）

用 [demo-videos/cam_fridge/demo006-2_expanded_20min_v2.mp4](../demo-videos/cam_fridge/demo006-2_expanded_20min_v2.mp4)（20 分钟 loop，取用/放置行为）。

| ID | 视频行为片段 | Rule 期望 | 覆盖点 |
|----|-------------|-----------|--------|
| **FR-normal** | 开冰箱取物 / 放置 | ❌ fridge stub 恒 false | stub 默认行为 |
| **FR-pretend-critical** | 手工 UPDATE DB 模拟 `severity=critical` | ❌ fridge stub 恒 false | **关键**：pin 住 stub 无论严重级别都不 fire |

groundtruth：[demo006-2_expanded_20min_v2_groundtruth.srt](../demo-videos/cam_fridge/demo006-2_expanded_20min_v2_groundtruth.srt)。

### 2.4 Cooldown（跨 use case 通用）

| ID | 操作 | 期望 |
|----|-----|-----|
| **CD-suppress** | 用 child_safety 视频里同一 critical clip 连续两次 rule_eval，间隔 < `rules.cooldownSeconds` | 第一次触发 alert，第二次 `suppressed_by_cooldown: true, alert_created: false` |
| **CD-recover** | 同上但间隔 > `cooldownSeconds` | 两次都触发 alert |

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
# 会依次 POST 以下 4 个（child_safety / elder_wakeup / high_altitude_safety / parking_safety）；
# 若你不打算跑 §9 的扩展 case，只 register 前两个也可以
for pair in \
    "child_safety:child_safety_monitor" \
    "elder_wakeup:elder_wakeup_monitor"; do
    ...
done

# 校验：应看到 6 builtin + 2 dynamic
curl -sf http://localhost:8192/v1/tasks | jq '.tasks[].name'
```

`fridge` 用内置 task `refrigerator_monitor_en`，不用注册。

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

---

## 4. VLM 输出校验前置

use case adapter 的 rule 层依赖 VLM 输出格式；正式测规则前先确认 prompt 有效。

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
  }" | python3 -m json.tool
```

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

## 5. 功能验证（U1 – U10，基线）

启动完 §3 之后，逐个 case 执行。

### U1. `child_safety`：critical 触发

`start-streams.sh` 已经把 `child_safety_demo_expanded_1h.mp4` loop 推到
`rtsp://localhost:8554/live/child`。等 20-40 秒让 VSA motion + prefilter 出第一个
带 person 的 clip，然后：

```bash
# 查最新 alert
curl -s -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
    "name":"smartbuilding_alert_query",
    "arguments":{"monitor_id":"cam_child","action":"latest","limit":1}}}' \
  | grep "^data:" | head -1 | sed 's/^data: //' | python3 -c "
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

### U7. `fridge`：stub 恒不触发

`cam_fridge` loop 推冰箱视频；期望 alerts 无新增。

对 FR-pretend-critical，用手工 UPDATE 模拟一条 critical 的 task，然后用 `smartbuilding_rule_eval` 触发：

```bash
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

# rule_eval dry-run（不 create_alert），验证 tool 返回的 rule_result.shouldAlert=false。
# 注意 -sS（不是 -sf）避免 error body 被吞；用 shell 变量替换 task_id，别用 <占位符>。
curl -sS -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{
    \"name\":\"smartbuilding_rule_eval\",
    \"arguments\":{\"monitor_id\":\"cam_fridge\",\"task_id\":${TASK_ID}}}}" \
  | grep "^data:" | head -1 | sed 's/^data: //' | jq '.result.content[0].text | fromjson'
```

期望响应含 `"rule_result": {"shouldAlert": false}` —— 这对应 `fridge/evaluate_rules.py` 的 no-alert stub；即使模拟出 `severity=critical` 也不会写 alert。

### U8. Cooldown：抑制第二次触发

先把 `config.yaml.example` 中 `use_case_dict.child_safety.rules.cooldownSeconds` 改为 `60`，然后重启 MCP。找到 loop 里同一 critical clip 的 task，连续两次跑 rule_eval：

```bash
curl -s -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
    "name":"smartbuilding_rule_eval",
    "arguments":{"monitor_id":"cam_child","task_id":<id>,"create_alert":true}}}'

# 立即第二次
curl -s -X POST http://localhost:3100/mcp ...同上... create_alert=true
```

期望：**只有 1 条** alert。第二次调用返回 `suppressed_by_cooldown: true, alert_created: false`。

### U9. Cooldown：过期恢复触发

将同一处 `cooldownSeconds=5`，重启；重复 U8 步骤但两次调用间隔 10 秒。期望两次都写入 alert。

### U10. rule_eval：dry-run vs create_alert=true

**目的**：验证 rule_eval 两种模式的语义。dry-run 只返回 evaluator 判定不写 DB；
create_alert=true 才落 alerts 表（同时走 cooldown 判定）。

```bash
export SMARTBUILDING_DATA_DIR="${SMARTBUILDING_DATA_DIR:-$HOME/.mcp-smartbuilding}"

# 1) 抓一条 critical task 并把 id 存进 shell 变量（不要用 <some_id> 占位符原样粘贴）
TASK_ID=$(sqlite3 "$SMARTBUILDING_DATA_DIR/smartbuilding.db" \
  "SELECT id FROM video_summary_tasks WHERE monitor_id='cam_child' AND severity='critical' AND status='completed' ORDER BY id DESC LIMIT 1;")
echo "TASK_ID=$TASK_ID"

# 2) 记录 U10 前 cam_child alerts 总数
BEFORE=$(sqlite3 "$SMARTBUILDING_DATA_DIR/smartbuilding.db" \
  "SELECT COUNT(*) FROM alerts WHERE monitor_id='cam_child';")
echo "alerts BEFORE = $BEFORE"

# 3) Dry-run —— 不传 create_alert
curl -sS -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{
    \"name\":\"smartbuilding_rule_eval\",
    \"arguments\":{\"monitor_id\":\"cam_child\",\"task_id\":${TASK_ID}}}}" \
  | grep "^data:" | head -1 | sed 's/^data: //' \
  | jq '.result.content[0].text | fromjson | {rule_result, alert_created, alert_id}'

# 4) 中间校验：alerts 总数没变
MID=$(sqlite3 "$SMARTBUILDING_DATA_DIR/smartbuilding.db" \
  "SELECT COUNT(*) FROM alerts WHERE monitor_id='cam_child';")
echo "alerts AFTER dry-run = $MID  (期望 = BEFORE = $BEFORE)"

# 5) create_alert=true —— 真写 alert（走 cooldown）
curl -sS -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{
    \"name\":\"smartbuilding_rule_eval\",
    \"arguments\":{\"monitor_id\":\"cam_child\",\"task_id\":${TASK_ID},\"create_alert\":true}}}" \
  | grep "^data:" | head -1 | sed 's/^data: //' \
  | jq '.result.content[0].text | fromjson | {rule_result, alert_created, alert_id, suppressed_by_cooldown}'

# 6) 最终校验：alerts +1（假设距上次同 UC alert 已过 cooldown；不然是 +0 且 suppressed_by_cooldown=true）
AFTER=$(sqlite3 "$SMARTBUILDING_DATA_DIR/smartbuilding.db" \
  "SELECT COUNT(*) FROM alerts WHERE monitor_id='cam_child';")
echo "alerts AFTER create_alert=true = $AFTER  (期望 = BEFORE + 1 = $((BEFORE+1)))"
```

**期望**：
- Dry-run 返回 `rule_result.shouldAlert=true, alert_created=null` → alerts 总数**不变**
- create_alert=true 返回 `alert_created=true, alert_id=<新 id>` → alerts 总数**+1**（若命中 cooldown 则 `alert_created=false, suppressed_by_cooldown=true`）

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
| U7 | fridge 恒不触发 | rule_eval 返回 `shouldAlert: false` 即使 severity=critical |
| U8 | cooldown 抑制 | 第二次 `suppressed_by_cooldown: true, alert_created: false`；alerts 只 +1 |
| U9 | cooldown 过期 | 两次都 +1 |
| U10 | rule_eval | dry-run 只返回 evaluator 结果不写 DB；create_alert=true 时写 DB 并走 cooldown |

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

---

## 9. 扩展验证 — 想验更全的 case / 自定义 use case

本节收集**不在基线里、但对完整验证 use case adapter 功能有价值**的 case。
跑之前需要**自己动手**：生成新视频、补 monitor 条目、注册 VLM task。

### 9.1 细分正/反例（同 use case，多视频）

现有 loop 视频靠"loop 内自然出现的多种片段"来覆盖正/反例，不够精细。想要一个
clip 对应一个明确期望时，按下面矩阵各自生成一条 **10 秒** 视频。

#### `child_safety` 细分

| ID | 视频内容 | VLM 期望输出 | Rule 期望 |
|----|---------|--------------|-----------|
| **CS-1** | 儿童攀爬窗台 / 书架 | `SEVERITY: critical, EVENT: child_climb, DESC: ...` | ✅ 触发 `[child_safety] child_climb: critical — ...` |
| **CS-2** | 儿童摔倒 | `SEVERITY: critical, EVENT: child_fall, DESC: ...` | ✅ 触发 |
| **CS-3** | 儿童安静玩玩具 | `SEVERITY: info, EVENT: child_play, DESC: ...` | ❌ 不触发（info 短路） |
| **CS-4** | 空客厅（有轻微光影变化） | Prefilter SKIP → clip 被删 | ❌ webhook 无事件 |

#### `elder_wakeup` 细分

| ID | 视频内容 | VLM 期望输出 | Rule 期望 |
|----|---------|--------------|-----------|
| **EW-1** | 老人从床上坐起、下床（送 VLM 时机在本地 08:00 之后） | `EVENT: get_up, WAKEUP_TIME: 25.5, DESC: ...` | ✅ 触发 `late_wakeup` |
| **EW-2** | 同上（送 VLM 时机在 07:15，grace 之内） | `EVENT: get_up, WAKEUP_TIME: 15.0, DESC: ...` | ❌ 不触发 |
| **EW-3** | 老人仍躺在床上未起 | `EVENT: still_in_bed, DESC: ...` | ❌ 不触发 |
| **EW-4** | 早晨空卧室 / 家人短暂经过 | Prefilter SKIP 或 `EVENT: unknown` | ❌ 不触发 |

### 9.2 自定义 use case（验证 adapter 扩展点）

后 2 个 use case 是**用来验证 use case adapter 的 design 能不能被外部用户使用**——
它们完全遵循 [use-case-adapter.md §3](./use-case-adapter.md) 的"Adding a new use case"
流程添加（新目录 + prompt.md + evaluate_rules.py + config.yaml.example 加条目 +
`schema.video_summary_tasks.extensions` 加字段），不改任何 core 代码。跑通即证明
design 是自足的。

需要新建的 monitor（**目前 [monitors.yaml.example](../monitors.yaml.example) 里没有**，自己 append）：

```yaml
cam_high_altitude:
  enabled: true
  name: "High Altitude Safety Camera"
  source_url: rtsp://localhost:8554/live/high_altitude
  use_case: high_altitude_safety
  pipeline_config:
    motion: { enabled: true, diff_threshold: 25 }
    recording: { enabled: true, interval_seconds: 60 }
    segment: { max_duration: 10 }

cam_parking:
  enabled: true
  name: "Parking Safety Camera"
  source_url: rtsp://localhost:8554/live/parking
  use_case: parking_safety
  pipeline_config:
    motion: { enabled: true, diff_threshold: 25 }
    recording: { enabled: true, interval_seconds: 60 }
    segment: { max_duration: 10 }
```

同时在 [demo-videos/streams.yaml](../demo-videos/streams.yaml) `streams:` 下 append：

```yaml
cam_high_altitude:
  enabled: true
  file: cam_high_altitude/ha01_plastic_bag_throw.mp4    # 或你生成的合集视频
  rtsp_url: rtsp://localhost:8554/live/high_altitude
  loop: true

cam_parking:
  enabled: true
  file: cam_parking/ps01_fire_lane.mp4
  rtsp_url: rtsp://localhost:8554/live/parking
  loop: true
```

跑扩展 case 前的**先决条件清单**：

1. `config.yaml.example` 里有 `use_case_dict.high_altitude_safety` 和 `use_case_dict.parking_safety`（仓库当前 config.yaml.example 已含）
2. `schema.video_summary_tasks.extensions` 里声明了 `motion_direction` / `parking_zone`（当前已含）
3. `monitors.yaml.example` 里 append 上面 2 个 monitor
4. `demo-videos/streams.yaml` 里 append 上面 2 个 stream 并放视频进去
5. VLM 服务已把 `high_altitude_monitor` / `parking_safety_monitor` 两个 task 动态注册进去（用 [vlm-integration-gsg.md §3.2](./vlm-integration-gsg.md) 的一键脚本 —— 默认脚本就有这 2 个）
6. 用 MCP tool 校验：`smartbuilding_use_case_validate use_case=high_altitude_safety` 应返回 `checks.task_registered=true, schema_consistent=true`；parking_safety 同理

#### `high_altitude_safety`（验证 `rules.requireDirection`）

`rules`（config.yaml.example，已含）：
```yaml
severityThreshold: warn
requireDirection: downward          # 只在 motion_direction=downward 时 fire
cooldownSeconds: 30
```

Schema 扩展列：`motion_direction`（`text`, `required: false`，已含）。

| ID | 视频内容 | VLM 期望输出 | Rule 期望 | 覆盖点 |
|----|---------|--------------|-----------|--------|
| **HA-1** | 从阳台向下丢塑料袋 / 瓶子 | `SEVERITY: critical, EVENT: high_altitude_throw, MOTION_DIRECTION: downward` | ✅ 触发 | 完整正例 |
| **HA-2** | 塑料袋从阳台飘落（速度慢）| 同 HA-1 —— prompt 明确"飘也算" | ✅ 触发 | prompt 边界 |
| **HA-3** | 鸟飞过 / 树叶飘落 | `SEVERITY: info, EVENT: no_incident, MOTION_DIRECTION: none` | ❌ 短路 | event 名过滤 |
| **HA-4** | 从楼下向上扔气球（motion_direction=upward）| `SEVERITY: critical, EVENT: high_altitude_throw, MOTION_DIRECTION: upward` | ❌ `requireDirection=downward` 抑制 | **关键**：`rules.requireDirection` 通过 payload.rules 生效 |
| **HA-5** | 画面模糊 | `SEVERITY: info, EVENT: uncertain` | ❌ 短路 | uncertain 处理 |

现有 [demo-videos/cam_ha_test/](../demo-videos/cam_ha_test/) 下已有 `building-throwing.mp4` / `building-throwing-2.mp4` 两个真实素材可以先做初步打样（相当于 HA-1 变体），细分反例仍需自己补 HA-3 / HA-4 / HA-5。

#### `parking_safety`（验证 `rules.excludeZones`）

`rules`（config.yaml.example）：
```yaml
severityThreshold: warn
cooldownSeconds: 600
# excludeZones: [normal, unknown]   # 可选：pin 住不告警的 zone
```

Schema 扩展列：`parking_zone`（`text`, `required: false`）。

| ID | 视频内容 | VLM 期望输出 | Rule 期望 | 覆盖点 |
|----|---------|--------------|-----------|--------|
| **PS-1** | 车停在消防通道 | `SEVERITY: critical, EVENT: fire_lane_parking, PARKING_ZONE: fire_lane` | ✅ `[parking_safety] fire_lane_parking: critical — ... (zone=fire_lane)` | zone 拼到 alert_message |
| **PS-2** | 车堵住小区门口 | `SEVERITY: critical, EVENT: entrance_blocking, PARKING_ZONE: entrance` | ✅ 触发 | 多种 event / zone 组合 |
| **PS-3** | 车正常停在划线车位 | `SEVERITY: info, EVENT: no_incident, PARKING_ZONE: normal` | ❌ 短路 | event 短路 |
| **PS-4** | 车占用无障碍位 + rules.excludeZones=[handicapped] | `SEVERITY: warn, EVENT: handicapped_spot_parking, PARKING_ZONE: handicapped` | ❌ excludeZones 抑制 | **关键**：`rules.excludeZones` 通过 payload.rules 生效 |

现有 [demo-videos/cam_parking/](../demo-videos/cam_parking/) 下已有 `false-parking.mp4`（可用于 PS-1 / PS-2 变体）；其余反例（PS-3 / PS-4）需自己补。

### 9.3 视频生成规范

用即梦 AI（或任何文生视频工具）生成的视频需满足以下技术参数，否则 VSA 会在 motion / prefilter 层前置过滤掉。

#### 硬性技术参数

| 参数 | 值 | 原因 |
|------|-----|------|
| 时长 | **10 s** | 与 VSA 默认 `segment.interval=10.0` 对齐，正好一个 clip |
| 分辨率 | **1280×720** 或 1920×1080 | prefilter 用的 YOLO 模型 `shape_static_1280x704`；越接近训练分辨率精度越高 |
| 帧率 | **15 fps**（不低于） | VSA 默认 `recording.fps=15`；再高也会被抽帧到 `detect_fps=2.0` |
| 编码 | **H.264 / mp4** | ffmpeg `-c copy` 可以零转码推 RTSP |
| 视角 | **固定摄像头**（无平移 / 变焦） | 模拟真实监控 |
| 光线 | **室内自然光 / 正常照度** | NPU YOLO 在暗光下召回率下降 |

#### 内容要求（分场景）

**child_safety / elder_wakeup（都需要 person 检测）**：
- 主体（person）在画面中出现 **≥ 2 秒**（`min_frames_hit=2 @ detect_fps=2Hz` = 1 秒理论上够，2 秒稳）
- person 面积 **占画面 ≥ 5%**（motion 检测阈值 + YOLO 检测框最小尺寸）
- 主体动作要 **明显**（否则 motion detector 判静止）

**fridge**：
- 冰箱静态背景 + 明显的开门动作 or 手/物件进出
- 不强制 person 出现（VLM 会输出 info-severity 叙述）

**empty scene（CS-4 / EW-4）**：
- 空房间 + 轻微光影变化（窗帘飘动、光线轻微变化）—— 触发 motion 但 prefilter 无 person → 用于验证 prefilter 前置过滤

#### Prompt 模板

统一模板骨架（英文更稳定）：

```
[fixed camera view, 1280×720, 10 seconds, 15 fps, indoor natural lighting]

Scene: <场景描述>
Subject: <人物 / 物体主体描述>
Action: <明确的动作，持续 8 秒，位于画面中间偏 <方向>>
Camera: static tripod shot, no camera movement, no zoom, no pan
Style: realistic surveillance camera footage, no cinematic effects
```

**每个 case 的具体 prompt**：

| ID | Prompt 关键描述 |
|----|----------------|
| CS-1 | `Scene: home living room. Subject: a 5-year-old child climbing on a windowsill. Action: child slowly climbs from floor to sit on windowsill over 8 seconds.` |
| CS-2 | `Scene: home living room. Subject: a 5-year-old child running. Action: child runs across frame and trips, falling to the floor at the 5-second mark.` |
| CS-3 | `Scene: home living room. Subject: a 5-year-old child sitting on rug with toys. Action: child quietly plays with wooden blocks, calm movements.` |
| CS-4 | `Scene: empty home living room. Subject: none. Action: sunlight through window creates gentle shifting shadows on the floor. No people visible.` |
| EW-1 | `Scene: elderly bedroom, morning. Subject: an 80-year-old man on bed. Action: man slowly sits up in bed, swings legs off bedside, stands up and walks out of frame.` |
| EW-2 | 同 EW-1（视频可复用，测试时通过 rules 热更调整"晚起阈值"来区分） |
| EW-3 | `Scene: elderly bedroom, morning. Subject: an 80-year-old man on bed. Action: man remains lying in bed with eyes closed, minimal movement.` |
| EW-4 | `Scene: empty elderly bedroom. Subject: none. Action: dawn light gradually brightens the room.` |
| HA-1 | `Scene: residential building facade seen from below, daytime. Subject: a white plastic trash bag falling from a 5th-floor balcony. Action: bag falls downward from balcony, drifts slightly, hits ground within 6 seconds.` |
| HA-2 | `Scene: residential building facade, windy. Subject: a light plastic bag drifting from a balcony. Action: bag slowly drifts downward through the air, not straight fall.` |
| HA-3 | `Scene: residential building facade. Subject: a small bird flying horizontally, and a leaf falling from a tree branch. Action: bird flies across frame, leaf gently drifts down.` |
| HA-4 | `Scene: residential building facade seen from below. Subject: a person on ground level throwing a small balloon upward. Action: balloon rises up toward a balcony over 5 seconds.` |
| HA-5 | `Scene: heavy fog around a residential building. Subject: unclear moving object. Action: a blurry shape moves briefly in the frame.` |
| PS-1 | `Scene: apartment fire lane with painted yellow "消防通道" markings on the ground. Subject: a white sedan parked directly on the fire lane. Action: car remains stationary through the whole 10 seconds.` |
| PS-2 | `Scene: small community gate / building entrance. Subject: a black SUV parked blocking the entrance archway. Action: SUV is stationary, blocking the passage.` |
| PS-3 | `Scene: an apartment parking lot with clear white line markings. Subject: a red hatchback parked correctly within a marked parking slot. Action: car is stationary, aligned with the marked slot.` |
| PS-4 | `Scene: parking lot with a designated handicapped spot marked with a blue wheelchair icon on the ground. Subject: a black SUV parked in the handicapped spot without any wheelchair placard visible. Action: car remains stationary.` |

#### 文件命名与目录

统一放到仓库根目录下的 `demo-videos/`（推流脚本 `demo-videos/start-streams.sh` 也从这里读）：

```
demo-videos/
├── cam_child/                       # rtsp://localhost:8554/live/child
│   ├── child_safety_demo_expanded_1h.mp4      ← 已存在（基线用）
│   ├── cs01_child_climb.mp4                    ← 需自己生成
│   ├── cs02_child_fall.mp4
│   ├── cs03_child_play.mp4
│   └── cs04_empty_scene.mp4
├── cam_elder_bedroom/               # rtsp://localhost:8554/live/elder
│   ├── day1_elder_wakeup_expanded_20min.mp4   ← 已存在（基线用）
│   ├── ew01_late_getup.mp4
│   ├── ew03_still_in_bed.mp4
│   └── ew04_empty_bedroom.mp4
├── cam_elder_bedroom_2/             # rtsp://localhost:8554/live/elder2
│   └── day2_elder_wakeup_expanded_20min.mp4   ← 已存在（基线用）
├── cam_fridge/                      # rtsp://localhost:8554/live/fridge
│   └── demo006-2_expanded_20min_v2.mp4        ← 已存在（基线用）
├── cam_high_altitude/               # rtsp://localhost:8554/live/high_altitude
│   ├── ha01_plastic_bag_throw.mp4
│   ├── ha02_bag_drift.mp4
│   ├── ha03_bird_leaf.mp4
│   ├── ha04_balloon_upward.mp4
│   └── ha05_foggy.mp4
├── cam_ha_test/                     # 现有真实素材（可用于 HA-1 变体）
│   ├── building-throwing.mp4
│   └── building-throwing-2.mp4
└── cam_parking/                     # rtsp://localhost:8554/live/parking
    ├── false-parking.mp4                       ← 现有素材（PS-1/PS-2 变体）
    ├── ps01_fire_lane.mp4
    ├── ps02_block_entrance.mp4
    ├── ps03_normal_slot.mp4
    └── ps04_handicapped.mp4
```

> 目录按 `monitor_id` 组织，与 `demo-videos/streams.yaml` 保持一致。use case 归属由 `monitors.yaml.example` 中 monitor→use_case 的映射决定，不再单独按 use case 分目录。

**自定义 use case 视频挂载**：如果不走 VSA 全链路而直接对 VLM 打样（§4），
把视频 cp 到 `~/.mcp-smartbuilding/test-videos/<use_case>/` 下，然后用容器内
路径 `/data/test-videos/<use_case>/<file>.mp4` 传给 `/v1/summary`——详见
[vlm-integration-gsg.md §4](./vlm-integration-gsg.md)。

### 9.4 扩展 case 的执行步骤（对应 §5 的补充）

以下 U11 / U12 假设 §9.2 的先决条件都已就绪。

#### U11. `high_altitude_safety`（自定义 use case → 验证 adapter design）

覆盖 §9.2 的 HA-1 / HA-4 / HA-3 三档，验证 `rules.requireDirection` 通过
`payload.rules` 生效——**这是 adapter design 的核心扩展点**：核心代码不知道
`motion_direction` 是什么，`evaluate_rules.py` 从 `payload.rules.requireDirection`
读约束并对 `payload.fields.motion_direction` 判定。

```bash
# --- U11a: HA-1 正例（塑料袋 downward → critical + downward）---
ffmpeg -re -stream_loop -1 -i demo-videos/cam_high_altitude/ha01_plastic_bag_throw.mp4 \
  -c copy -f rtsp rtsp://localhost:8554/live/high_altitude &
sleep 20; kill %1

# 查最新 alert
curl -s -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
    "name":"smartbuilding_alert_query",
    "arguments":{"monitor_id":"cam_high_altitude","action":"latest","limit":1}}}' \
  | grep "^data:" | head -1 | sed 's/^data: //' | jq -r '.result.content[0].text'

# 期望 description 以 [high_altitude_safety] high_altitude_throw: critical — 开头

# 查扩展列是否被 parser 填了（motion_direction 尤其关键）
python3 - <<'PY'
import sqlite3, os
con = sqlite3.connect(f"{os.environ['SMARTBUILDING_DATA_DIR']}/smartbuilding.db")
for r in con.execute("""SELECT id, event, severity, motion_direction, desc
                        FROM video_summary_tasks
                        WHERE monitor_id='cam_high_altitude'
                        ORDER BY id DESC LIMIT 1"""):
    print(dict(zip(('id','event','severity','motion_direction','desc'), r)))
PY
# 期望：event=high_altitude_throw, motion_direction=downward
```

```bash
# --- U11b: HA-4 反例（气球向上 upward → 因 requireDirection=downward 抑制）---
ffmpeg -re -stream_loop -1 -i demo-videos/cam_high_altitude/ha04_balloon_upward.mp4 \
  -c copy -f rtsp rtsp://localhost:8554/live/high_altitude &
sleep 20; kill %1

# 期望：alerts 无新增；video_summary_tasks 里 motion_direction=upward，但 rule 层短路
```

**用 `smartbuilding_rule_eval` dry-run 定位是否真的因 `requireDirection` 短路**（VLM 输
出正确但 rule 判 false 时最好用这招）：

```bash
# 找到刚才 HA-4 的 task_id
TASK_ID=$(python3 -c "
import sqlite3, os
con = sqlite3.connect(f\"{os.environ['SMARTBUILDING_DATA_DIR']}/smartbuilding.db\")
r = con.execute(\"SELECT id FROM video_summary_tasks WHERE monitor_id='cam_high_altitude' ORDER BY id DESC LIMIT 1\").fetchone()
print(r[0])
")

curl -s -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{
    \"name\":\"smartbuilding_rule_eval\",
    \"arguments\":{\"monitor_id\":\"cam_high_altitude\",\"task_id\":${TASK_ID}}}}" \
  | grep "^data:" | head -1 | sed 's/^data: //' | jq '.result.content[0].text|fromjson'

# 期望：rule_result.shouldAlert=false, payload.rules 里 requireDirection=downward
```

#### U12. `parking_safety`（自定义 use case → 验证 adapter design）

覆盖 §9.2 的 PS-1（正例）+ PS-4（`excludeZones` 抑制）。重点验证：alert_message
带 `zone=fire_lane` 之类拼接、`excludeZones` 通过 `payload.rules` 生效。

```bash
# --- U12a: PS-1 消防通道 critical ---
ffmpeg -re -stream_loop -1 -i demo-videos/cam_parking/ps01_fire_lane.mp4 \
  -c copy -f rtsp rtsp://localhost:8554/live/parking &
sleep 20; kill %1

curl -s -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
    "name":"smartbuilding_alert_query",
    "arguments":{"monitor_id":"cam_parking","action":"latest","limit":1}}}' \
  | grep "^data:" | head -1 | sed 's/^data: //' | jq -r '.result.content[0].text'

# 期望 description：
# [parking_safety] fire_lane_parking: critical — ... (zone=fire_lane)
```

```bash
# --- U12b: PS-4 无障碍位 + excludeZones=[handicapped] 抑制 ---
# 先热改 config.yaml.example:
#   use_case_dict.parking_safety.rules.excludeZones: [handicapped]
# 然后重启 MCP
vim config.yaml.example
node packages/mcp-server/dist/index.js --http \
  --config config.yaml.example --monitors monitors.yaml.example &

# 推 ps04
ffmpeg -re -stream_loop -1 -i demo-videos/cam_parking/ps04_handicapped.mp4 \
  -c copy -f rtsp rtsp://localhost:8554/live/parking &
sleep 20; kill %1

# 期望：alerts 无新增；video_summary_tasks 里 parking_zone=handicapped, event=handicapped_spot_parking
```

**dry-run 验证 excludeZones 生效链路**：

```bash
TASK_ID=$(python3 -c "
import sqlite3, os
con = sqlite3.connect(f\"{os.environ['SMARTBUILDING_DATA_DIR']}/smartbuilding.db\")
r = con.execute(\"SELECT id FROM video_summary_tasks WHERE monitor_id='cam_parking' ORDER BY id DESC LIMIT 1\").fetchone()
print(r[0])
")

curl -s -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{
    \"name\":\"smartbuilding_rule_eval\",
    \"arguments\":{\"monitor_id\":\"cam_parking\",\"task_id\":${TASK_ID}}}}" \
  | grep "^data:" | head -1 | sed 's/^data: //' | jq '.result.content[0].text|fromjson | {payload_rules: .payload.rules, rule_result}'

# 期望：payload_rules.excludeZones=["handicapped"], rule_result.shouldAlert=false
```

### 9.5 扩展验收清单（对应 §6 的补充）

| # | 项目 | 期望 |
|---|-----|------|
| U11a | HA-1 → high_altitude_safety alert | `[high_altitude_safety] high_altitude_throw: critical — ...` 存在；`video_summary_tasks.motion_direction=downward` |
| U11b | HA-4 → requireDirection 短路 | alerts 无新增；`video_summary_tasks.motion_direction=upward`；rule_eval dry-run 返回 `shouldAlert=false` |
| U12a | PS-1 → parking_safety alert | description 以 `[parking_safety] fire_lane_parking: critical — ... (zone=fire_lane)` 结尾 |
| U12b | PS-4 → excludeZones 短路 | alerts 无新增；`video_summary_tasks.parking_zone=handicapped`；rule_eval dry-run 返回 `shouldAlert=false` 且 payload.rules.excludeZones=["handicapped"] |

---

## 10. 零重启动态注册新 use case

### 10.1 背景

MCP server 启动时把 `config.yaml` 的 `use_case_dict` 一次性快照到 `ServerConfig.useCaseDict`
（详见 [packages/mcp-server/src/config.ts:180](../packages/mcp-server/src/config.ts#L180)），
然后**按引用**传给所有 tool handler、[task-poller.ts:76](../packages/mcp-server/src/video-worker/task-poller.ts#L76)、
`WorkerService`。这意味着：

- 修改 `config.yaml` 后**不重启就不生效**
- 但**运行时直接 mutate `config.useCaseDict[name] = entry`** 会立即被所有下游看到（task-poller 每次 poll 都新读 `this.config.useCaseDict[useCase]`，不是启动时快照）
- 同样：`schema.video_summary_tasks.extensions` 底层是通过 `PRAGMA table_info` + `ALTER TABLE ADD COLUMN` 幂等应用（[schema-manager.ts:92](../packages/db/src/schema-manager.ts#L92)），运行时再次调用 `applySchema` 安全
- VLM `/v1/tasks` 本来就热更新（`POST` / `PATCH` / `DELETE`，state 持久化到容器内 `~/.cache/.multilevel-video-understanding/tasks/`）

基于这三点，`smartbuilding_use_case_register` 这个 MCP tool 把三层的操作打包成一步。

### 10.2 `smartbuilding_use_case_register` 工作原理

`action=register` 内部按顺序执行 4 步：

1. **Schema 扩展**：如果传了 `schema_extensions=[{name, type, required}, ...]`，对 `video_summary_tasks` 表跑 `ALTER TABLE ADD COLUMN`（列已存在则跳过），同时把这些扩展 merge 到 `config.schema.video_summary_tasks.extensions` 内存副本里，保证后续 `use_case_validate` 的 required-field 检查能看到
2. **VLM task 注册**：如果传了 `prompt_text`，POST `/v1/tasks`；收到 `409 Conflict` 时自动 PATCH。`prompt_text` 支持两种格式：
   - Markdown 带 `## LOCAL_PROMPT` / `## GLOBAL_PROMPT` 段（同 [use-cases/<uc>/prompt.md](../use-cases/) 文件格式）—— tool 会自动拼装成 4 常量 Python 源码
   - 已经拼好的 4 常量源码（含 `GLOBAL_PROMPT = '''...'''` 字样）—— 原样透传
3. **注入内存 `use_case_dict`**：把 `{video_summary_task, description, evaluate_rules_path, rules, ...}` 组成的 entry `config.useCaseDict[use_case] = entry`；task-poller 下一轮 poll 就能读到
4. **调 `use_case_validate` 复核**：把三步的效果串起来检查一次，结果放在 `steps.validate` 里返回

`action=unregister`：DELETE `/v1/tasks/<name>` + `delete config.useCaseDict[name]`。schema 扩展列**不回滚**（sqlite 没法 drop column 而不破坏数据）。

### 10.3 零重启操作步骤（`pet_safety` 完整例子）

假设已经在跑 §3 那套三服务（VSA / VLM / MCP），且没重启 MCP。以下所有步骤对已在跑的
`cam_fridge` / `cam_child` / `cam_elder_bedroom(*)` 都无影响。

#### 步骤 A — 写 evaluate_rules.py 和 prompt.md（磁盘上）

```bash
cd /home/user/jie/smarthome/smart-community
mkdir -p use-cases/pet_safety

cat > use-cases/pet_safety/prompt.md <<'EOF'
## LOCAL_PROMPT

You are a home pet-safety camera. Watch the 10-second clip and output EXACTLY these fields:

SEVERITY: critical | warn | info
EVENT: <one of: pet_stuck, pet_escape, pet_normal, no_incident>
DESC: <one sentence>
PET_ZONE: <one of: cage, sofa, floor, door, unknown>

Rules:
- pet_stuck = animal trapped / immobile in unnatural position → critical
- pet_escape = animal reaching for door/window in a way suggesting escape → warn
- pet_normal = resting / playing / eating → info
- no visible pet = no_incident, info
EOF

cat > use-cases/pet_safety/evaluate_rules.py <<'EOF'
import sys, json

def main():
    ctx = json.load(sys.stdin)
    fields = (ctx.get("fields") or {})
    event = fields.get("event", "")
    severity = fields.get("severity", "info")
    desc = fields.get("desc", "")
    zone = fields.get("pet_zone", "unknown")

    rules = (ctx.get("payload", {}).get("rules") or {})
    threshold = rules.get("severityThreshold", "warn")
    order = {"info": 0, "warn": 1, "critical": 2}

    if event == "no_incident":
        print(json.dumps({"should_alert": False})); return
    if order.get(severity, 0) < order.get(threshold, 1):
        print(json.dumps({"should_alert": False})); return

    msg = f"[pet_safety] {event}: {severity} — {desc} (zone={zone})"
    print(json.dumps({"should_alert": True, "alert_message": msg}))

if __name__ == "__main__":
    main()
EOF
```

**期望输出**：两个文件被创建，`ls use-cases/pet_safety/` 显示 `evaluate_rules.py  prompt.md`。

#### 步骤 B — 调 `smartbuilding_use_case_register` 一步搞定

用 `jq` 组装参数并 POST：

```bash
PROMPT_TEXT=$(cat use-cases/pet_safety/prompt.md)

jq -n \
  --arg pt "$PROMPT_TEXT" \
  --arg erp "$(pwd)/use-cases/pet_safety/evaluate_rules.py" \
  '{
    jsonrpc: "2.0", id: 1, method: "tools/call",
    params: {
      name: "smartbuilding_use_case_register",
      arguments: {
        action: "register",
        use_case: "pet_safety",
        video_summary_task: "pet_safety_monitor",
        description: "Pet safety monitoring (dynamic)",
        evaluate_rules_path: $erp,
        rules: { severityThreshold: "warn", cooldownSeconds: 300 },
        reports: { data_source: "alerts", default_type: "daily", filter: {} },
        prompt_text: $pt,
        schema_extensions: [
          { name: "pet_zone", type: "text", required: false }
        ]
      }
    }
  }' | curl -s -X POST http://localhost:3100/mcp \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        --data-binary @- \
     | grep "^data:" | head -1 | sed 's/^data: //' | jq '.result.content[0].text | fromjson'
```

**期望输出**（关键字段）：

```json
{
  "action": "register",
  "use_case": "pet_safety",
  "ok": true,
  "steps": {
    "schema": { "added": ["video_summary_tasks.pet_zone"], "warnings": [] },
    "vlm_task": "registered",
    "use_case_dict": "added",
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

#### 步骤 C — 加 monitor 并让它开始跑

现有 MCP 依然在跑，直接调 `smartbuilding_monitor_ctl register_source`——它内部会跑
`use_case_validate`（此时 `use_case_dict` 里已经有 `pet_safety`，validate 通过）：

```bash
# 先把宠物视频推到 mediamtx（生成一个新 stream path）
# 这里假设你已经准备了 demo-videos/cam_pet/pet_demo.mp4
ffmpeg -re -stream_loop -1 -i demo-videos/cam_pet/pet_demo.mp4 \
  -c copy -f rtsp -rtsp_transport tcp rtsp://localhost:8554/live/pet &

# 用 MCP tool 添加 monitor
curl -s -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
    "name":"smartbuilding_monitor_ctl",
    "arguments":{
      "action":"register_source",
      "monitor_id":"cam_pet",
      "source_url":"rtsp://localhost:8554/live/pet",
      "use_case":"pet_safety",
      "pipeline_config":{
        "motion":{"enabled":true,"diff_threshold":25},
        "recording":{"enabled":true,"interval_seconds":60},
        "segment":{"max_duration":10}
      }
    }}}' | grep "^data:" | head -1 | sed 's/^data: //' | jq '.result.content[0].text | fromjson'
```

**期望输出**：`{ ok: true, monitor_id: "cam_pet", status: "online", ... }`。

约 20-40 秒后应能在 `alerts` 表 / `smartbuilding_alert_query` 里看到 pet_safety 的告警
（如果视频里有 critical 事件）。

#### 步骤 D — 反向操作：unregister

```bash
# 先停 monitor（不 unregister 掉，只是 stop 或 unregister_source）
curl -s -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
    "name":"smartbuilding_monitor_ctl",
    "arguments":{"action":"unregister","monitor_id":"cam_pet"}}}'

# 再 unregister use case
curl -s -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
    "name":"smartbuilding_use_case_register",
    "arguments":{"action":"unregister","use_case":"pet_safety"}}}' \
  | grep "^data:" | head -1 | sed 's/^data: //' | jq '.result.content[0].text | fromjson'
```

**期望输出**：

```json
{
  "action": "unregister",
  "use_case": "pet_safety",
  "ok": true,
  "steps": {
    "vlm_task": "deleted",
    "use_case_dict": "removed"
  },
  "warnings": [],
  "errors": []
}
```

### 10.4 已知限制（重启后会不会消失）

| 层 | 重启后是否保留 |
|---|---|
| VLM `/v1/tasks/<name>` | ✅ 保留（写入容器 `~/.cache/.multilevel-video-understanding/tasks/`）|
| DB schema 扩展列 | ✅ 保留（`ALTER TABLE` 已落盘）|
| `config.useCaseDict[<name>]` | ❌ **丢失**（内存 only）|
| Monitor（通过 monitor_ctl register_source 加的） | ✅ 保留（写入 SQLite `monitors` 表）|

所以**重启后你会看到**：数据库里 `cam_pet` 还在、VLM task 还在、schema 列还在，
但 MCP 会因为找不到 `pet_safety` use case 而抛
`monitors reference unknown use_case keys` 并退出（[index.ts:64-68](../packages/mcp-server/src/index.ts#L64-L68)）。

**修复方式**（二选一）：
- **推荐**：在 `config.yaml.example` 里加上 `use_case_dict.pet_safety` 条目，让下次启动能读到。这是当前推荐的"补 config、下次启动可继续"的做法
- **临时**：先 unregister monitor（`cam_pet`），再重启 MCP，之后再 register_use_case + register_source

后续 P3：给 tool 加一个 `persist: true` 参数，把 use_case 序列化写回 `config.yaml.example`，实现"真正的一次调用永久生效"。当前实现不做这一步，避免运行时改写用户配置文件带来的破坏性风险。

### 10.5 关联 tool 一览

| Tool | 什么时候用 |
|---|---|
| `smartbuilding_use_case_register` | 新加 use case（本节主角）|
| `smartbuilding_use_case_validate` | 校验现有 use case 的三层（存在 / VLM task 注册 / prompt schema）|
| `smartbuilding_monitor_ctl` | 加/减 monitor；用 `action=register_source` 时 tool 内部自动跑 use_case_validate |
| `smartbuilding_monitors_compose` | 批量按 `monitors.yaml` 起 monitor |
| `smartbuilding_rule_eval` | dry-run 一个 completed task 看 rule 层判定，不写 DB |

