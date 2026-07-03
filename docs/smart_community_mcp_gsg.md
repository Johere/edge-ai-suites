# Smart Community MCP Server — Get Started Guide

## 前提条件

- Node.js ≥ 18
- npm（随 Node.js 安装）
- Docker + docker compose（跑 VLM 后端 `multilevel-video-understanding` + `vllm-ipex-serving`）

## 0. 启动 VLM 后端（首次或换栈时）

MCP server 依赖 `multilevel-video-understanding` (`:8192`) 作 video summary，以及 `vllm-ipex-serving` (`:41091`) 作单帧 scene_query。仓库根目录 `docker/multilevel-video-understanding/compose.yaml` 提供了自包含的 stack，与 MCP 数据目录对齐（`SMARTBUILDING_DATA_DIR` → 容器内 `/data:ro`）。

```bash
cd /home/user/jie/smarthome/smart-community/docker/multilevel-video-understanding
source ./set_env.sh                       # 导出 SMARTBUILDING_DATA_DIR、模型选择、VLM URL 等
docker compose up -d                      # 首次会拉/build 镜像；vllm 加载 35B 模型 ≈ 30 分钟
docker compose logs -f vllm-ipex-serving  # 等到日志出现 "Uvicorn running on ..."
```

准入依赖：**MCP 侧的 `SMARTBUILDING_DATA_DIR`（默认 `${HOME}/.mcp-smartbuilding`）、`set_env.sh` 里同名变量、`config.yaml.example` 的 `summary_service.path_remap.host_prefix` 三者必须指向同一个宿主机目录**——否则容器内 `/data/segments/...` 找不到 MCP 写下的 clip，会报 `Local file not found`。

停止（切换到其他 stack 前必须先 down 掉，否则端口冲突）：

```bash
cd /home/user/jie/smarthome/smart-community/docker/multilevel-video-understanding
source ./set_env.sh && docker compose down
```

> 若之前跑的是 `agent-ai.smarthome/start-video-summary-service/end2end` 那个旧 stack，需要先到那个目录 `source set_env.sh && docker compose down`，否则 `vllm-ipex-serving` / `multilevel-video-understanding` 端口 8192 / 41091 会占用。

## 1. 安装依赖

```bash
cd /home/user/jie/smarthome/smart-community
npm install
```

所有 workspace packages（`packages/db`、`packages/tools`、`packages/rule-engine`、`packages/mcp-server`）的依赖会自动安装并链接。

## 2. 编译

```bash
npm run build
```

编译所有 packages 的 TypeScript → `dist/`。

编译单个 package：

```bash
npm run build --workspace=packages/mcp-server
```

## 3. 运行

### stdio 模式（默认）

```bash
# 开发时（tsx 直接运行，无需编译）
npm run dev

# 或带配置文件
npx tsx packages/mcp-server/src/index.ts --config config.yaml.example --monitors monitor_cam_child.yaml

# 编译后运行
node packages/mcp-server/dist/index.js --config config.yaml.example --monitors monitor_cam_child.yaml
```

stdio 模式下，Server 通过 stdin/stdout 与 MCP Client 通信。通常由 Client 自动 spawn，不需要手动启动。

### Streamable HTTP 模式

```bash
# 开发时
# npm run dev:http --workspace=packages/mcp-server

# 带配置文件
npx tsx packages/mcp-server/src/index.ts --http --config config.yaml.example --monitors monitor_cam_child.yaml

# 编译后运行
node packages/mcp-server/dist/index.js --http --config config.yaml.example --monitors monitor_cam_child.yaml
```

HTTP 模式启动后输出：

```
[mcp-server] Streamable HTTP on http://localhost:3100/mcp
```

端口可在 `config.yaml` 中自定义：

```yaml
mcp:
  port: 3100
```

## 4. 验证

### 验证 stdio 模式（MCP Inspector）

```bash
npx @modelcontextprotocol/inspector npx tsx packages/mcp-server/src/index.ts --config config.yaml.example --monitors monitor_cam_child.yaml
```

浏览器打开 Inspector UI → 可看到 10 个 tools + 4 个 resources → 点击调用测试。

### 验证 HTTP 模式（curl）

```bash
curl -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"0.1.0"}}}'
```

正常返回：

```
event: message
data: {"result":{"protocolVersion":"2025-03-26","capabilities":{"tools":{"listChanged":true},"resources":{"listChanged":true}},"serverInfo":{"name":"smart-community","version":"0.1.0"}},"jsonrpc":"2.0","id":1}
```

## 5. 接入 Agent 客户端

### VS Code Claude Code（stdio）

项目根目录创建 `.mcp.json`：

```json
{
  "mcpServers": {
    "smart-community": {
      "command": "npx",
      "args": ["tsx", "packages/mcp-server/src/index.ts", "--config", "config.yaml.example"]
    }
  }
}
```

### Claude Desktop（stdio）

编辑 `~/.claude/claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "smart-community": {
      "command": "npx",
      "args": ["tsx", "/absolute/path/to/packages/mcp-server/src/index.ts", "--config", "/absolute/path/to/config.yaml"]
    }
  }
}
```

### OpenClaw（Streamable HTTP）

先手动启动 HTTP 模式：

```bash
npx tsx packages/mcp-server/src/index.ts --http --config config.yaml.example --monitors monitor_cam_child.yaml
```

然后在 OpenClaw 配置中添加：

```json
{
  "mcp": {
    "servers": {
      "smart-community": {
        "transport": "streamable-http",
        "url": "http://localhost:3100/mcp"
      }
    }
  }
}
```

启动后，命令行验证:
```bash
$ openclaw mcp probe  smart-community
│
◇

OpenClaw 2026.6.9 (c645ec4) — I'll refactor your busywork like it owes me money.

MCP probe (/home/mytest/.openclaw/openclaw.json):
- smart-community: 8 tools, resources

``` 

### Cursor（stdio）

项目根目录创建 `.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "smart-community": {
      "command": "npx",
      "args": ["tsx", "packages/mcp-server/src/index.ts", "--config", "config.yaml.example"]
    }
  }
}
```

## 6. 配置文件说明

`config.yaml` 完整示例（以 `config.yaml.example` 为准）：

```yaml
# 与 multilevel-video-understanding 容器的挂载路径对齐：
# host_prefix 必须等于 $SMARTBUILDING_DATA_DIR（也就是 docker/multilevel-video-understanding/set_env.sh
# 里同名变量的值）；container_prefix 与 compose.yaml 中 volumes 段的容器侧一致。
summary_service:
  url: http://localhost:8192
  path_remap:
    host_prefix: ${HOME}/.mcp-smartbuilding
    container_prefix: /data

# 单帧 scene_query 的 VLM 后端（vllm-ipex-serving）
vlm_service:
  url: http://localhost:41091/v1
  model: default
  max_edge_px: 720

# videostream-analytics 微服务
videostream_analytics:
  url: http://localhost:8999

poll_interval_ms: 5000
video_summary_max_concurrent: 2

# HTTP 模式端口（可选，默认 3100）
mcp:
  port: 3100

# events webhook 端口（接 videostream-analytics）
events_webhook:
  port: 3101

# DB schema 扩展（用例自定义字段）
schema:
  video_summary_tasks:
    extensions:
      - { name: "event",      type: "text", required: true }
      - { name: "severity",   type: "text", required: true }
      - { name: "desc",       type: "text", required: true }
      - { name: "confidence", type: "real", required: false }
  custom_tables: []
```

数据目录由 `SMARTBUILDING_DATA_DIR` 环境变量决定（默认 `~/.mcp-smartbuilding`），布局：

```
$SMARTBUILDING_DATA_DIR/
├── smartbuilding.db                     # SQLite（events / video_summary_tasks / alerts / …）
├── segments/<monitor_id>/               # videostream-analytics 写入的 clip / latest.jpg
│   ├── latest.jpg
│   ├── motion_events/<YYYY-MM-DD>/*.mp4
│   └── recordings/<YYYY-MM-DD>/*.mp4
└── logs/monitors/<monitor_id>/<YYYY-MM-DD>.log
```

## 7. 可用 MCP Tools

| Tool | 功能 |
|------|------|
| `smartbuilding_alert_query` | 查询/确认告警（action: latest / by_date / ack / stats） |
| `smartbuilding_state_query` | 读写 per-monitor JSON state store（action: get / set / delete） |
| `smartbuilding_scene_query` | 实时 VLM 画面分析（读 latest.jpg → VLM） |
| `smartbuilding_generate_report` | 生成日/周/月/自定义报告（表源由 use_case_dict.reports 决定） |
| `smartbuilding_monitor_ctl` | Monitor 生命周期（action: register_source / unregister / start / stop / status / list） |
| `smartbuilding_monitors_compose` | 基于 monitors.yaml 的批量管理（action: validate / up / down / restart / ps） |
| `smartbuilding_plan_ctl` | Per-monitor plan 管理，rule engine 可读 today's plan（action: list / upsert / delete） |
| `smartbuilding_rule_eval` | 手动触发 rule 评估（dry-run 或 create_alert=true） |
| `smartbuilding_video_db` | 底层只读 SQL 查询（仅 SELECT） |
| `smartbuilding_use_case_validate` | 校验 use_case ↔ VLM task prompt ↔ schema 一致性 |

## 8. 可用 MCP Resources

| Resource URI | 说明 |
|---|---|
| `smartbuilding://monitors` | 所有 monitor 列表 + 在线状态 |
| `smartbuilding://monitor/{id}/latest-frame` | 最新帧（base64 JPEG） |
| `smartbuilding://monitor/{id}/stats` | 当日事件/告警统计 |
| `smartbuilding://monitor/{id}/alerts` | 最近告警列表 |

## 9. 两种传输模式对比

| | stdio | Streamable HTTP |
|--|-------|-----------------|
| 启动方式 | Client 自动 spawn | 手动启动 |
| 参数 | （默认） | `--http` |
| 端口 | 无 | 3100（可配） |
| 多 Client 连接 | 不行（1对1） | 可以（1对多） |
| 实时推送 | 支持 | 支持（GET /mcp streamable-http 流） |
| 适用 Client | Claude Desktop、VS Code、Cursor | OpenClaw、远程部署 |
