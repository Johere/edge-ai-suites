import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { createMcpExpressApp } from "@modelcontextprotocol/sdk/server/express.js";
import { z } from "zod";

// 创建服务器实例的工厂函数（无状态模式下每个请求创建新实例）
function createServer() {
  const server = new McpServer({ name: "hello-mcp", version: "0.1.0" });

  // 注册一个 Tool
  server.registerTool(
    "greet",
    { description: "Say hello", inputSchema: { name: z.string() } },
    async ({ name }: { name: string }) => {
      return { content: [{ type: "text" as const, text: `Hello, ${name}! (I know you!! hiahiahiahiahia)` }] };
    }
  );

  // 注册一个 Resource
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
  const app = createMcpExpressApp();

  app.all("/mcp", async (req, res) => {
    const server = createServer();
    console.error(`[mcp] ${req.method} /mcp - Accept: ${req.headers.accept}`);
    if (req.body) {
      console.error(`[mcp] Body:`, JSON.stringify(req.body).slice(0, 200));
    } else {
      console.error(`[mcp] No body (likely GET for SSE)`);
    }

    try {
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
      console.error("[mcp] Error handling request:", error);
      if (!res.headersSent) {
        res.status(500).json({
          jsonrpc: "2.0",
          error: {
            code: -32603,
            message: "Internal server error",
          },
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
  const server = createServer();
  const transport = new StdioServerTransport();
  await server.connect(transport);
}
