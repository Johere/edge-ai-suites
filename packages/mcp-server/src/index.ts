import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { SmartBuildingDB, SchemaManager } from "@smartbuilding-video/db";
import { registerTools } from "./tools.js";
import { registerResources } from "./resources.js";
import { loadConfig, type ServerConfig } from "./config.js";
import { WorkerService } from "./video-worker/index.js";
import { EventsEndpoint } from "./events-endpoint.js";
import express from "express";
import cors from "cors";

async function main() {
  const configPath = process.argv.includes("--config")
    ? process.argv[process.argv.indexOf("--config") + 1]
    : undefined;

  const transportMode = process.argv.includes("--http") ? "http" : "stdio";

  const config: ServerConfig = loadConfig(configPath);

  // Ensure DB directory exists
  mkdirSync(dirname(config.db.path), { recursive: true });

  // Initialize database
  const db = new SmartBuildingDB(config.db.path);
  db.initialize();

  // Apply schema customization if defined
  if (config.schema) {
    const schemaManager = new SchemaManager((db as any).db);
    const result = schemaManager.applySchema(config.schema);
    if (result.added.length > 0) {
      console.error(`[schema] Added columns: ${result.added.join(", ")}`);
    }
    if (result.warnings.length > 0) {
      console.error(`[schema] Warnings: ${result.warnings.join(", ")}`);
    }
  }

  // Create MCP server
  const server = new McpServer({
    name: "smartbuilding-video",
    version: "0.1.0",
  });

  // Alert callback: notify MCP resource subscribers
  const onAlert = (monitorId: string) => {
    server.server.notification({
      method: "notifications/resources/updated",
      params: { uri: `smartbuilding://monitor/${monitorId}/alerts` },
    });
  };

  // Initialize worker service
  const workerService = new WorkerService(config, db, onAlert);

  // Register tools and resources
  registerTools(server, config, db, workerService);
  registerResources(server, config, db);

  // Connect transport
  if (transportMode === "http") {
    const app = express();
    app.use(cors());
    app.use(express.json());

    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: undefined,
    });

    await server.connect(transport);

    app.all("/mcp", async (req, res) => {
      try {
        await transport.handleRequest(req, res, req.body);
      } catch (err) {
        console.error("[mcp] error:", err);
        if (!res.headersSent) res.status(500).json({ error: String(err) });
      }
    });

    const port = config.mcp?.port ?? 3100;
    app.listen(port, () => {
      console.error(`[mcp-server] Streamable HTTP on http://localhost:${port}/mcp`);
    });
  } else {
    const transport = new StdioServerTransport();
    await server.connect(transport);
  }

  // Start events webhook endpoint
  const eventsEndpoint = new EventsEndpoint(config, db, (event) => {
    server.server.notification({
      method: "notifications/resources/updated",
      params: { uri: `smartbuilding://monitor/${event.sourceId}/stats` },
    });
  });
  await eventsEndpoint.start(3101);

  // Graceful shutdown
  process.on("SIGINT", () => {
    workerService.stopAll();
    eventsEndpoint.stop();
    db.close();
    process.exit(0);
  });
}

main().catch((err) => {
  console.error("MCP Server failed to start:", err);
  process.exit(1);
});
