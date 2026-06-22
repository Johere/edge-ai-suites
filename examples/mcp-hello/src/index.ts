import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { z } from "zod";
import express from "express";
import cors from "cors";

const server = new McpServer({ name: "hello-mcp", version: "0.1.0" });

// 函数实现
/*
    MCP SDK 要求返回特定结构:  { content: [{ type, text }] }, e.g.:
    {
        "content": [
            { "type": "text", "text": "Hello, Alice!" }
        ]
    }
*/
async function handleGreet({ name }: { name: string }) {
  return { content: [{ type: "text" as const, text: `Hello, ${name}! (I know you!! hiahiahiahiahia)` }] };
}

// 注册一个 Tool（类比 api.registerTool）
server.registerTool(
  "greet",
  { description: "Say hello", inputSchema: { name: z.string() } },
  handleGreet
);

// 注册一个 Resource（类比只读 API）
/* 函数返回值示例：
    {
    "contents": [
        { "uri": "hello://info", "text": "This server is running." }
    ]
    }
*/
server.registerResource(
  "server-info",
  "hello://info",
  { description: "Server status information" },
  async () => ({
    contents: [{ uri: "hello://info", text: "This server is running." }],
  })
);

// ─── 根据命令行参数选择传输方式 ───
const args = process.argv.slice(2);
const transportMode = args.includes("--http") ? "http" : "stdio";

if (transportMode === "http") {
  // Streamable HTTP 模式：启动 HTTP 服务器，等待 Client 连接
  // 适用于 OpenClaw、远程部署、多 Client 同时连接
  // （替代已废弃的 SSEServerTransport）
  const app = express();
  app.use(cors());
  app.use(express.json());

  app.all("/mcp", async (req, res) => {
    try {
      const transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: undefined,
      });
      await server.connect(transport);
      await transport.handleRequest(req, res, req.body);
    } catch (err) {
      console.error("[mcp] handleRequest error:", err);
      if (!res.headersSent) res.status(500).json({ error: String(err) });
    }
  });

  const port = 3100;
  app.listen(port, () => {
    console.error(`MCP HTTP server running on http://localhost:${port}/mcp`);
  });
} else {
  // stdio 模式：Client 自动 spawn 本进程，通过 stdin/stdout 通信
  // 适用于 Claude Desktop、VS Code Claude Code、Cursor
  const transport = new StdioServerTransport();
  await server.connect(transport);
}
