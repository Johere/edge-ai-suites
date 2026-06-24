import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import type { ServerConfig } from "./config.js";
import type { SmartBuildingDB } from "@smartbuilding-video/db";
import type { WorkerService } from "./video-worker/index.js";

export function registerTools(
  server: McpServer,
  config: ServerConfig,
  db: SmartBuildingDB,
  workerService: WorkerService,
): void {
  // --- smartbuilding_alert_query ---
  server.registerTool("smartbuilding_alert_query", {
    description: "Query or acknowledge alerts. action: latest | by_date | ack | stats",
    inputSchema: {
      monitor_id: z.string().describe("Monitor ID"),
      action: z.enum(["latest", "by_date", "ack", "stats"]).describe("Action to perform"),
      limit: z.number().optional().describe("Max results (default 20, for latest action)"),
      start_date: z.string().optional().describe("Start date YYYY-MM-DD (for by_date/stats)"),
      end_date: z.string().optional().describe("End date YYYY-MM-DD (for by_date/stats)"),
      alert_id: z.number().optional().describe("Alert ID to acknowledge (for ack action)"),
      ack_by: z.string().optional().describe("User who acknowledges (for ack action)"),
    },
  }, async (params) => {
    try {
      const { alertQuery } = await import("@smartbuilding-video/tools");
      const result = await alertQuery(db, params as any);
      return { content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }] };
    } catch (err: any) {
      return { content: [{ type: "text" as const, text: `Error: ${err.message}` }], isError: true };
    }
  });

  // --- smartbuilding_plan_ctl ---
  server.registerTool("smartbuilding_plan_ctl", {
    description: "Manage per-monitor plans (arbitrary JSON keyed by date). Rule engine can read today's plan before deciding whether to fire. action: list | upsert | delete",
    inputSchema: {
      monitor_id: z.string().describe("Monitor ID"),
      action: z.enum(["list", "upsert", "delete"]).describe("Action to perform"),
      name: z.string().optional().describe("Unique plan name within monitor (required for upsert / delete)"),
      plan: z.record(z.unknown()).optional().describe("Plan data object, arbitrary JSON (required for upsert)"),
      plan_date: z.string().optional().describe("Optional YYYY-MM-DD hint stored with the plan (not the key)"),
      active_only: z.boolean().optional().describe("Return only active plans, default true (for list)"),
    },
  }, async (params) => {
    try {
      const { planCtl } = await import("@smartbuilding-video/tools");
      const result = planCtl(db, params as any);
      return { content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }] };
    } catch (err: any) {
      return { content: [{ type: "text" as const, text: `Error: ${err.message}` }], isError: true };
    }
  });

  // --- smartbuilding_scene_query ---
  server.registerTool("smartbuilding_scene_query", {
    description: "Real-time scene analysis: reads latest.jpg from $SMARTBUILDING_DATA_DIR/segments/<monitor_id>/ and queries VLM (vllm-serving-ipex)",
    inputSchema: {
      monitor_id: z.string().describe("Monitor ID"),
      prompt: z.string().optional().describe("Override prompt for VLM (default: describe scene in 1-2 sentences)"),
      vlm_url: z.string().optional().describe("VLM base URL (default from config: vlmService.url)"),
      model: z.string().optional().describe("VLM model ID (default from config: vlmService.model)"),
      max_edge_px: z.number().optional().describe("Max frame edge in pixels (default from config: vlmService.maxEdgePx)"),
    },
  }, async (params) => {
    try {
      const { default: path } = await import("node:path");
      const { sceneQuery } = await import("@smartbuilding-video/tools");
      const dataDir = path.join(config.segmentsDir, params.monitor_id);
      const vlmUrl = params.vlm_url ?? config.vlmService.url;
      const model = params.model ?? config.vlmService.model;
      const maxEdgePx = params.max_edge_px ?? config.vlmService.maxEdgePx;
      const result = await sceneQuery({ ...params, data_dir: dataDir, vlm_url: vlmUrl, model, max_edge_px: maxEdgePx });
      return { content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }] };
    } catch (err: any) {
      return { content: [{ type: "text" as const, text: `Error: ${err.message}` }], isError: true };
    }
  });

  // --- smartbuilding_generate_report ---
  server.registerTool("smartbuilding_generate_report", {
    description: "Generate daily/weekly/monthly/custom report. Uses config-driven dataSource (events|alerts|tasks).",
    inputSchema: {
      monitor_id: z.string().describe("Monitor ID"),
      type: z.enum(["daily", "weekly", "monthly", "custom"]).optional()
        .describe("Report type (default: daily). custom requires period_start + period_end."),
      period_start: z.string().optional().describe("Start of period, closed interval. YYYY-MM-DD or YYYY-MM-DD HH:MM (for type=custom)"),
      period_end: z.string().optional().describe("End of period, closed interval. YYYY-MM-DD or YYYY-MM-DD HH:MM (for type=custom)"),
      data_source: z.enum(["events", "alerts", "tasks"]).optional()
        .describe("Data source override (default: alerts)"),
      filter: z.record(z.unknown()).optional()
        .describe("Key-value filter applied to data source table (e.g. {motion_type: 'motion'})"),
    },
  }, async (params) => {
    try {
      const { generateReport } = await import("@smartbuilding-video/tools");
      const reportConfig = {
        dataSource: (params.data_source ?? "alerts") as "events" | "alerts" | "tasks",
        defaultType: "daily" as const,
        summaryServiceUrl: config.summaryService.url,
        filter: params.filter as Record<string, any> | undefined,
        debugDir: config.logsDir,
      };
      const result = await generateReport(db, reportConfig, {
        monitor_id: params.monitor_id,
        type: params.type,
        period_start: params.period_start,
        period_end: params.period_end,
      });
      return { content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }] };
    } catch (err: any) {
      return { content: [{ type: "text" as const, text: `Error: ${err.message}` }], isError: true };
    }
  });

  // --- smartbuilding_monitor_ctl ---
  server.registerTool("smartbuilding_monitor_ctl", {
    description: "Manage monitor lifecycle: register_source | unregister | start | stop | status | list",
    inputSchema: {
      action: z.enum(["start", "stop", "register_source", "unregister", "status", "list"])
        .describe("Control action"),
      monitor_id: z.string().optional().describe("Monitor ID (required for all except list)"),
      source_url: z.string().optional().describe("RTSP URL (for register_source)"),
      name: z.string().optional().describe("Display name (for register_source)"),
      use_case_id: z.string().optional().describe("Use case ID (for register_source)"),
      video_summary_task: z.string().optional().describe("Task name registered in multilevel-video-understanding service (required for register_source)"),
      pipeline_config: z.record(z.unknown()).optional().describe("Pipeline config object (for register_source)"),
      webhook_url: z.string().optional().describe("Events webhook URL sent to analytics service (for register_source)"),
    },
  }, async (params) => {
    try {
      const { monitorCtl } = await import("@smartbuilding-video/tools");
      const result = await monitorCtl(db, config.videostreamAnalytics.url, params as any);
      // Sync worker service with DB state
      if ((params.action === "start" || params.action === "register_source") && params.monitor_id) workerService.start(params.monitor_id);
      if ((params.action === "stop" || params.action === "unregister") && params.monitor_id) workerService.stop(params.monitor_id);
      return { content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }] };
    } catch (err: any) {
      return { content: [{ type: "text" as const, text: `Error: ${err.message}` }], isError: true };
    }
  });

  // --- smartbuilding_rule_eval ---
  server.registerTool("smartbuilding_rule_eval", {
    description: "Manually trigger rule evaluation for a monitor. Scans recent completed tasks and creates alerts.",
    inputSchema: {
      monitor_id: z.string().describe("Monitor ID"),
      since: z.string().optional().describe("ISO 8601 timestamp — only evaluate tasks completed after this (default: last 24h)"),
    },
  }, async (params) => {
    try {
      const { ruleEval } = await import("@smartbuilding-video/tools");
      const result = await ruleEval(db, params);
      return { content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }] };
    } catch (err: any) {
      return { content: [{ type: "text" as const, text: `Error: ${err.message}` }], isError: true };
    }
  });

  // --- smartbuilding_video_db ---
  server.registerTool("smartbuilding_video_db", {
    description: "Low-level read-only SQL query against the monitor database",
    inputSchema: {
      query: z.string().describe("SELECT SQL query to execute"),
      params: z.array(z.unknown()).optional().describe("Positional query parameters"),
    },
  }, async (params) => {
    // Safety: only allow SELECT statements
    if (!params.query.trim().toUpperCase().startsWith("SELECT")) {
      return { content: [{ type: "text" as const, text: "Error: only SELECT queries allowed via this tool" }], isError: true };
    }
    try {
      const results = db.rawQuery(params.query, params.params ?? []);
      return { content: [{ type: "text" as const, text: JSON.stringify(results, null, 2) }] };
    } catch (err: any) {
      return { content: [{ type: "text" as const, text: `SQL Error: ${err.message}` }], isError: true };
    }
  });

  // --- smartbuilding_use_case_validate ---
  server.registerTool("smartbuilding_use_case_validate", {
    description: "Validate that a video summary prompt covers all required schema fields (case-insensitive substring check)",
    inputSchema: {
      use_case_name: z.string().describe("Use case identifier (for labeling only)"),
      prompt: z.string().describe("Video summary prompt text to validate"),
      required_fields: z.array(z.string()).describe("Field names that must appear in the prompt"),
    },
  }, async (params) => {
    const { useCaseValidate } = await import("@smartbuilding-video/tools");
    const result = useCaseValidate(params);
    return { content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }] };
  });
}
