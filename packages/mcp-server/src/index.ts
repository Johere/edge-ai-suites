import { mkdirSync } from "node:fs";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { createMcpExpressApp } from "@modelcontextprotocol/sdk/server/express.js";
import { SmartBuildingDB, SchemaManager } from "@smartbuilding-video/db";
import { registerTools } from "./tools.js";
import { registerResources } from "./resources.js";
import { loadConfig, type ServerConfig } from "./config.js";
import { WorkerService } from "./video-worker/index.js";
import { EventsEndpoint } from "./events-endpoint.js";
import { logger } from "./logger.js";

/**
 * 创建 MCP server 实例的工厂函数。
 * HTTP 无状态模式下，每个请求需要新的 server 实例。
 * 但 DB、config、workerService 等基础设施在所有请求间共享。
 */
function createMcpServer(
  config: ServerConfig,
  db: SmartBuildingDB,
  workerService: WorkerService,
  onAlert: (monitorId: string) => void
): McpServer {
  const server = new McpServer({
    name: "smartbuilding-video",
    version: "0.1.0",
  });

  registerTools(server, config, db, workerService);
  registerResources(server, config, db);

  return server;
}

async function main() {
  const configPath = process.argv.includes("--config")
    ? process.argv[process.argv.indexOf("--config") + 1]
    : undefined;

  const transportMode = process.argv.includes("--http") ? "http" : "stdio";

  const config: ServerConfig = loadConfig(configPath);

  // Ensure data directories exist
  mkdirSync(config.dataDir, { recursive: true });
  mkdirSync(config.segmentsDir, { recursive: true });
  mkdirSync(config.logsDir, { recursive: true });

  // Initialize database
  const db = new SmartBuildingDB(config.dbPath);
  db.initialize();

  // Apply schema customization if defined
  if (config.schema) {
    const schemaManager = new SchemaManager((db as any).db);
    const result = schemaManager.applySchema(config.schema);
    if (result.added.length > 0) {
      logger.info(`[schema] Added columns: ${result.added.join(", ")}`);
    }
    if (result.warnings.length > 0) {
      logger.warn(`[schema] ${result.warnings.join(", ")}`);
    }
  }

  const onAlert = (monitorId: string) => {
    logger.debug(`[worker] Alert triggered for monitor ${monitorId}`);
  };

  // Initialize worker service
  const workerService = new WorkerService(config, db, onAlert);

  // Connect transport
  let mcpServer: McpServer | null = null;

  if (transportMode === "http") {
    // ⚠️ 使用 SDK 提供的 Express app，自动配置了必要的中间件
    const app = createMcpExpressApp();

    // ⚠️ 关键：每个请求创建新的 server + transport（无状态模式）
    app.all("/mcp", async (req, res) => {
      logger.debug(`[mcp] ${req.method} /mcp`);

      // 为每个请求创建独立的 server 实例
      const server = createMcpServer(config, db, workerService, onAlert);

      try {
        const transport = new StreamableHTTPServerTransport({
          sessionIdGenerator: undefined,  // 无状态模式
        });
        await server.connect(transport);
        await transport.handleRequest(req, res, req.body);

        // 请求结束时清理资源
        res.on("close", () => {
          logger.debug("[mcp] Request closed");
          transport.close();
          server.close();
        });
      } catch (error) {
        logger.error(`[mcp] ${error}`);
        if (!res.headersSent) {
          res.status(500).json({
            jsonrpc: "2.0",
            error: { code: -32603, message: "Internal server error" },
            id: null,
          });
        }
      }
    });

    const port = config.mcp!.port;
    app.listen(port, () => {
      logger.info(`[mcp-server] Streamable HTTP on http://localhost:${port}/mcp`);
    });

    // HTTP 无状态模式下，无法跨请求发送 notification
    // eventsEndpoint 的回调只记录日志
  } else {
    // stdio 模式：可以使用单一 server 实例（有状态）
    mcpServer = createMcpServer(config, db, workerService, onAlert);
    const transport = new StdioServerTransport();
    await mcpServer.connect(transport);
  }

  // Start events webhook endpoint
  const eventsEndpoint = new EventsEndpoint(config, db, (event) => {
    // 只在 stdio 模式下发送 notification（有状态连接）
    if (mcpServer) {
      mcpServer.server.notification({
        method: "notifications/resources/updated",
        params: { uri: `smartbuilding://monitor/${event.sourceId}/stats` },
      });
    } else {
      // HTTP 无状态模式：无法主动推送，客户端需轮询 resources
      logger.debug(`[webhook] Stats updated for ${event.sourceId} (notification skipped in HTTP mode)`);
    }
  });
  await eventsEndpoint.start(config.eventsWebhook!.port);

  // Graceful shutdown
  process.on("SIGINT", () => {
    workerService.stopAll();
    eventsEndpoint.stop();
    db.close();
    process.exit(0);
  });
}

main().catch((err) => {
  logger.error(`MCP Server failed to start: ${err}`);
  process.exit(1);
});
