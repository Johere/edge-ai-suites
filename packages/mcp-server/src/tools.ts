import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import type { ServerConfig } from "./config.js";

export function registerTools(server: McpServer, config: ServerConfig): void {
  server.tool(
    "smartbuilding_alert_query",
    "Query or acknowledge alerts",
    {
      monitor_id: z.string().optional().describe("Filter by monitor ID"),
      status: z.enum(["unacked", "acked", "all"]).optional().describe("Alert status filter"),
      limit: z.number().optional().describe("Max results to return"),
    },
    async (params) => {
      // TODO: implement alert query via @smartbuilding-video/db
      return { content: [{ type: "text" as const, text: "Not implemented" }] };
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
      // TODO: implement state query
      return { content: [{ type: "text" as const, text: "Not implemented" }] };
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
      // TODO: implement VLM scene query
      return { content: [{ type: "text" as const, text: "Not implemented" }] };
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
      // TODO: implement daily report generation
      return { content: [{ type: "text" as const, text: "Not implemented" }] };
    }
  );

  server.tool(
    "smartbuilding_monitor_ctl",
    "Start, stop, or register video sources",
    {
      action: z.enum(["start", "stop", "register_source", "list"]).describe("Control action"),
      monitor_id: z.string().optional().describe("Monitor ID (required for start/stop)"),
      source_url: z.string().optional().describe("RTSP URL or file path (for register_source)"),
    },
    async (params) => {
      // TODO: implement monitor control
      return { content: [{ type: "text" as const, text: "Not implemented" }] };
    }
  );

  server.tool(
    "smartbuilding_rule_eval",
    "Manually trigger rule evaluation for a monitor",
    {
      monitor_id: z.string().describe("Monitor ID"),
    },
    async (params) => {
      // TODO: implement rule evaluation trigger
      return { content: [{ type: "text" as const, text: "Not implemented" }] };
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
      // TODO: implement DB query
      return { content: [{ type: "text" as const, text: "Not implemented" }] };
    }
  );

  server.tool(
    "smartbuilding_use_case_validate",
    "Validate prompt-schema consistency for a use case",
    {
      use_case_name: z.string().describe("Use case identifier"),
      prompt: z.string().optional().describe("VLM prompt to validate against schema"),
    },
    async (params) => {
      // TODO: implement use case validation
      return { content: [{ type: "text" as const, text: "Not implemented" }] };
    }
  );
}
