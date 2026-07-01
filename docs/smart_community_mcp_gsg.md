# Smart Community MCP Server — Get Started Guide

## 前提条件

- Node.js ≥ 18
- npm（随 Node.js 安装）

## 1. 安装依赖

```bash
cd agent-ai.smart-community-ai-automation
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

浏览器打开 Inspector UI → 可看到 8 个 tools + 4 个 resources → 点击调用测试。

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

`config.yaml` 完整示例：

```yaml
db:
  path: ./data/smartbuilding.db

summary_service:
  url: http://localhost:8192

videostream_analytics:
  url: http://localhost:8999

segments_dir: ./segments
poll_interval_ms: 5000
video_summary_max_concurrent: 2

# HTTP 模式端口（可选，默认 3100）
mcp:
  port: 3100

# DB schema 扩展（用例自定义字段）
schema:
  video_summary_tasks:
    extensions:
      - { name: "event", type: "text", required: true }
      - { name: "severity", type: "text", required: true }
      - { name: "desc", type: "text", required: true }
      - { name: "confidence", type: "real", required: false }
  alerts:
    extensions: []
  custom_tables: []
```

## 7. 可用 MCP Tools

| Tool | 功能 |
|------|------|
| `smartbuilding_alert_query` | 查询/确认告警 |
| `smartbuilding_state_query` | 读写 monitor 状态 |
| `smartbuilding_scene_query` | 实时 VLM 画面分析 |
| `smartbuilding_daily_report` | 生成日报 |
| `smartbuilding_monitor_ctl` | 启停/注册视频源 |
| `smartbuilding_rule_eval` | 手动触发规则评估 |
| `smartbuilding_video_db` | 底层 DB 查询 |
| `smartbuilding_use_case_validate` | 校验 prompt ↔ schema 一致性 |

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
