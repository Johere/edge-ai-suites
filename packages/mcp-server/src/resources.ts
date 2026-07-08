import { McpServer, ResourceTemplate } from "@modelcontextprotocol/sdk/server/mcp.js";
import {
  SubscribeRequestSchema,
  UnsubscribeRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import type { ServerConfig } from "./config.js";
import type { SmartBuildingDB } from "@smartbuilding-video/db";
import type { McpSubscriberRegistry } from "./mcp-subscriber-registry.js";
import { logger } from "./logger.js";

/**
 * Register MCP resources and (if a subscriber registry is provided) the subscribe/unsubscribe
 * request handlers so the McpServer can advertise `resources.subscribe: true` and update the
 * registry when a client subscribes.
 *
 * `sessionId` identifies the caller in the registry — pass "stdio" for the stdio singleton or
 * the streamable-HTTP session id for HTTP sessions.
 */
export function registerResources(
  server: McpServer,
  _config: ServerConfig,
  db: SmartBuildingDB,
  registry?: McpSubscriberRegistry,
  sessionId?: string,
): void {
  server.registerResource("monitors-list", "smartbuilding://monitors", {
    description: "All monitors with online status",
  }, async (uri) => {
    const monitors = db.listMonitors();
    return {
      contents: [{
        uri: uri.href,
        mimeType: "application/json",
        text: JSON.stringify({ monitors }, null, 2),
      }],
    };
  });

  server.registerResource(
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

  server.registerResource(
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

  // Cursor-read variant — MUST be registered BEFORE the bare template so the SDK's template
  // matcher (iterates insertion order) tries this first. `{?since}` is required by the pattern
  // (not optional in this SDK's UriTemplate), so we need two separate registrations.
  server.registerResource(
    "monitor-alerts-since",
    new ResourceTemplate("smartbuilding://monitor/{id}/alerts{?since}", { list: undefined }),
    { description: "Alerts for a monitor with id strictly greater than the ?since= cursor." },
    async (uri, variables) => {
      const id = variables.id as string;
      const sinceRaw = variables.since as string | undefined;
      const sinceId = sinceRaw !== undefined ? Number(sinceRaw) : NaN;
      if (!Number.isInteger(sinceId) || sinceId < 0) {
        throw new Error(`Invalid ?since= value: "${sinceRaw}" (must be a non-negative integer)`);
      }
      const alerts = db.queryAlerts({ monitorId: id, sinceId, limit: 200 });
      const latestId = alerts.length > 0
        ? Math.max(...alerts.map((a) => a.id))
        : sinceId; // no new alerts — cursor stays put
      return {
        contents: [{
          uri: uri.href,
          mimeType: "application/json",
          text: JSON.stringify({ monitorId: id, latestId, alerts }, null, 2),
        }],
      };
    }
  );

  server.registerResource(
    "monitor-alerts",
    new ResourceTemplate("smartbuilding://monitor/{id}/alerts", { list: undefined }),
    {
      description:
        "Recent alerts for a monitor (latest 20). Response includes `latestId` for cursor-based clients; use `smartbuilding://monitor/{id}/alerts?since={id}` for incremental reads.",
    },
    async (uri, variables) => {
      const id = variables.id as string;
      const alerts = db.queryAlerts({ monitorId: id, limit: 20 });
      const latestId = db.getLatestAlertId(id);
      return {
        contents: [{
          uri: uri.href,
          mimeType: "application/json",
          text: JSON.stringify({ monitorId: id, latestId, alerts }, null, 2),
        }],
      };
    }
  );

  // Subscribe / unsubscribe wiring — only when a registry + sessionId are supplied by the caller.
  if (registry && sessionId) {
    // Advertise capability so clients know this server supports `resources/subscribe`.
    // McpServer's own registerCapabilities enables listChanged but not subscribe.
    server.server.registerCapabilities({ resources: { subscribe: true } });

    server.server.setRequestHandler(SubscribeRequestSchema, async (request) => {
      const uri = request.params.uri;
      registry.addSubscription(sessionId, uri);
      logger.debug(`[mcp] session=${sessionId} subscribed to ${uri}`);
      return {};
    });

    server.server.setRequestHandler(UnsubscribeRequestSchema, async (request) => {
      const uri = request.params.uri;
      registry.removeSubscription(sessionId, uri);
      logger.debug(`[mcp] session=${sessionId} unsubscribed from ${uri}`);
      return {};
    });
  }
}
