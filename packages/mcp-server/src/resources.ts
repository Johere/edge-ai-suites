import { McpServer, ResourceTemplate } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { ServerConfig } from "./config.js";
import type { SmartBuildingDB } from "@smartbuilding-video/db";

export function registerResources(server: McpServer, config: ServerConfig, db: SmartBuildingDB): void {
  server.resource(
    "monitors-list",
    "smartbuilding://monitors",
    { description: "All monitors with online status" },
    async (uri) => {
      const monitors = db.listMonitors();
      return {
        contents: [{
          uri: uri.href,
          mimeType: "application/json",
          text: JSON.stringify({ monitors }, null, 2),
        }],
      };
    }
  );

  server.resource(
    "monitor-latest-frame",
    new ResourceTemplate("smartbuilding://monitor/{id}/latest-frame", { list: undefined }),
    { description: "Latest frame (base64 JPEG) for a monitor" },
    async (uri, variables) => {
      const id = variables.id as string;
      return {
        contents: [{
          uri: uri.href,
          mimeType: "application/json",
          text: JSON.stringify({ monitorId: id, frame: null, note: "Requires videostream-analytics integration" }),
        }],
      };
    }
  );

  server.resource(
    "monitor-stats",
    new ResourceTemplate("smartbuilding://monitor/{id}/stats", { list: undefined }),
    { description: "Today's event/alert statistics for a monitor" },
    async (uri, variables) => {
      const id = variables.id as string;
      const stats = db.getStats(id);
      return {
        contents: [{
          uri: uri.href,
          mimeType: "application/json",
          text: JSON.stringify({ monitorId: id, ...stats }, null, 2),
        }],
      };
    }
  );

  server.resource(
    "monitor-alerts",
    new ResourceTemplate("smartbuilding://monitor/{id}/alerts", { list: undefined }),
    { description: "Recent alerts for a monitor" },
    async (uri, variables) => {
      const id = variables.id as string;
      const alerts = db.queryAlerts({ sourceId: id, limit: 20 });
      return {
        contents: [{
          uri: uri.href,
          mimeType: "application/json",
          text: JSON.stringify({ monitorId: id, alerts }, null, 2),
        }],
      };
    }
  );
}
