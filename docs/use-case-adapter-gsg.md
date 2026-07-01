# Use Case Adapter — Get Started Guide (Test Recipe)

本文档面向 use case adapter 的功能验证，给出一套完整可执行的测试步骤。use case adapter 包含三个可测层，本文按层逐个覆盖：

- **Prompt 层**：VLM 拿到 clip 后按 `LOCAL_PROMPT` 的规定输出结构化字段（`SEVERITY: / EVENT: / DESC: / …`）
- **Rules 层**：`evaluate_rules.py` 对 VLM 输出 + `payload.rules` 判定 `{should_alert, alert_message}`
- **Cooldown 层**：`rules.cooldownSeconds` 抑制同 use case 短期重复告警

上游产品文档：[use-cases/README.md](../use-cases/README.md)、[docs/use-case-adapter.md](./use-case-adapter.md)、[docs/implements/schema-usecase-parser-alerts-pipeline.md](./implements/schema-usecase-parser-alerts-pipeline.md)。

---

## 1. 前提条件

| 依赖 | 说明 |
|---|---|
| Node.js ≥ 18 | 运行 MCP server (`packages/mcp-server`) |
| Python ≥ 3.10 | 运行 `evaluate_rules.py` override |
| ffmpeg | 视频推流 + 帧解码 |
| MediaMTX | 本地 RTSP server |
| Videostream Analytics 服务 | 见 [vsa-gsg.md](./vsa-gsg.md) 启动 |
| VLM 服务（`multilevel-video-understanding`）| 处理 clip 并返回 `summary_text` |
| 测试视频 | 见 §3 视频生成规范 |

**运行时环境变量**：

```bash
export SMARTBUILDING_DATA_DIR=/tmp/mcp-uc-test   # 独立测试目录，验证完可 rm -rf
```

---

## 2. 用例矩阵

三个内置 use case 各自的测试案例。左列 ID 与 §3 视频命名对应。

### 2.1 `child_safety`（`severityThreshold=warn`）

| ID | 视频内容 | VLM 期望输出 | Rule 期望 | 覆盖点 |
|----|---------|--------------|-----------|--------|
| **CS-1** | 儿童攀爬窗台 / 书架 | `SEVERITY: critical, EVENT: child_climb, DESC: ...` | ✅ 触发 `[child_safety] child_climb: critical — ...` | rule 层 critical fire |
| **CS-2** | 儿童摔倒 | `SEVERITY: critical, EVENT: child_fall, DESC: ...` | ✅ 触发 | 多种 event 类型 |
| **CS-3** | 儿童安静玩玩具 | `SEVERITY: info, EVENT: child_play, DESC: ...` | ❌ 不触发（info 短路） | severity 阈值 |
| **CS-4** | 空客厅（有轻微光影变化） | Prefilter SKIP → clip 被删 | ❌ webhook 无事件 | prefilter 前置过滤 |

### 2.2 `elder_wakeup`（`expectedWakeupLocal=07:00, graceMinutes=30`）

| ID | 视频内容 | VLM 期望输出 | Rule 期望 | 覆盖点 |
|----|---------|--------------|-----------|--------|
| **EW-1** | 老人从床上坐起、下床 —— 送 VLM 时机在 **本地 08:00 之后** | `EVENT: get_up, WAKEUP_TIME: 25.5, DESC: ...` | ✅ 触发 `late_wakeup` | 时间比较 + graceMinutes |
| **EW-2** | 同上 —— 送 VLM 时机在 **07:15**（grace 之内） | `EVENT: get_up, WAKEUP_TIME: 15.0, DESC: ...` | ❌ 不触发 | grace period 边界 |
| **EW-3** | 老人仍躺在床上未起 | `EVENT: still_in_bed, DESC: ...` | ❌ 不触发 | event 名匹配 |
| **EW-4** | 早晨空卧室 / 家人短暂经过 | Prefilter SKIP 或 `EVENT: unknown` | ❌ 不触发 | 短路 |

**关于时间比较**：`elder_wakeup/evaluate_rules.py` 用 `datetime.now()` 读实时。要在任意时间测试 EW-1 / EW-2，用以下**任一**方式：

- **方式 A（推荐）**：`smartbuilding_rule_eval` 手动调用时用 `PUT /sources/{id}/pipeline` 热更 `rules.expectedWakeupLocal="00:00"` / `"23:59"` 来"模拟"晚起 / 不晚起
- **方式 B**：改 override 脚本，读 `payload.rules.now_override_local`（HH:MM）作为测试注入点（本轮**不引入**，只在文档提示）

### 2.3 `fridge`（无告警）

| ID | 视频内容 | VLM 期望输出 | Rule 期望 | 覆盖点 |
|----|---------|--------------|-----------|--------|
| **FR-1** | 开冰箱取牛奶 / 放菜 | `SEVERITY: info` + 叙述式 desc | ❌ fridge stub 恒 false | stub 默认行为 |
| **FR-2** | （构造性）VLM 输出 `SEVERITY: critical`（可用手工 UPDATE DB 模拟） | `SEVERITY: critical, EVENT: food_critical, DESC: ...` | ❌ fridge stub 恒 false | **关键**：pin 住 stub 无论严重级别都不 fire |

### 2.4 Cooldown（跨 use case 通用）

| ID | 操作 | 期望 |
|----|-----|-----|
| **CD-1** | 用 CS-1 视频推两次，间隔 < `rules.cooldownSeconds` | 第一次触发 alert，第二次 `suppressed_by_cooldown: true, alert_created: false` |
| **CD-2** | 同上但间隔 > `cooldownSeconds` | 两次都触发 alert |

---

## 3. 测试视频生成规范

用即梦 AI（或任何文生视频工具）生成的视频需满足以下技术参数，否则 VSA 会在 motion / prefilter 层前置过滤掉。

### 3.1 硬性技术参数

| 参数 | 值 | 原因 |
|------|-----|------|
| 时长 | **10 s** | 与 VSA 默认 `segment.interval=10.0` 对齐，正好一个 clip |
| 分辨率 | **1280×720** 或 1920×1080 | prefilter 用的 YOLO 模型 `shape_static_1280x704`；越接近训练分辨率精度越高 |
| 帧率 | **15 fps**（不低于） | VSA 默认 `recording.fps=15`；再高也会被抽帧到 `detect_fps=2.0` |
| 编码 | **H.264 / mp4** | ffmpeg `-c copy` 可以零转码推 RTSP |
| 视角 | **固定摄像头**（无平移 / 变焦） | 模拟真实监控 |
| 光线 | **室内自然光 / 正常照度** | NPU YOLO 在暗光下召回率下降 |

### 3.2 内容要求（分场景）

**child_safety / elder_wakeup（都需要 person 检测）**：
- 主体（person）在画面中出现 **≥ 2 秒**（`min_frames_hit=2 @ detect_fps=2Hz` = 1 秒理论上够，2 秒稳）
- person 面积 **占画面 ≥ 5%**（motion 检测阈值 + YOLO 检测框最小尺寸）
- 主体动作要 **明显**（否则 motion detector 判静止）

**fridge**：
- 冰箱静态背景 + 明显的开门动作 or 手/物件进出
- 不强制 person 出现（VLM 会输出 info-severity 叙述）

**empty scene（CS-4 / EW-4）**：
- 空房间 + 轻微光影变化（窗帘飘动、光线轻微变化）—— 触发 motion 但 prefilter 无 person → 用于验证 prefilter 前置过滤

### 3.3 即梦 AI Prompt 模板

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
| FR-1 | `Scene: kitchen with refrigerator. Subject: a hand opening refrigerator door. Action: hand opens door, reaches in and takes out a milk carton, closes door.` |
| FR-2 | 同 FR-1（用 DB 手工构造模拟 critical severity） |

### 3.4 文件命名与目录

```
tests/videos/use_cases/
├── child_safety/
│   ├── cs01_child_climb.mp4
│   ├── cs02_child_fall.mp4
│   ├── cs03_child_play.mp4
│   └── cs04_empty_scene.mp4
├── elder_wakeup/
│   ├── ew01_late_getup.mp4
│   ├── ew02_ontime_getup.mp4       # 可与 ew01 复用
│   ├── ew03_still_in_bed.mp4
│   └── ew04_empty_bedroom.mp4
└── fridge/
    ├── fr01_normal_open.mp4
    └── fr02_pretend_critical.mp4    # 可与 fr01 复用
```

---

## 4. 准备：启动支撑服务（4 个终端）

**T1 — MediaMTX**

```bash
~/.local/bin/mediamtx /path/to/mediamtx.yml
```

启动日志包含 `[RTSP] listener opened on :8554`。

**T2 — Videostream Analytics 服务**

```bash
cd videostream-analytics && source .venv/bin/activate
WEBHOOK_URL=http://localhost:3101/events \
  .venv/bin/videostream-analytics serve --config config/config.yaml
```

启动日志：`Uvicorn running on http://0.0.0.0:8999`。

**T3 — MCP server（含 use case adapter 装载）**

```bash
cd smart-community
export SMARTBUILDING_DATA_DIR=/tmp/mcp-uc-test
rm -rf $SMARTBUILDING_DATA_DIR

# 建立最简 monitors.yaml（三个 use case 各一个 monitor）
cat > /tmp/monitors-uc-test.yaml <<'EOF'
monitors:
  cam_child_uc:
    enabled: true
    name: "child_safety test cam"
    source_url: "rtsp://localhost:8554/live/child_uc"
    use_case: child_safety
  cam_elder_uc:
    enabled: true
    name: "elder_wakeup test cam"
    source_url: "rtsp://localhost:8554/live/elder_uc"
    use_case: elder_wakeup
  cam_fridge_uc:
    enabled: true
    name: "fridge test cam"
    source_url: "rtsp://localhost:8554/live/fridge_uc"
    use_case: fridge
EOF

node packages/mcp-server/dist/index.js \
  --config config.yaml.example \
  --monitors /tmp/monitors-uc-test.yaml \
  --http
```

启动日志包含：
- `[mcp-server] Streamable HTTP on http://localhost:3100/mcp`
- `[events-endpoint] Listening on port 3101`
- `[auto-register] cam_child_uc registered`（对 videostream-analytics 完成注册）

**T4 — ffmpeg 推流（每个 case 执行一次）**

```bash
# 推 CS-1
ffmpeg -re -stream_loop -1 -i tests/videos/use_cases/child_safety/cs01_child_climb.mp4 \
  -c copy -f rtsp rtsp://localhost:8554/live/child_uc
```

单个视频只需推流一遍（10 秒 loop 一次），VSA motion 检测触发后自动切段 emit 事件，随后可以 kill 掉 ffmpeg 换下一个视频。

---

## 5. VLM 输出校验前置

use case adapter 的 rule 层依赖 VLM 输出格式；正式测规则前先确认 prompt 有效。

```bash
# 直接对 VLM 服务打样，看它对 cs01 的 clip 输出什么
curl -sf -X POST http://localhost:8192/v1/summary \
  -H "Content-Type: application/json" \
  -d '{
    "video_url": "file:///abs/path/to/cs01_child_climb.mp4",
    "task": "child_safety_monitor"
  }' | python3 -m json.tool
```

期望 `summary_text` 包含（大小写不敏感）：

- `SEVERITY: critical | warn | info`
- `EVENT: <event 名>`
- `DESC: <一句话描述>`

若字段缺失，说明 prompt 与 schema 不匹配 —— 用 [use-case-adapter.md §3.2](./use-case-adapter.md) 的 `smartbuilding_use_case_validate` 定位问题。

---

## 6. 功能验证（U1 – U10）

启动 T1–T3 后，逐个 case 执行。

### U1. `child_safety`：critical 触发（CS-1）

```bash
# 推 cs01
ffmpeg -re -stream_loop -1 -i tests/videos/use_cases/child_safety/cs01_child_climb.mp4 \
  -c copy -f rtsp rtsp://localhost:8554/live/child_uc &
FFMPEG_PID=$!

# 等 20s 让 clip 触发 + VLM 完成
sleep 20
kill $FFMPEG_PID

# 查 alerts 表
curl -s -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
    "name":"smartbuilding_alert_query",
    "arguments":{"monitor_id":"cam_child_uc","action":"latest","limit":1}}}' \
  | grep "^data:" | head -1 | sed 's/^data: //' | python3 -c "
import json, sys
d = json.load(sys.stdin)
for c in d.get('result',{}).get('content',[]):
    if c.get('type')=='text': print(c['text'])
"
```

期望：一条 alert，`description` 以 `[child_safety] child_climb: critical —` 开头。

### U2. `child_safety`：info 短路（CS-3）

```bash
ffmpeg ... cs03_child_play.mp4 ... &
sleep 20; kill %1

# alerts 数量应该无新增
curl -s -X POST http://localhost:3100/mcp ... alert_query action=stats
```

期望：`total` 数没有增加。同时可以用 `smartbuilding_video_db` 查 `video_summary_tasks` 最新行确认 `severity=info`（VLM 有输出，rule 层短路）。

### U3. `child_safety`：Prefilter 前置过滤（CS-4）

推 CS-4 空场景视频；期望 VSA `motion_events/<date>/*.mp4` 目录**无新文件**（prefilter SKIP 直接删了），或事件级别不出 `motion` webhook。

**校验**：

```bash
# 查 events 表（motion 事件）
python3 -c "
import sqlite3
con = sqlite3.connect('$SMARTBUILDING_DATA_DIR/smartbuilding.db')
for r in con.execute('SELECT id, monitor_id, motion_type FROM events ORDER BY id DESC LIMIT 5'):
    print(dict(zip(('id','monitor_id','motion_type'), r)))
"
```

期望：`cam_child_uc` 无新 events（因为 prefilter 层直接删除了 motion clip）。

### U4. `elder_wakeup`：late_wakeup 触发（EW-1）

**先通过 PUT 热更 rules，让"当前时间"必然被判"晚起"**：

```bash
curl -s -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
    "name":"smartbuilding_monitor_ctl",
    "arguments":{"action":"update_pipeline","monitor_id":"cam_elder_uc",
                 "pipeline":{"...":"..."}}}}'
# 或者临时改 config.yaml.example 里 elder_wakeup.rules.expectedWakeupLocal="00:00" + graceMinutes=0，重启 MCP
```

（用直接改 config + 重启 MCP 更简单：`expectedWakeupLocal="00:00", graceMinutes=0` 让任意时间都算晚起。）

推 ew01，查 alerts：期望有 `[elder_wakeup] late_wakeup: warn —` 一条。

### U5. `elder_wakeup`：on_time 不触发（EW-2）

**热改 rules**：`expectedWakeupLocal="23:59", graceMinutes=59` 让任何时间都在 grace 内，重启 MCP。

推 ew01（同一视频），期望 alerts 无新增。

### U6. `elder_wakeup`：event 短路（EW-3）

推 ew03；VLM 应输出 `EVENT: still_in_bed`。alerts 无新增（override 里 `event != get_up` 直接 return）。

### U7. `fridge`：stub 恒不触发（FR-1 + FR-2）

推 fr01；期望 alerts 无新增。

对 FR-2，用手工 UPDATE 模拟一条 critical 的 task，然后用 `smartbuilding_rule_eval` 触发：

```bash
# 手工构造 completed task（假装 VLM 输出了 critical）
python3 - <<'PY'
import sqlite3, os
con = sqlite3.connect(f"{os.environ['SMARTBUILDING_DATA_DIR']}/smartbuilding.db")
con.execute("""INSERT INTO video_summary_tasks
    (monitor_id, event_id, status, summary_text, event, severity, desc, created_at)
    VALUES ('cam_fridge_uc', NULL, 'completed',
            'SEVERITY: critical\nEVENT: food_critical\nDESC: pretend',
            'food_critical', 'critical', 'pretend', datetime('now'))""")
con.commit()
row = con.execute("SELECT id FROM video_summary_tasks WHERE monitor_id='cam_fridge_uc' ORDER BY id DESC LIMIT 1").fetchone()
print('task_id:', row[0])
PY

# rule_eval dry-run（不 create_alert），验证 stub 返回 should_alert=false
curl -s -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
    "name":"smartbuilding_rule_eval",
    "arguments":{"monitor_id":"cam_fridge_uc","task_id":<上面输出的 id>}}}' \
  | grep "^data:" | head -1 | sed 's/^data: //' | python3 -m json.tool
```

期望响应含 `"rule_result": {"shouldAlert": false}` —— pin 住 fridge stub 不受 VLM 输出严重度影响。

### U8. Cooldown：抑制第二次触发（CD-1）

先热改 `child_safety.rules.cooldownSeconds=60`，重启 MCP。

```bash
# 第一次推 cs01
ffmpeg ... cs01 ... &
sleep 20; kill %1

# 立即再推一次
ffmpeg ... cs01 ... &
sleep 20; kill %1

# 查 alerts count
curl ... alert_query action=stats
```

期望：**只有 1 条** alert（第二次被 cooldown 抑制）。VSA log / MCP log 里应能看到 `[task-poller] cooldown suppressed alert for cam_child_uc/child_safety` debug 行（需要 log level DEBUG）。

同样可以用 `smartbuilding_rule_eval create_alert=true` 直接看：第二次 call 返回 `suppressed_by_cooldown: true, alert_created: false`。

### U9. Cooldown：过期恢复触发（CD-2）

将 `cooldownSeconds=5`，重启；重复 U8 步骤但两次推流间隔 10 秒。期望两次都触发。

### U10. rule_eval：dry-run + 手工触发

```bash
# 查最近 completed task
python3 -c "
import sqlite3, os
con = sqlite3.connect(f\"{os.environ['SMARTBUILDING_DATA_DIR']}/smartbuilding.db\")
for r in con.execute(\"SELECT id, monitor_id, status FROM video_summary_tasks WHERE status='completed' ORDER BY id DESC LIMIT 3\"):
    print(r)
"

# dry-run: 不 create_alert
curl -s -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
    "name":"smartbuilding_rule_eval",
    "arguments":{"monitor_id":"cam_child_uc","task_id":<some_id>}}}'

# 手工触发一次（会走 cooldown）
curl -s -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{
    "name":"smartbuilding_rule_eval",
    "arguments":{"monitor_id":"cam_child_uc","task_id":<some_id>,"create_alert":true}}}'
```

---

## 7. 验收清单

| # | 项目 | 期望 |
|---|-----|------|
| U1 | CS-1 → child_safety alert | `[child_safety] child_climb: critical — ...` 存在 |
| U2 | CS-3 → info 短路 | alerts 无新增 |
| U3 | CS-4 → prefilter 拦截 | events 无 motion 行 |
| U4 | EW-1 → late_wakeup | `[elder_wakeup] late_wakeup: warn — ...` 存在 |
| U5 | EW-2 → grace 内 | alerts 无新增 |
| U6 | EW-3 → event 短路 | alerts 无新增 |
| U7 | FR-1 + FR-2 → fridge 恒不触发 | rule_eval 返回 `shouldAlert: false` 即使 severity=critical |
| U8 | CD-1 → cooldown 抑制 | 第二次 `suppressed_by_cooldown: true, alert_created: false`；alerts 只 +1 |
| U9 | CD-2 → cooldown 过期 | 两次都 +1 |
| U10 | rule_eval | dry-run 只返回 evaluator 结果不写 DB；create_alert=true 时写 DB 并走 cooldown |

---

## 8. 常见问题

### 8.1 VLM 输出格式与 prompt 期望不符

现象：alerts 表始终为空，即使 `severity` 应该 critical。

排查：
1. `smartbuilding_use_case_validate use_case=<uc>` 检查 `LOCAL_PROMPT` 是否包含 required 字段名
2. 直接 `curl POST /v1/summary` 打样 VLM（§5），确认返回文本里有 `SEVERITY:` / `EVENT:` / `DESC:`
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

### 8.2 elder_wakeup 时间比较不可控

override 用 `datetime.now()` 读实时。测试时用**热改 rules**（改 `expectedWakeupLocal` / `graceMinutes` 制造边界条件）+ 重启 MCP 覆盖。生产用途本身依赖真实时间，无需处理。

### 8.3 prefilter 把有效视频也 SKIP 了

原因：视频里 person 出现 < 2 秒 或 光线太暗。

排查：
1. 检查 VSA log 里 `Prefilter PASS` / `SKIP` 出现的次数
2. 视频重新生成，加长 person 停留 + 提高光照
3. 临时调小 `prefilter.min_frames_hit=1`（重启 MCP + VSA）

### 8.4 alerts 表迟迟没数据

按顺序排查：
1. VSA 是否发了 webhook？（查 VSA log 里 `Emitted motion`）
2. MCP `/events` 是否收到？（查 MCP log `[events-endpoint] received event`）
3. task 是否 completed？（`SELECT status FROM video_summary_tasks`）
4. rule engine 是否返回 shouldAlert=true？（用 `smartbuilding_rule_eval` dry-run 复现）

任一环节断，问题聚焦到那一层，往上游查。

---

## 9. 相关文档

- **契约层**：[apis/videostream_analytics_api.md](./apis/videostream_analytics_api.md)
- **VSA 联调**：[vsa-gsg.md](./vsa-gsg.md)
- **VSA 实现**：[implements/videostream-analytics-microservice.md](./implements/videostream-analytics-microservice.md)
- **Use case adapter 使用手册**：[use-case-adapter.md](./use-case-adapter.md)
- **端到端 schema→parser→alert 数据流**：[implements/schema-usecase-parser-alerts-pipeline.md](./implements/schema-usecase-parser-alerts-pipeline.md)
- **override 协议**：[../use-cases/README.md](../use-cases/README.md)
