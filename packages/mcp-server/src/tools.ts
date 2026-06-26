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
        debugDir: config.reportsLogsDir,
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
      use_case: z.string().optional().describe("Use case ID (required for register_source)"),
      video_summary_task: z.string().optional().describe("Task name registered in multilevel-video-understanding service (required for register_source; verified to exist before proceeding)"),
      pipeline_config: z.record(z.unknown()).optional().describe("Pipeline config object (for register_source)"),
      webhook_url: z.string().optional().describe("Events webhook URL (default: derived from config eventsWebhook.port)"),
    },
  }, async (params) => {
    try {
      // Validate required fields for register_source
      if (params.action === "register_source") {
        if (!params.use_case) throw new Error("use_case is required for register_source");
        if (!params.video_summary_task) throw new Error("video_summary_task is required for register_source");
        // webhook_url defaulted from config below if caller omits

        // Verify video_summary_task exists in multilevel-video-understanding service before register_source
        const taskName = params.video_summary_task;
        const resp = await fetch(`${config.summaryService.url}/v1/tasks/${taskName}`, {
          signal: AbortSignal.timeout(8000),
        }).catch((err) => { throw new Error(`multilevel-video-understanding (${config.summaryService.url}) unreachable: ${err.message}`); });
        if (resp.status === 404) {
          throw new Error(
            `video_summary_task "${taskName}" not found in multilevel-video-understanding service (${config.summaryService.url}). ` +
            `Register the task first: POST ${config.summaryService.url}/v1/tasks`
          );
        }
        if (!resp.ok) {
          throw new Error(`Failed to verify video_summary_task "${taskName}": HTTP ${resp.status}`);
        }
      }

      const { monitorCtl } = await import("@smartbuilding-video/tools");
      const { join } = await import("node:path");
      // Inject derived fields the tool layer can compute from server config:
      // - data_dir: per-monitor segment root for analytics to write into
      // - webhook_url: this server's /events endpoint (caller may override)
      const enriched: any = { ...params };
      if (params.action === "register_source" && params.monitor_id) {
        enriched.data_dir ??= join(config.segmentsDir, params.monitor_id);
        enriched.webhook_url ??= `http://localhost:${config.eventsWebhook!.port}/events`;
      }
      const result = await monitorCtl(db, config.videostreamAnalytics.url, workerService, enriched);
      return { content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }] };
    } catch (err: any) {
      return { content: [{ type: "text" as const, text: `Error: ${err.message}` }], isError: true };
    }
  });

  // --- smartbuilding_monitors_compose ---
  server.registerTool("smartbuilding_monitors_compose", {
    description: "Docker-compose-style management of monitors declared in a monitors.yaml file. Actions: validate | up | down | restart | ps",
    inputSchema: {
      action: z.enum(["validate", "up", "down", "restart", "ps"]).describe("Compose action"),
      file: z.string().describe("Path to monitors.yaml (absolute or relative to cwd)"),
      monitor_id: z.string().optional().describe("Apply to only this monitor (default: all in file)"),
    },
  }, async (params) => {
    try {
      const { loadMonitorsFromYaml, validateMonitors } = await import("@smartbuilding-video/tools");
      const { applyMonitorConfig } = await import("./monitor-bootstrap.js");

      // 1. Load + validate (every action validates first)
      let resolvedPath: string;
      let monitors: Record<string, any>;
      try {
        const loaded = loadMonitorsFromYaml(params.file);
        resolvedPath = loaded.resolvedPath;
        monitors = loaded.monitors;
      } catch (err: any) {
        return {
          content: [{ type: "text" as const, text: JSON.stringify({
            action: params.action, file: params.file, valid: false,
            errors: [{ monitor_id: "*", field: "file", reason: err.message }],
            results: [],
          }, null, 2) }],
          isError: true,
        };
      }

      const filtered: Record<string, any> = params.monitor_id
        ? (params.monitor_id in monitors ? { [params.monitor_id]: monitors[params.monitor_id] } : {})
        : monitors;
      const errors = validateMonitors(filtered);
      const valid = errors.length === 0;

      const output: any = { action: params.action, file: resolvedPath, valid, errors, results: [] };

      // 2. Action dispatch
      if (params.action === "validate") {
        return { content: [{ type: "text" as const, text: JSON.stringify(output, null, 2) }] };
      }

      if (!valid) {
        // Don't make changes when config is invalid
        return { content: [{ type: "text" as const, text: JSON.stringify(output, null, 2) }], isError: true };
      }

      if (params.action === "ps") {
        // Report current state of each monitor without modifying anything
        for (const monitorId of Object.keys(filtered)) {
          const dbRec = db.getMonitor(monitorId);
          const workerRunning = workerService.workers.has(monitorId);
          let analytics: any;
          try {
            const resp = await fetch(`${config.videostreamAnalytics.url}/sources/${monitorId}/status`, { signal: AbortSignal.timeout(5000) });
            analytics = resp.ok ? { reachable: true, status: await resp.json() } : { reachable: false, error: `HTTP ${resp.status}` };
          } catch (err: any) {
            analytics = { reachable: false, error: err?.message ?? "unreachable" };
          }
          output.results.push({
            monitor_id: monitorId,
            status: "ok",
            state: {
              db: dbRec ? { exists: true, status: dbRec.status } : { exists: false },
              analytics,
              worker: { running: workerRunning },
            },
          });
        }
        return { content: [{ type: "text" as const, text: JSON.stringify(output, null, 2) }] };
      }

      // up / down / restart — delegate to shared bootstrap helper
      output.results = await applyMonitorConfig(
        db, config, workerService, filtered, params.action,
        params.monitor_id,
      );
      return { content: [{ type: "text" as const, text: JSON.stringify(output, null, 2) }] };
    } catch (err: any) {
      return { content: [{ type: "text" as const, text: `Error: ${err.message}` }], isError: true };
    }
  });

  // --- smartbuilding_video_db ---
  server.registerTool("smartbuilding_video_db", {
    description: "Low-level read-only SQL query against the SQLite database (all tables: monitors, alerts, video_summary_tasks, events, recordings, reports, plans, monitor_state)",
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
      use_case: z.string().describe("Use case identifier (for labeling only)"),
      prompt: z.string().describe("Video summary prompt text to validate"),
      required_fields: z.array(z.string()).describe("Field names that must appear in the prompt"),
    },
  }, async (params) => {
    const { useCaseValidate } = await import("@smartbuilding-video/tools");
    const result = useCaseValidate(params);
    return { content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }] };
  });
}
