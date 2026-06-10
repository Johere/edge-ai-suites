# MCP Server Ramp-Up Guide

> 适用读者：有 OpenClaw plugin (TS) 开发经验，熟悉 Python/C++，初次接触 MCP Server。

---

## 1. MCP 是什么 — 与 OpenClaw Plugin 的对比

| 概念 | OpenClaw Plugin | MCP Server |
|------|----------------|------------|
| **协议** | OpenClaw 私有 API（`api.registerTool`） | 开放标准协议 [Model Context Protocol](https://modelcontextprotocol.io) |
| **传输** | 同进程调用 | stdio（本地 pipe）或 SSE/HTTP（远程） |
| **暴露能力** | `api.registerTool(name, handler)` | `server.tool(name, schema, handler)` |
| **客户端** | 仅 OpenClaw | 任意 MCP Client：Claude Desktop、Cursor、Hermes、OpenClaw… |
| **生命周期** | 随 OpenClaw 进程 | 独立进程，Client 按需连接 |
| **订阅/推送** | 无原生机制 | `notifications/resources/updated`（Resource Subscription） |

**核心思维转变**：OpenClaw plugin 是"嵌入框架的扩展"；MCP Server 是"独立服务，被任何 Agent 框架消费"。你写的 MCP Server 对 Claude Desktop、Cursor、OpenClaw 一视同仁。

---

## 2. 核心概念速览（30 分钟）

### 2.1 三大原语

| 原语 | 类比 | 用途 |
|------|------|------|
| **Tool** | OpenClaw 的 `registerTool` / REST API endpoint | Agent 主动调用的操作（查询、写入、控制） |
| **Resource** | 只读 GET endpoint | 提供上下文数据，Agent 或 Client 读取 |
| **Prompt** | System prompt 模板 | 预定义的 prompt 模板（本项目未使用） |

### 2.2 传输层

```
┌─────────────────┐        stdio (pipe)         ┌─────────────────┐
│  MCP Client     │ ◄─── JSON-RPC messages ───► │  MCP Server     │
│  (Claude/Cursor)│                              │  (你写的)        │
└─────────────────┘                              └─────────────────┘
```

- **stdio**：Client spawn Server 子进程，通过 stdin/stdout 通信。本地开发首选。
- **SSE**：Server 启 HTTP，Client 连接。适用于远程部署。

### 2.3 消息格式（JSON-RPC 2.0）

```jsonc
// Client → Server: 调用 tool
{ "jsonrpc": "2.0", "id": 1, "method": "tools/call",
  "params": { "name": "smartbuilding_alert_query", "arguments": { "limit": 5 } } }

// Server → Client: 返回结果
{ "jsonrpc": "2.0", "id": 1, "result": { "content": [{ "type": "text", "text": "..." }] } }

// Server → Client: 推送通知（无 id，单向）
{ "jsonrpc": "2.0", "method": "notifications/resources/updated",
  "params": { "uri": "smartbuilding://monitor/cam01/alerts" } }
```

---

## 3. 从零创建一个 MCP Server（动手 Lab）

### 3.1 最小可运行示例

```bash
mkdir mcp-hello && cd mcp-hello
npm init -y
npm install @modelcontextprotocol/sdk zod
npm install -D typescript tsx @types/node
npx tsc --init --target es2022 --module nodenext --moduleResolution nodenext --outDir dist
```

创建 `src/index.ts`：

```typescript
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const server = new McpServer({ name: "hello-mcp", version: "0.1.0" });

// 注册一个 Tool（类比 api.registerTool）
server.tool(
  "greet",                                    // tool name
  "Say hello to someone",                     // description（Agent 用这个决定何时调用）
  { name: z.string().describe("Who to greet") }, // input schema（Zod → JSON Schema）
  async ({ name }) => ({                      // handler
    content: [{ type: "text", text: `Hello, ${name}!` }],
  })
);

// 注册一个 Resource（类比只读 API）
server.resource(
  "server-info",
  "hello://info",
  async () => ({
    contents: [{ uri: "hello://info", text: "This server is running." }],
  })
);

// 启动
const transport = new StdioServerTransport();
await server.connect(transport);
```

### 3.2 用 MCP Inspector 验证

```bash
# 安装 MCP Inspector（官方调试工具）
npx @modelcontextprotocol/inspector npx tsx src/index.ts
```

浏览器打开 Inspector UI → 左侧可看到 `greet` tool 和 `hello://info` resource → 点击调用测试。

### 3.3 接入 Claude Desktop

编辑 `~/.claude/claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "hello-mcp": {
      "command": "npx",
      "args": ["tsx", "/absolute/path/to/mcp-hello/src/index.ts"]
    }
  }
}
```

重启 Claude Desktop → 对话中输入 "greet Alice" → Agent 自动调用你的 tool。

---

## 4. 本项目 MCP Server 架构理解

### 4.1 入口 → 模块映射

```
packages/mcp-server/src/
├── index.ts              ← 启动入口：加载 config → 初始化 DB → 注册 tools/resources → 启动 worker
├── config.ts             ← YAML 配置解析
├── tools.ts              ← 8 个 MCP tool 注册（调用 @smartbuilding-video/tools 实现）
├── resources.ts          ← 4 个 MCP resource（monitors, latest-frame, stats, alerts）
├── events-endpoint.ts    ← HTTP webhook（接收 Python microservice 的事件推送）
└── video-worker/         ← 异步任务：轮询 DB → 调用 VLM → 写结果 → 触发 alert
```

### 4.2 与 OpenClaw Plugin 的关键差异

| 你在 OpenClaw Plugin 中做的 | 在 MCP Server 中的对应 |
|-----------------------------|----------------------|
| `definePluginEntry(api => {...})` | `main()` 函数里初始化 `McpServer` + `connect(transport)` |
| `api.registerTool("name", handler)` | `server.tool("name", desc, zodSchema, handler)` |
| `api.runtime.session.append(...)` | 不需要 — Agent 框架自己处理 UI |
| `api.runtime.subagent.run(...)` | 不在 MCP Server 层 — 由 openclaw-adapter 桥接 |
| 读/写 OpenClaw FS | 直接操作本地文件系统或 DB |

### 4.3 数据流（完整链路）

```
RTSP Camera
    │
    ▼
[videostream-analytics]  ── POST /events ──►  [events-endpoint.ts]
  (Python microservice)                           │
                                                  ▼ DB: insert pending task
                                            [video-worker/task-poller.ts]
                                                  │ poll every N sec
                                                  ▼
                                            [vlm-client.ts] → VLM Service (:8192)
                                                  │
                                                  ▼ parse + rule eval
                                            [rule-engine] → DB: insert alert
                                                  │
                                                  ▼ server.notification(...)
                                            MCP Resource Subscription
                                                  │
                                    ┌─────────────┼─────────────┐
                                    ▼             ▼             ▼
                              Claude Desktop   Cursor      OpenClaw (via adapter)
```

---

## 5. 关键 SDK API 速查

```typescript
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

// 创建 Server
const server = new McpServer({ name: "my-server", version: "1.0.0" });

// ─── Tool ───
server.tool(name, description, zodInputSchema, async (params) => {
  return { content: [{ type: "text", text: "result" }] };
});

// ─── Resource（静态 URI）───
server.resource(name, uri, async () => ({
  contents: [{ uri, text: "data" }],
}));

// ─── Resource（动态 URI，带参数）───
import { ResourceTemplate } from "@modelcontextprotocol/sdk/server/mcp.js";
server.resource(name, new ResourceTemplate("smartbuilding://monitor/{id}/alerts", { list: undefined }), async (uri, { id }) => ({
  contents: [{ uri: uri.href, text: JSON.stringify(getAlerts(id)) }],
}));

// ─── 推送通知（Resource Subscription）───
server.server.notification({
  method: "notifications/resources/updated",
  params: { uri: "smartbuilding://monitor/cam01/alerts" },
});

// ─── 连接传输层 ───
await server.connect(new StdioServerTransport());
```

---

## 6. 开发环境搭建

```bash
# 1. 进入项目
cd /mnt/disk1/projects/intel-innersource/openclaw-demo/agent-ai.smart-community-ai-automation

# 2. 安装依赖（monorepo，自动 link workspace packages）
npm install

# 3. 编译所有 packages
npm run build --workspaces

# 4. 用 Inspector 测试本项目 MCP Server
npx @modelcontextprotocol/inspector npx tsx packages/mcp-server/src/index.ts -- --config config.yaml.example

# 5. 运行已有测试
npx tsx tests/dev-mcp-server/run-all.ts
```

---

## 7. 推荐学习路径（1 周）

| Day | 目标 | 资源 |
|-----|------|------|
| 1 | 理解 MCP 协议全貌 | [MCP 官方文档](https://modelcontextprotocol.io/introduction)：读 Introduction + Core Concepts |
| 2 | 跑通 hello-mcp 示例 | 本文 §3 动手 Lab；用 Inspector 交互 |
| 3 | 读本项目 `index.ts` + `tools.ts` | 对照 §4 架构图，理解 wiring |
| 4 | 读 `video-worker/` + `events-endpoint.ts` | 理解异步任务链路和 webhook |
| 5 | 尝试添加一个新 tool | 参考 §8 实践任务 |
| 6 | 读 `resources.ts` + Resource Subscription | 理解推送机制 |
| 7 | 端到端：MCP Server + Inspector + Claude Desktop | 完整体验 Agent 调用 tool 的过程 |

---

## 8. 实践任务：添加一个新 Tool

目标：添加 `smartbuilding_ping` tool，返回 server 运行时间。

### Step 1: 在 `packages/tools/src/` 新建实现

```typescript
// packages/tools/src/ping.ts
const startTime = Date.now();

export function ping(): string {
  const uptimeSec = Math.floor((Date.now() - startTime) / 1000);
  return `Server uptime: ${uptimeSec}s`;
}
```

### Step 2: 在 `packages/mcp-server/src/tools.ts` 注册

```typescript
server.tool(
  "smartbuilding_ping",
  "Check server health and uptime",
  {},  // 无参数
  async () => ({
    content: [{ type: "text", text: ping() }],
  })
);
```

### Step 3: 编译 + Inspector 验证

```bash
npm run build --workspaces
npx @modelcontextprotocol/inspector npx tsx packages/mcp-server/src/index.ts -- --config config.yaml.example
# Inspector 中应能看到 smartbuilding_ping，点击 Call 测试
```

---

## 9. 常见 Gotchas

| 坑 | 说明 | 解决 |
|----|------|------|
| **stdout 污染** | MCP stdio 模式下，Server 的 stdout 是协议通道。`console.log()` 会破坏 JSON-RPC 帧 | 一律用 `console.error()` 输出日志 |
| **Zod schema = JSON Schema** | `server.tool` 的第 3 参数必须是 Zod object（SDK 内部转 JSON Schema 发给 Client） | 不要传 raw JSON Schema |
| **异步初始化** | DB、config 必须在 `server.connect()` 前就绪 | 参考 `index.ts` 的顺序 |
| **Resource URI 规范** | 自定义 scheme（如 `smartbuilding://`）需要 Client 支持 `list_changed` | 当前 SDK 默认支持 |
| **热重载** | `tsx --watch` 会重启进程，Client 连接断开 | 开发时用 Inspector（每次手动连接） |

---

## 10. 参考资料

| 资源 | 链接/路径 |
|------|-----------|
| MCP 官方规范 | https://modelcontextprotocol.io/specification |
| MCP TypeScript SDK | https://github.com/modelcontextprotocol/typescript-sdk |
| MCP Inspector | `npx @modelcontextprotocol/inspector` |
| 本项目设计文档 | `agent-ai.smarthome/docs/design/smartbuilding-video-design-2026.2.md` |
| 本项目 MCP Server 源码 | `packages/mcp-server/src/` |
| 本项目测试 | `tests/dev-mcp-server/` |
| MCP Server 示例集合 | https://github.com/modelcontextprotocol/servers |
