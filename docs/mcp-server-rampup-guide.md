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

## 3. Node.js / TypeScript 工具链速查

> 面向 Python/C++ 背景开发者，解释 Node.js 生态中常见的命令和概念。

### 3.1 为什么用 TypeScript 而不是 JavaScript

TypeScript = JavaScript + 静态类型检查。类比：

| | C++ | TypeScript | JavaScript |
|--|-----|-----------|-----------|
| 类型系统 | 静态，编译期检查 | 静态，编译期检查 | 动态，运行时才报错 |
| 发现错误时机 | 编译时 | `tsc` 时 | 跑到那行代码才炸 |
| 类比关系 | — | C++ | 汇编 |

选 TypeScript 的收益：编译期消灭拼写/类型错误、IDE 精确补全、重构有保障、类型即文档。代价仅是多一步编译（开发时用 `tsx` 几乎无感）。

TypeScript 约 2018–2019 年成为前端/Node.js 主流，2024–2025 年 AI Agent 生态（MCP SDK、LangChain.js、OpenClaw）全面采用。

### 3.2 包管理器：npm vs pnpm

| | npm | pnpm |
|--|-----|------|
| 定位 | Node.js 自带的包管理器 | npm 的高性能替代品 |
| 类比 | Python 的 `pip` | pip 但更快更省空间 |
| 安装依赖 | `npm install` | `pnpm install` |
| 添加包 | `npm install zod` | `pnpm add zod` |
| 运行脚本 | `npm run build` | `pnpm run build` |
| 磁盘占用 | 每个项目独立复制 | 全局 store + 硬链接，多项目共享 |
| 安装速度 | 一般 | 快 2-3x |
| Lock 文件 | `package-lock.json` | `pnpm-lock.yaml` |

**本项目用 npm**（有 `package-lock.json`）。如果看到别的项目有 `pnpm-lock.yaml`，说明它用 pnpm。

#### `npm install` 的三种形式

| 命令 | 装到哪 | 更新 package.json | 用途 |
|------|--------|------------------|------|
| `npm install zod` | 当前项目 `node_modules/` | 是，写入 `"dependencies"` | 项目运行时依赖 |
| `npm install -D tsx` | 当前项目 `node_modules/` | 是，写入 `"devDependencies"` | 项目开发时依赖 |
| `npm install -g pnpm` | 系统全局目录 | 否 | 全局 CLI 工具，与项目无关 |
| `npm install`（不带包名） | 当前项目 `node_modules/` | 否 | 按已有 package.json 安装所有依赖 |

类比 Python：

```bash
pip install requests          # ≈ npm install requests（项目依赖）
pip install --user black      # ≈ npm install -g black（全局工具）
pip install -r requirements.txt  # ≈ npm install（按清单安装）
```

npm 比 pip 更自动 — `npm install <包名>` 安装的同时自动记录到 `package.json`，不需要手动维护依赖列表。

### 3.3 npx — 临时执行器

`npx` 是 npm 自带的工具，用于**一次性运行某个包的可执行文件**，不永久安装：

```bash
npx tsx src/index.ts                          # 临时运行 tsx
npx @modelcontextprotocol/inspector ...       # 临时运行 MCP Inspector
npx tsc --init                                # 临时运行 TypeScript 编译器
```

如果包已在本地 `node_modules/.bin/` 中（已 install），npx 直接用本地版本，不重复下载。

类比：Python 的 `pipx run`。

### 3.4 tsc vs tsx

| | tsc | tsx |
|--|-----|-----|
| 全称 | TypeScript Compiler | TypeScript Execute |
| 来源 | 官方（microsoft/TypeScript） | 第三方（privatenumber/tsx） |
| 做什么 | 类型检查 + 生成 `.js` 文件 | 即时转译 + 直接运行（不生成文件） |
| 类型检查 | 做 | 不做 |
| 速度 | 慢（全量检查） | 快（esbuild 转译） |
| 用途 | CI / 发布前编译 | 开发时快速运行 |
| 类比 | `g++ -o main src/*.cpp`（编译） | 假想的 `run main.cpp`（直接执行，跳过严格检查） |

典型工作流：

```bash
# 开发：tsx 快速迭代（改完直接跑，不需要手动编译）
npx tsx src/index.ts

# 提交前：tsc 检查类型（确保没有类型错误）
npx tsc --noEmit

# 构建部署：tsc 编译产物 → node 运行
npx tsc                  # 编译 src/*.ts → dist/*.js
node dist/index.js       # 运行（生产环境只需 Node.js，不需要 tsx）
```

### 3.5 node_modules 目录

`npm install` 把所有依赖的**源码**下载到 `node_modules/`：

```
node_modules/
├── zod/                          # 你声明的依赖
├── @modelcontextprotocol/sdk/    # 你声明的依赖
├── typescript/                   # devDependency
└── ...其他间接依赖...            # 递归展开的依赖树
```

| 特点 | 说明 |
|------|------|
| 类比 | Python 的 `site-packages/`，C++ 的 vcpkg/conan 下载目录 |
| 是否提交 git | 不提交（`.gitignore` 里有它） |
| 可以删除重建 | `rm -rf node_modules && npm install` |
| 体积 | 通常几百 MB（JS 生态依赖链很深） |

### 3.6 tsconfig.json — TypeScript 的 "Makefile"

`npx tsc` 不需要手动列出编译文件，它读 `tsconfig.json`：

```jsonc
{
  "compilerOptions": {
    "target": "es2022",       // 编译目标 JS 版本
    "module": "nodenext",     // 模块系统
    "outDir": "dist",         // 输出目录
    "rootDir": "src"          // 源码目录
  },
  "include": ["src/**/*.ts"]  // ← 编译哪些文件（glob 模式）
}
```

类比：

| C++ | TypeScript |
|-----|-----------|
| `CMakeLists.txt` 里的 `add_executable(main src/*.cpp)` | `tsconfig.json` 里的 `"include": ["src/**/*.ts"]` |
| `cmake --build .` | `npx tsc` |

### 3.7 package.json — 项目清单

类比 Python 的 `pyproject.toml` / `requirements.txt` + `Makefile`，集三个职责于一身：

```jsonc
{
  "name": "@smartbuilding-video/mcp-server",   // 包名
  "version": "0.1.0",
  "scripts": {                                  // 可运行的命令（类比 Makefile targets）
    "build": "tsc",                             // npm run build → 执行 tsc
    "dev": "tsx src/index.ts"                   // npm run dev → 执行 tsx src/index.ts
  },
  "dependencies": {                             // 运行时依赖（类比 requirements.txt）
    "@modelcontextprotocol/sdk": "^1.12.1",
    "zod": "^3.24.0"
  },
  "devDependencies": {                          // 开发时依赖（不随产物发布）
    "typescript": "^5.8.0",
    "tsx": "^4.19.0"
  }
}
```

### 3.8 完整对照表

| Python / C++ | Node.js / TypeScript | 说明 |
|-------------|---------------------|------|
| `pip install` | `npm install` | 安装依赖 |
| `pip install -e .` | `npm link` | 本地开发模式安装 |
| `pipx run` | `npx` | 临时执行 |
| `python main.py` | `npx tsx src/index.ts` | 开发时运行 |
| `g++ → ./main` | `npx tsc → node dist/index.js` | 编译 → 运行产物 |
| `site-packages/` | `node_modules/` | 依赖存放目录 |
| `requirements.txt` | `package.json` (dependencies) | 依赖声明 |
| `Makefile` / `CMakeLists.txt` | `tsconfig.json` + `package.json` (scripts) | 构建配置 |
| `pyproject.toml` | `package.json` | 项目元信息 |
| virtualenv | 项目级 `node_modules/`（天然隔离） | 依赖隔离 |

---

## 4. 从零创建一个 MCP Server（动手 Lab）

### 4.1 最小可运行示例

```bash
mkdir mcp-hello && cd mcp-hello

# 生成 package.json（-y 跳过交互问答，全用默认值）。
npm init -y

# ⚠️ 重要：在 package.json 中添加 "type": "module"
# 否则 Node.js 默认把 .js 当 CommonJS，import/export 语法会报错：
#   "ECMAScript imports and exports cannot be written in a CommonJS file"
# 添加后告诉 Node.js：本项目所有 .js 文件都是 ESM 模块。
npm pkg set type=module

# 安装运行时依赖
# @modelcontextprotocol/sdk — MCP 官方 TypeScript SDK
# zod — 类型校验库，声明 tool 的输入参数 schema
# express — HTTP 服务器（HTTP 模式需要）
# cors — 跨域中间件（Inspector 在浏览器运行，需要 CORS 允许跨域请求）
npm install @modelcontextprotocol/sdk zod express cors

# 安装开发依赖
npm install -D typescript tsx @types/node @types/express @types/cors

# 生成 tsconfig.json
npx tsc --init --target es2022 --module nodenext --moduleResolution nodenext --outDir dist
```

⚠️ **tsconfig.json 额外修改**：`npx tsc --init` 生成的默认配置可能包含过于严格的选项，需要手动调整：

```jsonc
{
  "compilerOptions": {
    "module": "nodenext",
    "target": "es2022",
    "outDir": "dist",
    "types": ["node"],                        // ← 添加，否则找不到 Node.js 类型
    // "exactOptionalPropertyTypes": true,     // ← 注释掉，与 MCP SDK 类型不兼容
    "strict": true,
    "skipLibCheck": true,
    "moduleResolution": "nodenext"
  }
}
```

创建 `src/index.ts`（同时支持 stdio 和 Streamable HTTP 两种传输）：

```typescript
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { createMcpExpressApp } from "@modelcontextprotocol/sdk/server/express.js";
import { z } from "zod";

// ⚠️ 关键：Streamable HTTP 无状态模式下，每个请求需要独立的 server 实例
// 用工厂函数创建，而不是全局单例
function createServer() {
  const server = new McpServer({ name: "hello-mcp", version: "0.1.0" });

  // ─── 注册 Tool ───
  server.registerTool(
    "greet",
    {
      description: "Say hello to someone",
      inputSchema: { name: z.string().describe("Who to greet") },
    },
    async ({ name }: { name: string }) => ({
      content: [{ type: "text" as const, text: `Hello, ${name}!` }],
    })
  );

  // ─── 注册 Resource ───
  server.registerResource(
    "server-info",
    "hello://info",
    { description: "Server status information" },
    async () => ({
      contents: [{ uri: "hello://info", text: "This server is running." }],
    })
  );

  return server;
}

// ─── 根据命令行参数选择传输方式 ───
const args = process.argv.slice(2);
const transportMode = args.includes("--http") ? "http" : "stdio";

if (transportMode === "http") {
  // Streamable HTTP 模式：无状态，每个请求创建新的 server + transport
  // ⚠️ 必须使用 createMcpExpressApp()，不能用普通 express()
  const app = createMcpExpressApp();

  // ⚠️ 关键：支持 GET 和 POST（GET 用于 SSE 连接，POST 用于消息请求）
  app.all("/mcp", async (req, res) => {
    const server = createServer();
    console.error(`[mcp] ${req.method} /mcp`);

    try {
      // ⚠️ 每个请求创建新 transport + 新 server.connect()
      const transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: undefined,  // 无状态模式
      });
      await server.connect(transport);
      await transport.handleRequest(req, res, req.body);

      // ⚠️ 请求结束时清理资源
      res.on("close", () => {
        transport.close();
        server.close();
      });
    } catch (error) {
      console.error("[mcp] Error:", error);
      if (!res.headersSent) {
        res.status(500).json({
          jsonrpc: "2.0",
          error: { code: -32603, message: "Internal server error" },
          id: null,
        });
      }
    }
  });

  const port = 3111;
  app.listen(port, () => {
    console.error(`MCP HTTP server running on http://localhost:${port}/mcp`);
  });
} else {
  // stdio 模式：Client 自动 spawn 本进程，通过 stdin/stdout 通信
  // stdio 模式可以复用单一 server 实例
  const server = createServer();
  const transport = new StdioServerTransport();
  await server.connect(transport);
}
```

> **注意**：SDK v1.29 废弃了 `SSEServerTransport`，改用 `StreamableHTTPServerTransport`。新协议基于标准 HTTP POST，比 SSE 更简洁可靠。

### 4.2 启动方式

```bash
# stdio 模式（默认）— Client 自动启动，开发调试用
npx tsx src/index.ts

# HTTP 模式 — 手动启动，OpenClaw / 远程部署用
npx tsx src/index.ts --http
# 输出：MCP HTTP server running on http://localhost:3111/mcp
```

| | stdio | Streamable HTTP |
|--|-------|-----------------|
| 谁启动 Server | Client 自动 spawn | 你手动启动 |
| 生命周期 | 随 Client 进程 | 独立运行 |
| 多 Client 连接 | 不行（1对1） | 可以（1对多） |
| 适用 Client | Claude Desktop、VS Code、Cursor | OpenClaw、Hermes、远程 |

### 4.3 验证 Server 是否正常工作

#### 方式 1：MCP Inspector（stdio 模式，推荐）

```bash
npx @modelcontextprotocol/inspector npx tsx src/index.ts
```

Inspector 自动 spawn server 子进程，通过 stdio 通信。浏览器打开 Inspector UI → 左侧可看到 `greet` tool 和 `hello://info` resource → 点击调用测试。

#### 方式 2：curl 验证 HTTP 模式

```bash
# 终端 1：启动 server
npx tsx src/index.ts --http

# 终端 2：发送 initialize 请求
curl -X POST http://localhost:3111/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"0.1.0"}}}'

# 应返回 200 + event: message + serverInfo JSON
```

> **注意**：MCP Inspector 对 Streamable HTTP 模式的支持取决于版本，某些版本可能连接失败。这是 Inspector 的兼容性问题，不代表 server 有 bug — 用 curl 验证 HTTP 模式，用 Inspector 验证 stdio 模式。实际 Agent 集成（VS Code Claude Code、Claude Desktop、OpenClaw）使用的是各自的 MCP Client 实现，不受 Inspector 限制。

### 4.4 接入 Agent 客户端

MCP Server 写好后，通过配置文件告诉 Client 如何启动它。不同 Client 的配置文件不同，但格式几乎一样：

#### VS Code Claude Code（项目级 `.mcp.json`）

在项目根目录创建 `.mcp.json`：

```json
// stdio 模式（Client 自动 spawn Server）
{
  "mcpServers": {
    "hello-mcp": {
      "command": "npx",
      "args": ["tsx", "/absolute/path/to/mcp-hello/src/index.ts"]
    }
  }
}
```

```json
// HTTP 模式（Server 已手动启动，Client 通过 URL 连接）
{
  "mcpServers": {
    "hello-mcp-http": {
      "url": "http://localhost:3111/mcp"
    }
  }
}
```
> Note: Failed!!!

新开 Claude Code 会话 → 会提示是否允许加载 → 确认后即可使用。修改 `.mcp.json` 后需重启 MCP 连接（输入 `/mcp` → restart）。

#### Claude Desktop（`~/.claude/claude_desktop_config.json`）

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

重启 Claude Desktop → Agent 自动发现你的 tool。

#### OpenClaw（`openclaw.json` 或 UI 配置）

```json
{
  "mcp": {
    "servers": {
      "hello-mcp": {
        "transport": "streamable-http",
        "url": "http://localhost:3111/mcp"
      }
    }
  }
}
```

⚠️ **重要配置说明**：
- **transport 必须是 `"streamable-http"`**，不能是 `"sse"`
  - OpenClaw 支持两种 transport：`"sse"` 和 `"streamable-http"`
  - 旧版 MCP SDK 使用 `SSEServerTransport`（已废弃），对应 `"sse"` 配置
  - 新版 MCP SDK (v1.29+) 使用 `StreamableHTTPServerTransport`，对应 `"streamable-http"` 配置
  - **配置与服务器实现必须匹配**，否则会出现连接超时或 500 错误
- **URL 必须包含完整路径**（如 `/mcp`），不能只写 `http://localhost:3111`
- OpenClaw 不支持 stdio transport，只支持 HTTP 模式

验证配置：
```bash
# 先启动 MCP Server
npx tsx src/index.ts --http

# 然后探测连接
openclaw mcp probe hello-mcp

# 应该输出：
# MCP probe (/path/to/openclaw.json):
# - hello-mcp: 1 tools, resources
```

#### Cursor（项目级 `.cursor/mcp.json`）

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

#### 各客户端配置对比

| 客户端 | 配置文件位置 | 传输方式 | 备注 |
|--------|-------------|---------|------|
| VS Code Claude Code | 项目根目录 `.mcp.json` | stdio / HTTP（`url` 字段） | HTTP 模式支持可能不完整 |
| Claude Desktop | `~/.claude/claude_desktop_config.json` | stdio | 仅 stdio |
| OpenClaw | `openclaw.json` 或 UI 配置 | Streamable HTTP | 必须用 `"transport": "streamable-http"` |
| Cursor | 项目根目录 `.cursor/mcp.json` | stdio | 仅 stdio |
| Hermes | `~/.hermes/config.yaml` | stdio / SSE | 取决于版本 |

格式几乎一样 — 同一个 MCP Server，换个配置文件就能接入不同 Client。这就是 MCP "框架无关"的好处。

> **注意**：Agent 会**自主决定**是否调用 tool。如果请求太简单（如 "greet Alice"），Agent 可能觉得自己能回答而不调用 tool。用 MCP Inspector 可以直接测试 tool 调用，不经过 Agent 判断。

---

## 5. 本项目 MCP Server 架构理解

### 5.1 入口 → 模块映射

```
packages/mcp-server/src/
├── index.ts              ← 启动入口：加载 config → 初始化 DB → 注册 tools/resources → 启动 worker
├── config.ts             ← YAML 配置解析
├── tools.ts              ← 8 个 MCP tool 注册（调用 @smartbuilding-video/tools 实现）
├── resources.ts          ← 4 个 MCP resource（monitors, latest-frame, stats, alerts）
├── events-endpoint.ts    ← HTTP webhook（接收 Python microservice 的事件推送）
└── video-worker/         ← 异步任务：轮询 DB → 调用 VLM → 写结果 → 触发 alert
```

### 5.2 与 OpenClaw Plugin 的关键差异

| 你在 OpenClaw Plugin 中做的 | 在 MCP Server 中的对应 |
|-----------------------------|----------------------|
| `definePluginEntry(api => {...})` | `main()` 函数里初始化 `McpServer` + `connect(transport)` |
| `api.registerTool("name", handler)` | `server.registerTool("name", { description, inputSchema }, handler)` |
| `api.runtime.session.append(...)` | 不需要 — Agent 框架自己处理 UI |
| `api.runtime.subagent.run(...)` | 不在 MCP Server 层 — 由 openclaw-adapter 桥接 |
| 读/写 OpenClaw FS | 直接操作本地文件系统或 DB |

### 5.3 数据流（完整链路）

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

## 6. 关键 SDK API 速查（v1.29+）

```typescript
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { ResourceTemplate } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

// 创建 Server
const server = new McpServer({ name: "my-server", version: "1.0.0" });

// ─── Tool（registerTool，替代已废弃的 server.tool）───
server.registerTool(
  "tool_name",
  {
    description: "What this tool does",
    inputSchema: { param: z.string().describe("参数说明") },  // Zod schema
  },
  async ({ param }) => ({
    content: [{ type: "text", text: `result: ${param}` }],
  })
);

// ─── Resource 静态 URI（registerResource，替代已废弃的 server.resource）───
server.registerResource(
  "resource-name",
  "myapp://info",
  { description: "Static resource" },
  async () => ({
    contents: [{ uri: "myapp://info", text: "data" }],
  })
);

// ─── Resource 动态 URI（带参数模板）───
server.registerResource(
  "monitor-alerts",
  new ResourceTemplate("smartbuilding://monitor/{id}/alerts", { list: undefined }),
  { description: "Alerts for a specific monitor" },
  async (uri, { id }) => ({
    contents: [{ uri: uri.href, text: JSON.stringify(getAlerts(id)) }],
  })
);

// ─── 推送通知（Resource Subscription）───
server.server.notification({
  method: "notifications/resources/updated",
  params: { uri: "smartbuilding://monitor/cam01/alerts" },
});

// ─── 连接传输层 ───
await server.connect(new StdioServerTransport());
```

> **注意**：SDK v1.29 废弃了 `server.tool()` 和 `server.resource()`，改用 `server.registerTool()` 和 `server.registerResource()`。旧 API 仍可用但会有 deprecated 警告。

### 6.1 返回值格式（协议固定）

MCP 协议规定了 Tool 和 Resource 的返回结构，所有 MCP Server 必须遵守，所有 Client 统一解析。

**Tool 返回** — `{ content: [...] }`：

```typescript
// 返回文本
{ content: [{ type: "text", text: "查询结果..." }] }

// 返回图片（base64）
{ content: [{ type: "image", data: "iVBOR...", mimeType: "image/png" }] }

// 返回多段内容（可混合类型）
{ content: [
    { type: "text", text: "分析结果：" },
    { type: "image", data: "...", mimeType: "image/jpeg" },
] }

// 标记失败
{ content: [{ type: "text", text: "Error: monitor not found" }], isError: true }
```

**Resource 返回** — `{ contents: [...] }`（注意多了个 s）：

```typescript
// 返回文本资源
{ contents: [{ uri: "smartbuilding://monitors", text: "[{...}, {...}]" }] }

// 返回二进制资源
{ contents: [{ uri: "smartbuilding://monitor/cam01/latest-frame", blob: "...", mimeType: "image/jpeg" }] }
```

**对比**：

| | Tool | Resource |
|--|------|----------|
| 字段名 | `content` | `contents`（多了 s） |
| 元素结构 | `{ type, text/data }` | `{ uri, text/blob }` |
| 支持类型 | text / image / resource | text / blob |
| 为什么不同 | 返回"执行结果" | 返回"资源数据"，需标明来源 URI |

类比：REST API 你可以自由定义返回 JSON；MCP 像 gRPC — 协议严格定义消息格式，所有参与方必须遵守。

---

## 7. 开发环境搭建

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

## 8. 推荐学习路径（1 周）

| Day | 目标 | 资源 |
|-----|------|------|
| 1 | 理解 MCP 协议全貌 | [MCP 官方文档](https://modelcontextprotocol.io/introduction)：读 Introduction + Core Concepts |
| 2 | 跑通 hello-mcp 示例 | 本文 §4 动手 Lab；用 Inspector 交互 |
| 3 | 读本项目 `index.ts` + `tools.ts` | 对照 §5 架构图，理解 wiring |
| 4 | 读 `video-worker/` + `events-endpoint.ts` | 理解异步任务链路和 webhook |
| 5 | 尝试添加一个新 tool | 参考 §9 实践任务 |
| 6 | 读 `resources.ts` + Resource Subscription | 理解推送机制 |
| 7 | 端到端：MCP Server + Inspector + Claude Desktop | 完整体验 Agent 调用 tool 的过程 |

---

## 9. 实践任务：添加一个新 Tool

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
server.registerTool(
  "smartbuilding_ping",
  { description: "Check server health and uptime" },  // 无 inputSchema = 无参数
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

## 10. 常见 Gotchas

| 坑 | 说明 | 解决 |
|----|------|------|
| **stdout 污染** | MCP stdio 模式下，Server 的 stdout 是协议通道。`console.log()` 会破坏 JSON-RPC 帧 | 一律用 `console.error()` 输出日志 |
| **Zod schema = JSON Schema** | `server.tool` 的第 3 参数必须是 Zod object（SDK 内部转 JSON Schema 发给 Client） | 不要传 raw JSON Schema |
| **异步初始化** | DB、config 必须在 `server.connect()` 前就绪 | 参考 `index.ts` 的顺序 |
| **HTTP stateless transport 复用** | Stateless 模式（`sessionIdGenerator: undefined`）下，**每个请求必须创建新的 server + transport 实例**。复用单一实例会导致"Already connected"错误或 500 错误 | 使用工厂函数 `createServer()`，在路由 handler 内部每次调用 |
| **只监听 POST 导致 404** | OpenClaw 使用 GET 建立 SSE 连接，如果只监听 `app.post("/mcp")`，GET 请求返回 404 | 使用 `app.all("/mcp")` 同时支持 GET 和 POST |
| **OpenClaw transport 配置错误** | 配置文件写 `"transport": "sse"` 但服务器用 `StreamableHTTPServerTransport` | 改为 `"transport": "streamable-http"`，必须与服务器实现匹配 |
| **req.body 是 undefined** | GET 请求没有 body，直接调用 `req.body.slice()` 等方法会崩溃 | 添加 `if (req.body)` 检查 |
| **使用 express() 而非 createMcpExpressApp()** | 手动创建的 express() 缺少 MCP 所需的中间件配置，可能导致 body parsing 或 CORS 问题 | 使用 SDK 提供的 `createMcpExpressApp()` |
| **Resource URI 规范** | 自定义 scheme（如 `smartbuilding://`）需要 Client 支持 `list_changed` | 当前 SDK 默认支持 |
| **热重载** | `tsx --watch` 会重启进程，Client 连接断开 | 开发时用 Inspector（每次手动连接） |

---

## 11. 故障排除指南

### 11.1 OpenClaw 连接问题诊断流程

#### 问题：`openclaw mcp probe hello-mcp` 失败

**症状分类与解决方案**：

| 错误信息 | 根本原因 | 解决方案 |
|---------|---------|---------|
| `SSE error: Non-200 status code (404)` | URL 路径错误或服务器未监听 GET | 检查 URL 是否包含 `/mcp`；确认代码用 `app.all()` 而非 `app.post()` |
| `SSE error: Non-200 status code (500)` | 服务器内部错误，通常是代码 bug | 查看服务器日志（stderr）；检查是否有未处理的异常 |
| `SSE error: Non-200 status code (400)` | 启用了 stateful 模式但客户端没提供 session ID | 改用 stateless：`sessionIdGenerator: undefined` |
| `MCP server connection timed out after 30000ms` | transport 配置类型不匹配 | OpenClaw 配置改为 `"transport": "streamable-http"` |
| `Error: Streamable HTTP error: Error POSTing to endpoint:` | 请求根本没到达服务器，或服务器崩溃 | 检查服务器是否在运行（`lsof -i :3111`）；查看服务器启动日志 |
| `TypeError: fetch failed` | 服务器未启动或端口错误 | 先启动服务器：`npx tsx src/index.ts --http` |

**调试步骤**：

```bash
# 1. 确认服务器正在运行
lsof -i :3111
# 应该看到 node 进程监听 3111 端口

# 2. 用 curl 直接测试服务器（绕过 OpenClaw）
curl -i -X POST http://localhost:3111/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"ping"}'

# 正常响应：
# HTTP/1.1 200 OK
# event: message
# data: {"result":{},"jsonrpc":"2.0","id":1}

# 3. 测试 initialize 方法（OpenClaw 的第一个请求）
curl -X POST http://localhost:3111/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}},"jsonrpc":"2.0","id":1}'

# 应返回 serverInfo 和 capabilities

# 4. 确认 OpenClaw 配置正确
openclaw mcp show hello-mcp
# 应显示 "transport": "streamable-http"

# 5. 最后才用 OpenClaw probe
openclaw mcp probe hello-mcp
```

### 11.2 常见代码错误

#### 错误 1：复用 transport 实例导致 "Already connected"

**错误代码**：
```typescript
// ❌ 错误：在外部创建 transport，所有请求复用
const app = express();
const transport = new StreamableHTTPServerTransport({
  sessionIdGenerator: undefined,
});
await server.connect(transport);  // 只 connect 一次

app.all("/mcp", async (req, res) => {
  // 第二个请求到来时，transport 已经 connected，报错
  await transport.handleRequest(req, res, req.body);
});
```

**正确代码**：
```typescript
// ✅ 正确：每个请求创建新 server + transport
app.all("/mcp", async (req, res) => {
  const server = createServer();  // 工厂函数
  const transport = new StreamableHTTPServerTransport({
    sessionIdGenerator: undefined,
  });
  await server.connect(transport);  // 每个请求都 connect
  await transport.handleRequest(req, res, req.body);
  
  res.on("close", () => {
    transport.close();
    server.close();
  });
});
```

#### 错误 2：只监听 POST 导致 OpenClaw GET 请求 404

**错误代码**：
```typescript
// ❌ 错误：只监听 POST，OpenClaw 的 GET（SSE 连接）返回 404
app.post("/mcp", async (req, res) => { ... });
```

**正确代码**：
```typescript
// ✅ 正确：同时支持 GET 和 POST
app.all("/mcp", async (req, res) => { ... });
```

#### 错误 3：OpenClaw 配置与服务器实现不匹配

**错误配置**：
```json
{
  "mcp": {
    "servers": {
      "hello-mcp": {
        "transport": "sse",  // ❌ 旧协议，与 StreamableHTTPServerTransport 不兼容
        "url": "http://localhost:3111"
      }
    }
  }
}
```

**正确配置**：
```json
{
  "mcp": {
    "servers": {
      "hello-mcp": {
        "transport": "streamable-http",  // ✅ 新协议
        "url": "http://localhost:3111/mcp"  // ✅ 包含完整路径
      }
    }
  }
}
```

### 11.3 日志调试技巧

在服务器代码中添加详细日志（使用 `console.error`，不影响 stdio 协议）：

```typescript
app.all("/mcp", async (req, res) => {
  console.error(`[mcp] ${req.method} ${req.url}`);
  console.error(`[mcp] Headers:`, JSON.stringify(req.headers));
  if (req.body) {
    console.error(`[mcp] Body:`, JSON.stringify(req.body).slice(0, 500));
  }
  
  try {
    const server = createServer();
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: undefined,
    });
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
    
    res.on("close", () => {
      console.error("[mcp] Request closed");
      transport.close();
      server.close();
    });
  } catch (error) {
    console.error("[mcp] Error:", error);
    console.error("[mcp] Stack:", error instanceof Error ? error.stack : "N/A");
    // ...
  }
});
```

查看日志：
```bash
# 服务器日志输出到 stderr，用 2>&1 捕获
npx tsx src/index.ts --http 2>&1 | tee server.log

# 或者后台运行并查看日志
npx tsx src/index.ts --http > server.log 2>&1 &
tail -f server.log
```

### 11.4 MCP Inspector vs OpenClaw 的差异

| 工具 | 传输方式 | 适用场景 | 限制 |
|------|---------|---------|------|
| MCP Inspector | stdio（spawn 子进程） | 测试 stdio 模式服务器 | 某些版本对 HTTP 模式支持不完整 |
| curl | HTTP | 直接测试 HTTP 协议层 | 需要手动构造 JSON-RPC 消息 |
| OpenClaw | HTTP (Streamable HTTP) | 测试实际集成 | 需要正确的 transport 配置 |

**推荐验证流程**：
1. **先用 Inspector 验证 stdio 模式** → 确认 tools/resources 注册正确
2. **再用 curl 验证 HTTP 模式** → 确认协议层通信正常
3. **最后用 OpenClaw probe** → 确认实际客户端集成成功

---

## 12. 参考资料

| 资源 | 链接/路径 |
|------|-----------|
| MCP 官方规范 | https://modelcontextprotocol.io/specification |
| MCP TypeScript SDK | https://github.com/modelcontextprotocol/typescript-sdk |
| MCP Inspector | `npx @modelcontextprotocol/inspector` |
| 本项目设计文档 | `agent-ai.smarthome/docs/design/smartbuilding-video-design-2026.2.md` |
| 本项目 MCP Server 源码 | `packages/mcp-server/src/` |
| 本项目测试 | `tests/dev-mcp-server/` |
| MCP Server 示例集合 | https://github.com/modelcontextprotocol/servers |
