import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { ServerConfig } from "./config.js";

export function registerResources(server: McpServer, config: ServerConfig): void {
  server.resource(
    "monitors-list",
    "smartbuilding://monitors",
    { description: "All monitors with online status" },
    async (uri) => {
      // TODO: fetch monitor list from DB
      return {
        contents: [{
          uri: uri.href,
          mimeType: "application/json",
          text: JSON.stringify({ monitors: [] }),
        }],
      };
    }
  );

  server.resource(
    "monitor-latest-frame",
    "smartbuilding://monitor/{id}/latest-frame",
    { description: "Latest frame (base64 JPEG) for a monitor" },
    async (uri, { id }) => {
      // TODO: fetch latest frame
      return {
        contents: [{
          uri: uri.href,
          mimeType: "application/json",
          text: JSON.stringify({ frame: null }),
        }],
      };
    }
  );

  server.resource(
    "monitor-stats",
    "smartbuilding://monitor/{id}/stats",
    { description: "Today's event/alert statistics for a monitor" },
    async (uri, { id }) => {
      // TODO: fetch stats from DB
      return {
        contents: [{
          uri: uri.href,
          mimeType: "application/json",
          text: JSON.stringify({ events: 0, alerts: 0 }),
        }],
      };
    }
  );

  server.resource(
    "monitor-alerts",
    "smartbuilding://monitor/{id}/alerts",
    { description: "Recent alerts for a monitor" },
    async (uri, { id }) => {
      // TODO: fetch alerts from DB
      return {
        contents: [{
          uri: uri.href,
          mimeType: "application/json",
          text: JSON.stringify({ alerts: [] }),
        }],
      };
    }
  );
}
