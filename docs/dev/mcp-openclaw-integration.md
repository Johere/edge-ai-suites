# MCP Server ↔ OpenClaw / VLM 联调指南

**日期**: 2026-07-01
**目标**: 说清楚 smart-community 仓的 MCP server 如何跟 (1) OpenClaw、(2) videostream-analytics
(VSA)、(3) multilevel-video-understanding (VLM) 三者联调。

---

## 0. TL;DR

| 问题 | 答案 |
|------|------|
| 我能不能把 smart-community 里的 MCP server "装到" OpenClaw 里？ | **不能直接装**。OpenClaw 2026.4.1 无原生 MCP client 支持。 |
| 那 `openclaw.json` 里的 `mcp.servers` 是什么？ | Design doc §4.3 里的**未来能力**。当前 runtime `openclaw.json` 无此字段。 |
| 那怎么调？ | 用 **Claude Desktop / Cursor / MCP Inspector** 当 MCP client；OpenClaw 端**继续用它自己的 plugin** (smarthome-video)。两条链**并行**跑。 |
| Use case adapter 和 VSA 能联调吗？ | **能**。VSA → webhook → MCP server → task-poller → VLM → parser → rule engine → alerts，端到端已通。 |

---

## 1. 三个服务的关系

```
┌────────────────────────────────────────────────────────────────┐
│  开发机                                                          │
│                                                                │
│  ┌── smart-community 仓 ────────────────────────────────────┐   │
│  │                                                        │   │
│  │  MCP Server (Node.js) :3100 (SSE) / stdio              │   │
│  │  Events Webhook :3101                                  │   │
│  │  ├── 8 个 MCP tools                                    │   │
│  │  ├── 4 个 MCP resources                                │   │
│  │  ├── Task-poller → VLM /v1/summary                     │   │
│  │  ├── Rule engine → alerts                              │   │
│  │  └── SQLite $SMARTBUILDING_DATA_DIR/smartbuilding.db   │   │
│  │                                                        │   │
│  └────────────────────────────────────────────────────────┘   │
│           ▲                                    ▲               │
│           │ (a) MCP protocol                   │ (b) HTTP     │
│           │                                    │              │
│  ┌────────┴─────────┐              ┌───────────┴──────────┐   │
│  │ MCP Client       │              │ VSA :8999            │   │
│  │  - Claude Desktop│              │ (agent-ai.smarthome  │   │
│  │  - Cursor        │              │  仓，Python 微服务)   │   │
│  │  - MCP Inspector │              │  motion + NPU YOLO   │   │
│  │  - Claude Code   │              │  POST /events →      │   │
│  └──────────────────┘              │  ${SMARTBUILDING_DATA│   │
│                                    │   _DIR}/segments/... │   │
│                                    └──────────┬───────────┘   │
│                                               │ (c) HTTP     │
│  ┌────────────────────────────────────────────▼───────────┐   │
│  │ multilevel-video-understanding :8192                    │   │
│  │ (agent-ai.smarthome 仓，Docker compose 起两个容器)     │   │
│  │  - VLM 推理                                            │   │
│  │  - Dynamic Task Registry                               │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                                │
│  ┌── agent-ai.smarthome (可选，不跟 MCP 一起跑) ────────────┐   │
│  │ OpenClaw Gateway :18789                                │   │
│  │ smarthome-video plugin (走 plugin API，不走 MCP)       │   │
│  │ 目前跟 smart-community 的 MCP 服务是**独立两条链**       │   │
│  └────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────┘
```

### 关键事实

1. **smart-community 是独立仓** — 它自己有 MCP server + task-poller + rule engine
2. **agent-ai.smarthome 是另一个独立仓** — 里面有 VSA + VLM + OpenClaw plugin
3. 两个仓**共用底层微服务** (VSA + VLM)，但 MCP server 只在 smart-community 里
4. **OpenClaw plugin 里的逻辑 ≠ MCP server 里的逻辑** — 是**两条并行链**，功能有重叠

---

## 2. 同事说"参考 agent-ai.smarthome 装 openclaw" 到底啥意思？

### 2.1 事实核查

在 [/home/user/jie/smarthome/agent-ai.smarthome/agent-ai.smarthome-openclaw-runtime-workspace/openclaw.json](../../../agent-ai.smarthome/agent-ai.smarthome-openclaw-runtime-workspace/openclaw.json) 里：

```
$ grep -n "mcp\|MCP\|mcpServers" openclaw.json
(empty)
```

- **无** `mcp:` 顶层字段
- **无** `mcpServers:` 顶层字段
- **无** `mcp.servers` 嵌套字段

`plugins.entries.smarthome-video` 是**普通 OpenClaw plugin**，通过 `openclaw/plugin-sdk/plugin-entry`
注册 tool，**不走 MCP 协议**。

### 2.2 Design doc 怎么说的？

[smartbuilding-video-design-2026.2.md §4.3](../smartbuilding-video-design-2026.2.md#43-standalone-mcp-client) 声称
OpenClaw SSE 模式支持：

```json
{
  "mcp": {
    "servers": {
      "smartbuilding-video": {
        "transport": "sse",
        "url": "http://localhost:3100"
      }
    }
  }
}
```

**这个能力在当前 OpenClaw runtime (2026.4.1) 里不存在** — 是设计文档描绘的未来目标，
未落地。如果 OpenClaw 后续版本加了这个能力，那么"装 openclaw + 改 openclaw.json"
就能把 smart-community MCP server 挂上去。**当前不行**。

### 2.3 那"参考 agent-ai.smarthome" 到底是啥合理的解释？

三种可能，从最有可能到最不可能：

1. **VLM 服务 + VSA 服务的启动脚本**参考它 — 因为 agent-ai.smarthome 里有成熟的
   `start-video-summary-service/end2end/docker-compose` 起 VLM 的方案，同事的意思是
   **借它的 docker-compose 起 VLM 服务**，MCP 独立跑
2. **OpenClaw plugin 逻辑作为 MCP tool 实现的对照参考** — smart-community 的
   `packages/tools/*` 里很多实现都是从 `openclaw-extensions/smarthome-video/src/tools/*`
   平移过来的，同事的意思是**继续参考现有实现平移**
3. **未来 OpenClaw 版本升级到支持 MCP 后**，那时候只需改 openclaw.json

我倾向于 (1)+(2) 都对。**现在能做的**：把 VLM + VSA 从 agent-ai.smarthome 起来，
smart-community MCP server 独立跑，两边通过 HTTP 联调。

---

## 3. 完整 setup 步骤（可执行）

### 3.1 起底层服务（VLM + vLLM）

```bash
# 从 agent-ai.smarthome 起 VLM 服务（依赖 vLLM）
cd /home/user/jie/smarthome/agent-ai.smarthome/start-video-summary-service/end2end
source set_env.sh
docker compose up -d

# 等所有容器 healthy
docker ps --format "table {{.Names}}\t{{.Status}}"
# 期望：
# end2end-multilevel-video-understanding-1   Up X seconds (healthy)
# end2end-vllm-ipex-serving-1                Up X seconds (healthy)

# 健康检查
curl -sS http://localhost:8192/v1/health && echo OK
curl -sS http://localhost:41091/v1/models | head
```

首次 FP8 编译 3-20 min，之后重启只要 30-60s。

### 3.2 起 VSA（可选，如果要真实 RTSP 联调）

VSA 在 [/home/user/jie/smarthome/smart-community/videostream-analytics/](../../videostream-analytics/)
里 — **就在 smart-community 仓内**，不需要跨仓。

```bash
cd /home/user/jie/smarthome/smart-community/videostream-analytics

# 起 mediamtx（RTSP 服务器）— 需要在 host 有 mediamtx binary
mediamtx config/mediamtx.yml &

# 起 VSA HTTP 微服务
.venv/bin/python -m stream_monitor.service --port 8999 &

# 健康检查
curl -sS http://localhost:8999/health
```

（如果本次调试只走"手工塞 DB → rule_eval" 路径，可以跳过 VSA。）

### 3.3 起 smart-community MCP server

```bash
cd /home/user/jie/smarthome/smart-community

npm install                    # 首次
npm run build                  # 编译所有 packages

# 起服务器（HTTP 模式，方便用 curl 调）
export SMARTBUILDING_DATA_DIR=/tmp/mcp-e2e
mkdir -p $SMARTBUILDING_DATA_DIR

node packages/mcp-server/dist/index.js \
  --config config.yaml.example \
  --monitors /path/to/monitors.yaml \
  --http
# → [mcp-server] Streamable HTTP on http://localhost:3100/mcp
```

### 3.4 挂接 MCP Client（选一个）

#### 方式 A: Claude Desktop（本地对话）

`~/.claude/claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "smartbuilding-video": {
      "command": "npx",
      "args": [
        "tsx",
        "/home/user/jie/smarthome/smart-community/packages/mcp-server/src/index.ts",
        "--config",
        "/home/user/jie/smarthome/smart-community/config.yaml.example"
      ],
      "env": {
        "SMARTBUILDING_DATA_DIR": "/tmp/mcp-e2e"
      }
    }
  }
}
```

重启 Claude Desktop，就能在对话里调 `smartbuilding_alert_query` 等 tool。

#### 方式 B: Claude Code（VS Code / CLI）

项目根 `/home/user/jie/smarthome/smart-community/.mcp.json`：

```json
{
  "mcpServers": {
    "smartbuilding-video": {
      "command": "npx",
      "args": [
        "tsx",
        "packages/mcp-server/src/index.ts",
        "--config",
        "config.yaml.example"
      ],
      "env": {
        "SMARTBUILDING_DATA_DIR": "/tmp/mcp-e2e"
      }
    }
  }
}
```

启动 Claude Code (`claude` in this dir) → 自动 spawn MCP server → tools 可用。

#### 方式 C: MCP Inspector（浏览器 GUI 调试）

```bash
npx @modelcontextprotocol/inspector \
  npx tsx /home/user/jie/smarthome/smart-community/packages/mcp-server/src/index.ts \
  --config /home/user/jie/smarthome/smart-community/config.yaml.example
```

浏览器打开 Inspector，可交互式调用每个 tool，看到 request/response，最适合调试。

#### 方式 D: 纯 curl（脚本自动化）

在 §3.3 起的 HTTP 服务基础上：

```bash
curl -sS -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
    "name":"smartbuilding_rule_eval",
    "arguments":{"monitor_id":"cam_test","task_id":1}}}' \
  | grep "^data:" | head -1 | sed 's/^data: //' | jq .
```

---

## 4. Use case adapter 和 VSA 能不能联合调试？

**答案：可以，链路完整**。

### 4.1 端到端数据流

```
① 视频推流：mediamtx 收 RTSP，VSA 从 mediamtx 拉
        ↓
② VSA motion detect + NPU YOLO prefilter → 切 clip
        ↓
③ VSA POST /events (motion payload w/ clip_file_path) → MCP :3101/events
        ↓
④ MCP events-endpoint 写 DB: events + pending video_summary_task
        ↓
⑤ MCP task-poller (每 5s 轮询) 拿 pending task
        ↓
⑥ POST /v1/summary → VLM :8192 → summary_text
        ↓
⑦ parseSummaryFields 抽 event/severity/desc/... → 写 task 扩展列
        ↓
⑧ rule engine call use-cases/<uc>/evaluate_rules.py → shouldAlert?
        ↓
⑨ Cooldown check → INSERT alerts → MCP notifications/resources/updated
        ↓
⑩ MCP client (Claude Desktop 等) 收到 push
```

### 4.2 联调所需服务清单

| # | 服务 | 端口 | 起自 | 用途 |
|---|------|------|------|------|
| 1 | mediamtx | 8554 | agent-ai.smarthome/scripts | RTSP 服务器 |
| 2 | ffmpeg RTSP pusher | — | 手工 / 脚本 | 把 mp4 推成 RTSP |
| 3 | VSA | 8999 | smart-community/videostream-analytics | 动态视频源管理 + prefilter |
| 4 | vLLM | 41091 | agent-ai.smarthome docker | LLM 推理后端 |
| 5 | multilevel-video-understanding | 8192 | 同上 docker | VLM 视频摘要 |
| 6 | MCP server | 3100 / 3101 | smart-community | tool 分发 + task-poller + rule engine |
| 7 | MCP client | — | Claude Desktop / Inspector | 用户交互 |

### 4.3 最小联调步骤（单 use case: parking_safety）

```bash
# 1. 起底层
cd /home/user/jie/smarthome/agent-ai.smarthome/start-video-summary-service/end2end
source set_env.sh && docker compose up -d

# 2. 注册 VLM task（一次性）
python3 /home/user/jie/smarthome/smart-community/scripts/register-vlm-task.py \
  --use-case parking_safety   # 假设有这个脚本，见 vlm-integration-gsg.md

# 3. 起 VSA
cd /home/user/jie/smarthome/smart-community/videostream-analytics
.venv/bin/python -m stream_monitor.service --port 8999 &

# 4. 起 MCP server
cd /home/user/jie/smarthome/smart-community
export SMARTBUILDING_DATA_DIR=/tmp/mcp-e2e
node packages/mcp-server/dist/index.js \
  --config config.yaml.example \
  --monitors monitors-parking.yaml --http &

# 5. 通过 MCP tool 注册 source（这一步 VSA + MCP 都知道这个 monitor）
curl -sS -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
    "name":"smartbuilding_monitor_ctl",
    "arguments":{
      "action":"register_source",
      "monitor_id":"cam_parking",
      "source_url":"rtsp://localhost:8554/live/parking",
      "use_case":"parking_safety"
    }}}'

# 6. 推流触发 pipeline
ffmpeg -re -stream_loop -1 -i false-parking.mp4 \
  -c copy -f rtsp rtsp://localhost:8554/live/parking &

# 7. 观察 alerts
watch -n 3 'curl -sS -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{
    \"name\":\"smartbuilding_alert_query\",
    \"arguments\":{\"monitor_id\":\"cam_parking\",\"action\":\"latest\"}}}" \
  | grep ^data: | head -1'
```

### 4.4 关键 debug 点

| 症状 | 检查 |
|------|------|
| VSA `/register_source` 返回错误 | `curl :8999/sources` 看已注册列表；`curl :8999/health` |
| VSA 收到 RTSP 但没发 webhook | 检查 VSA logs (motion 阈值 / prefilter 是否 PASS) |
| MCP `:3101/events` 没收到 payload | 检查 VSA register 时的 `webhook_url` 参数 |
| Task 卡在 pending | 看 mcp-server logs，看有没有 VLM 调用；`curl :8192/v1/health` |
| VLM 返回 summary 但字段不对 | 检查 prompt.md，参照 [use-case-adapter.md](../use-case-adapter.md) 4 条 conventions |
| Rule 没触发 alert | `smartbuilding_rule_eval` 手工重跑，看 shouldAlert |
| Alert 存了但 Claude Desktop 没收到 | 检查 MCP client 是否订阅了 `smartbuilding://monitor/*/alerts` |

---

## 5. OpenClaw 那边呢？

**独立跑就行**。OpenClaw 里的 `smarthome-video` plugin 有它自己的 SQLite / task-poller /
VLM 客户端，与 smart-community MCP server 平行。

如果要**同时验证两条链**，用两套隔离目录：

```bash
# OpenClaw 侧
~/.openclaw/                                # OpenClaw runtime，plugin 用
$HOME/.openclaw/smarthome-demo/data/        # plugin 的 SQLite

# smart-community MCP 侧
$SMARTBUILDING_DATA_DIR=/tmp/mcp-e2e        # MCP 的 SQLite + segments
```

两条链**共享** VLM (:8192) 和 vLLM (:41091)。

**未来** — 如果 OpenClaw 升级支持 MCP client，就能通过 §2.2 里 design 声称的
`openclaw.json` → `mcp.servers` 直接连 smart-community 的 MCP server，届时可以：

- 删掉 `openclaw-extensions/smarthome-video/` (~5000 行 plugin 代码)
- 让 OpenClaw agent 通过 MCP 调用 smart-community 的 8 个 tool
- 单一 SQLite / 单一 task-poller

这是 Design 2026.2 的**长期目标**，也是 v0.4 → v1.0 演进方向。

---

## 6. FAQ

### Q1: 现在 use case adapter 能不能不起 VSA / VLM 就调？

**能，走两种简化路径**：

- **纯 unit 层**：直接 `python3 use-cases/<uc>/evaluate_rules.py <ctx.json>`，看 override 逻辑
- **半 e2e**：手工 SQLite `INSERT INTO video_summary_tasks (...)`
  塞一条模拟的 completed task → 调 `smartbuilding_rule_eval` → 看 alert
  （见 [use-case-adapter-validation.md](./use-case-adapter-validation.md) §Step 4）

### Q2: MCP server 起来后 tool 有几个？

`config.yaml.example` 默认注册 **10 个 tool**（tool 名+功能见 [smart_community_mcp_gsg.md §7](../smart_community_mcp_gsg.md#7-可用-mcp-tools)），
比 design §3.2 的 8 个多 2 个 (plan_ctl, monitors_compose, state_query, rule_eval)。

### Q3: OpenClaw 版本要求？

Design §4.3 声称的 MCP client 支持还没落地。可以先按现有 2026.4.1 用 plugin，
或**跳过 OpenClaw**，用 Claude Desktop / Claude Code 作为 MCP client — 效果一样。

---

## 参考

- [smart_community_mcp_gsg.md](../smart_community_mcp_gsg.md) — MCP server 启动手册（本仓）
- [use-case-adapter-gsg.md](../use-case-adapter-gsg.md) — Adapter 一键 e2e recipe
- [vlm-integration-gsg.md](../vlm-integration-gsg.md) — 挂 VLM task 手册
- [vsa-gsg.md](../vsa-gsg.md) — VSA 部署手册
- [/home/user/jie/smarthome/agent-ai.smarthome/CLAUDE.md](../../../agent-ai.smarthome/CLAUDE.md) — 那边仓的架构说明
