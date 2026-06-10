import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import type { ServerConfig } from "./config.js";
import type { SmartBuildingDB, Alert } from "@smartbuilding-video/db";
import type { WorkerService } from "./video-worker/index.js";

export function registerTools(
  server: McpServer,
  config: ServerConfig,
  db: SmartBuildingDB,
  workerService: WorkerService,
): void {
  server.tool(
    "smartbuilding_alert_query",
    "Query or acknowledge alerts",
    {
      monitor_id: z.string().optional().describe("Filter by monitor ID"),
      status: z.enum(["unacked", "acked", "all"]).optional().describe("Alert status filter"),
      limit: z.number().optional().describe("Max results to return"),
      ack_id: z.number().optional().describe("Alert ID to acknowledge (mutually exclusive with query)"),
    },
    async (params) => {
      if (params.ack_id !== undefined) {
        db.ackAlert(params.ack_id);
        return { content: [{ type: "text" as const, text: `Alert ${params.ack_id} acknowledged.` }] };
      }

      const acked = params.status === "acked" ? true : params.status === "unacked" ? false : undefined;
      const alerts = db.queryAlerts({
        sourceId: params.monitor_id,
        acked,
        limit: params.limit ?? 50,
      });
      return { content: [{ type: "text" as const, text: JSON.stringify(alerts, null, 2) }] };
    }
  );

  server.tool(
    "smartbuilding_state_query",
    "Read or write monitor state",
    {
      monitor_id: z.string().describe("Monitor ID"),
      action: z.enum(["get", "set"]).describe("Read or write state"),
      state: z.record(z.unknown()).optional().describe("State to set (for action=set)"),
    },
    async (params) => {
      if (params.action === "set") {
        if (!params.state) {
          return { content: [{ type: "text" as const, text: "Error: state is required for action=set" }], isError: true };
        }
        db.setState(params.monitor_id, params.state);
        return { content: [{ type: "text" as const, text: "State updated." }] };
      }
      const state = db.getState(params.monitor_id);
      return { content: [{ type: "text" as const, text: JSON.stringify(state, null, 2) }] };
    }
  );

  server.tool(
    "smartbuilding_scene_query",
    "Real-time VLM scene analysis for a monitor",
    {
      monitor_id: z.string().describe("Monitor ID"),
      question: z.string().optional().describe("Specific question about the scene"),
    },
    async (params) => {
      // Requires video-worker's VLM client to capture current frame and query
      const monitor = db.getMonitor(params.monitor_id);
      if (!monitor) {
        return { content: [{ type: "text" as const, text: `Monitor ${params.monitor_id} not found.` }], isError: true };
      }
      // TODO: capture frame from videostream-analytics, send to VLM with question
      return { content: [{ type: "text" as const, text: "Scene query not yet implemented — requires live frame capture from videostream-analytics." }] };
    }
  );

  server.tool(
    "smartbuilding_daily_report",
    "Generate daily report for a monitor",
    {
      monitor_id: z.string().describe("Monitor ID"),
      date: z.string().optional().describe("Date in YYYY-MM-DD format (defaults to today)"),
    },
    async (params) => {
      const date = params.date ?? new Date().toISOString().slice(0, 10);
      const alerts = db.queryAlerts({ sourceId: params.monitor_id });
      const dayAlerts = alerts.filter((a: Alert) => a.createdAt.startsWith(date));
      const stats = db.getStats(params.monitor_id);

      const report = {
        monitorId: params.monitor_id,
        date,
        totalEvents: stats.events,
        totalAlerts: dayAlerts.length,
        alertBreakdown: dayAlerts.reduce((acc: Record<string, number>, a: Alert) => {
          acc[a.event] = (acc[a.event] || 0) + 1;
          return acc;
        }, {} as Record<string, number>),
        unackedAlerts: dayAlerts.filter((a: Alert) => !a.acked).length,
      };
      return { content: [{ type: "text" as const, text: JSON.stringify(report, null, 2) }] };
    }
  );

  server.tool(
    "smartbuilding_monitor_ctl",
    "Start, stop, or register video sources",
    {
      action: z.enum(["start", "stop", "register_source", "list"]).describe("Control action"),
      monitor_id: z.string().optional().describe("Monitor ID (required for start/stop)"),
      source_url: z.string().optional().describe("RTSP URL or file path (for register_source)"),
      name: z.string().optional().describe("Display name (for register_source)"),
      use_case_id: z.string().optional().describe("Use case identifier (for register_source)"),
    },
    async (params) => {
      switch (params.action) {
        case "list": {
          const monitors = db.listMonitors();
          return { content: [{ type: "text" as const, text: JSON.stringify(monitors, null, 2) }] };
        }
        case "register_source": {
          if (!params.source_url || !params.monitor_id) {
            return { content: [{ type: "text" as const, text: "Error: monitor_id and source_url are required for register_source" }], isError: true };
          }
          const monitor = db.createMonitor({
            id: params.monitor_id,
            name: params.name ?? params.monitor_id,
            sourceUrl: params.source_url,
            status: "offline",
            useCaseId: params.use_case_id ?? "default",
          });
          return { content: [{ type: "text" as const, text: `Monitor registered: ${JSON.stringify(monitor)}` }] };
        }
        case "start": {
          if (!params.monitor_id) {
            return { content: [{ type: "text" as const, text: "Error: monitor_id required" }], isError: true };
          }
          db.updateMonitorStatus(params.monitor_id, "online");
          workerService.start(params.monitor_id);
          return { content: [{ type: "text" as const, text: `Monitor ${params.monitor_id} started.` }] };
        }
        case "stop": {
          if (!params.monitor_id) {
            return { content: [{ type: "text" as const, text: "Error: monitor_id required" }], isError: true };
          }
          db.updateMonitorStatus(params.monitor_id, "offline");
          workerService.stop(params.monitor_id);
          return { content: [{ type: "text" as const, text: `Monitor ${params.monitor_id} stopped.` }] };
        }
      }
    }
  );

  server.tool(
    "smartbuilding_rule_eval",
    "Manually trigger rule evaluation for a monitor",
    {
      monitor_id: z.string().describe("Monitor ID"),
    },
    async (params) => {
      // TODO: trigger rule evaluation via rule-engine package
      return { content: [{ type: "text" as const, text: `Rule evaluation triggered for ${params.monitor_id}. (Implementation pending rule-engine integration)` }] };
    }
  );

  server.tool(
    "smartbuilding_video_db",
    "Low-level database query",
    {
      query: z.string().describe("SQL query to execute"),
      params: z.array(z.unknown()).optional().describe("Query parameters"),
    },
    async (params) => {
      try {
        const results = db.rawQuery(params.query, params.params ?? []);
        return { content: [{ type: "text" as const, text: JSON.stringify(results, null, 2) }] };
      } catch (err: any) {
        return { content: [{ type: "text" as const, text: `SQL Error: ${err.message}` }], isError: true };
      }
    }
  );

  server.tool(
    "smartbuilding_use_case_validate",
    "Validate prompt-schema consistency for a use case",
    {
      use_case_name: z.string().describe("Use case identifier"),
      prompt: z.string().describe("VLM prompt to validate against schema"),
      required_fields: z.array(z.string()).describe("Schema required field names"),
    },
    async (params) => {
      const missing = params.required_fields.filter(
        (field) => !params.prompt.toLowerCase().includes(field.toLowerCase()),
      );
      if (missing.length === 0) {
        return { content: [{ type: "text" as const, text: `Validation passed: all required fields found in prompt for use case "${params.use_case_name}".` }] };
      }
      return {
        content: [{ type: "text" as const, text: `Validation failed for "${params.use_case_name}". Missing fields: ${missing.join(", ")}` }],
        isError: true,
      };
    }
  );
}
