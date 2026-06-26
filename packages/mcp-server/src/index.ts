import { mkdirSync } from "node:fs";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { createMcpExpressApp } from "@modelcontextprotocol/sdk/server/express.js";
import { SmartBuildingDB, SchemaManager } from "@smartbuilding-video/db";
import { registerTools } from "./tools.js";
import { registerResources } from "./resources.js";
import { loadConfig, loadMonitorsConfig, type ServerConfig } from "./config.js";
import { WorkerService } from "./video-worker/index.js";
import { EventsEndpoint } from "./events-endpoint.js";
import { logger } from "./logger.js";
import { autoRegisterMonitors } from "./monitor-bootstrap.js";
import { startStorageCleaner } from "./storage-cleaner.js";

/**
 * Build a per-request McpServer. HTTP stateless mode calls this for every request;
 * stdio mode calls it once. DB / config / workerService are shared across instances.
 */
function createMcpServer(
  config: ServerConfig,
  db: SmartBuildingDB,
  workerService: WorkerService,
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

  const monitorsPath = process.argv.includes("--monitors")
    ? process.argv[process.argv.indexOf("--monitors") + 1]
    : undefined;

  const transportMode = process.argv.includes("--http") ? "http" : "stdio";

  const config: ServerConfig = loadConfig(configPath);

  if (monitorsPath) {
    try {
      config.monitors = loadMonitorsConfig(monitorsPath);
      logger.info(`[config] loaded ${Object.keys(config.monitors).length} monitor(s) from ${monitorsPath}`);

      // Reference integrity: every monitor.use_case must exist in config.useCaseDict
      const knownUseCases = Object.keys(config.useCaseDict);
      const badRefs: string[] = [];
      for (const [id, m] of Object.entries(config.monitors)) {
        if (!knownUseCases.includes(m.use_case)) {
          badRefs.push(`${id} → "${m.use_case}"`);
        }
      }
      if (badRefs.length > 0) {
        throw new Error(
          `monitors reference unknown use_case keys: [${badRefs.join(", ")}]. ` +
          `Declared in config.yaml use_case_dict: [${knownUseCases.join(", ")}]`,
        );
      }
    } catch (err: any) {
      logger.error(`[config] failed to load --monitors ${monitorsPath}: ${err.message}`);
      process.exit(1);
    }
  }

  mkdirSync(config.dataDir, { recursive: true });
  mkdirSync(config.segmentsDir, { recursive: true });
  mkdirSync(config.reportsLogsDir, { recursive: true });
  mkdirSync(config.monitorsLogsDir, { recursive: true });

  const db = new SmartBuildingDB(config.dbPath);
  db.initialize();

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

  const workerService = new WorkerService(config, db, onAlert);

  let mcpServer: McpServer | null = null;

  if (transportMode === "http") {
    const app = createMcpExpressApp();

    // Stateless HTTP: new server + transport per request.
    app.all("/mcp", async (req, res) => {
      logger.debug(`[mcp] ${req.method} /mcp`);

      const server = createMcpServer(config, db, workerService);

      try {
        const transport = new StreamableHTTPServerTransport({
          sessionIdGenerator: undefined,  // stateless
        });
        await server.connect(transport);
        await transport.handleRequest(req, res, req.body);

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

  } else {
    // stdio: single stateful server instance
    mcpServer = createMcpServer(config, db, workerService);
    const transport = new StdioServerTransport();
    await mcpServer.connect(transport);
  }

  const eventsEndpoint = new EventsEndpoint(db);
  await eventsEndpoint.start(config.eventsWebhook!.port);

  // Clean up state from previous crash (analytics sources that DB doesn't know about, etc.)
  await reconcileOnStartup(db, config.videostreamAnalytics.url);

  await autoRegisterMonitors(db, config, workerService);

  // Periodic disk cleanup: logs/monitors + segments/<id>/{recordings,motion_events,queries}
  const stopCleaner = startStorageCleaner(config);

  const shutdown = async () => {
    logger.info("[mcp-server] Shutting down...");
    stopCleaner();
    await workerService.stopAll();
    const onlineMonitors = db.listOnlineMonitors();
    if (onlineMonitors.length > 0) {
      logger.info(`[shutdown] Pausing ${onlineMonitors.length} online monitors in videostream-analytics (${config.videostreamAnalytics.url})`);
      await Promise.all(onlineMonitors.map((m) =>
        fetch(`${config.videostreamAnalytics.url}/sources/${m.id}/pause`, {
          method: "POST", signal: AbortSignal.timeout(3000),
        }).catch(() => {})
      ));
      for (const m of onlineMonitors) db.updateMonitorStatus(m.id, "offline");
    }
    eventsEndpoint.stop();
    db.close();
    process.exit(0);
  };

  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}

async function reconcileOnStartup(
  db: SmartBuildingDB,
  analyticsUrl: string,
): Promise<void> {
  let analyticsSources: Map<string, unknown>;
  try {
    const resp = await fetch(`${analyticsUrl}/sources`, { signal: AbortSignal.timeout(5000) });
    if (!resp.ok) {
      logger.warn(`[reconcile] videostream-analytics (${analyticsUrl}) returned HTTP ${resp.status} — skipping startup reconciliation`);
      return;
    }
    const list = (await resp.json()) as any[];
    analyticsSources = new Map(list.map((s: any) => [s.source_id, s]));
  } catch {
    logger.warn(`[reconcile] videostream-analytics (${analyticsUrl}) unreachable — skipping startup reconciliation`);
    return;
  }

  let offlined = 0;
  let deleted = 0;

  // DB-marked-online monitors are crash remnants: mark offline so register_source restarts them.
  const onlineMonitors = db.listOnlineMonitors();
  for (const m of onlineMonitors) {
    if (analyticsSources.has(m.id)) {
      await fetch(`${analyticsUrl}/sources/${m.id}`, { method: "DELETE", signal: AbortSignal.timeout(5000) }).catch(() => {});
      logger.warn(`[reconcile] monitor ${m.id} found in videostream-analytics (${analyticsUrl}) on startup, deleted and marked offline — call register_source to restart`);
    } else {
      logger.warn(`[reconcile] monitor ${m.id} not found in videostream-analytics (${analyticsUrl}) after restart, marked offline — call register_source to restart`);
    }
    db.updateMonitorStatus(m.id, "offline");
    offlined++;
  }

  // Orphans (in analytics but not DB): DB is source of truth.
  const dbIds = new Set(db.listMonitors().map((m) => m.id));
  for (const sourceId of analyticsSources.keys()) {
    if (!dbIds.has(sourceId)) {
      await fetch(`${analyticsUrl}/sources/${sourceId}`, { method: "DELETE", signal: AbortSignal.timeout(5000) }).catch(() => {
        logger.warn(`[reconcile] failed to delete orphan source ${sourceId} from videostream-analytics (${analyticsUrl})`);
      });
      logger.info(`[reconcile] deleted orphan source ${sourceId} from videostream-analytics (${analyticsUrl})`);
      deleted++;
    }
  }

  logger.info(`[reconcile] complete: ${offlined} marked offline, ${deleted} orphans deleted`);
}

main().catch((err) => {
  logger.error(`MCP Server failed to start: ${err}`);
  process.exit(1);
});
