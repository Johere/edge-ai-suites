import type { SmartBuildingDB } from "@smartbuilding-video/db";

export interface MonitorCtlParams {
  action: "start" | "stop" | "register_source" | "unregister" | "status" | "list";
  monitor_id?: string;
  // register_source params
  source_url?: string;
  name?: string;
  use_case_id?: string;
  video_summary_task?: string; // task name in multilevel-video-understanding service
  pipeline_config?: Record<string, unknown>;
  // videostream-analytics base URL override
  analytics_url?: string;
  // MCP server events webhook URL (sent to analytics service on register)
  webhook_url?: string;
}

/**
 * Manage monitor lifecycle: register/unregister RTSP sources, start/stop processing.
 * Two layers:
 *   1. DB: create/update monitor record
 *   2. videostream-analytics microservice (`:8999` by default): RESTful source management
 */
export async function monitorCtl(
  db: SmartBuildingDB,
  analyticsBaseUrl: string,
  params: MonitorCtlParams
): Promise<unknown> {
  const analyticsUrl = params.analytics_url ?? analyticsBaseUrl;

  switch (params.action) {
    case "list": {
      const monitors = db.listMonitors();
      // Enrich with live status from analytics service (best-effort)
      try {
        const resp = await fetch(`${analyticsUrl}/sources`, { signal: AbortSignal.timeout(5000) });
        if (resp.ok) {
          const live = (await resp.json()) as any[];
          const liveById = Object.fromEntries(live.map((s: any) => [s.source_id, s]));
          return monitors.map((m) => ({ ...m, analyticsStatus: liveById[m.id]?.status ?? "unknown" }));
        }
      } catch {
        // analytics service unreachable; return DB state only
      }
      return monitors;
    }

    case "register_source": {
      if (!params.monitor_id) {
        throw new Error("monitor_id is required for register_source");
      }
      if (!params.source_url) {
        throw new Error("source_url is required for register_source");
      }
      // Basic RTSP URL format validation
      if (!params.source_url.startsWith("rtsp://") && !params.source_url.startsWith("rtsp:")) {
        throw new Error(`Invalid RTSP URL: ${params.source_url} — must start with rtsp://`);
      }

      if (!params.video_summary_task) {
        throw new Error("video_summary_task is required for register_source — set it to the task name registered in multilevel-video-understanding");
      }

      // Create/update DB record
      const existing = db.getMonitor(params.monitor_id);
      if (!existing) {
        db.createMonitor({
          id: params.monitor_id,
          name: params.name ?? params.monitor_id,
          sourceUrl: params.source_url,
          status: "offline",
          useCaseId: params.use_case_id ?? "default",
          videoSummaryTask: params.video_summary_task,
        });
      }

      // Register with analytics microservice
      const webhookUrl = params.webhook_url ?? `http://localhost:3101/events`;
      await fetch(`${analyticsUrl}/register_source`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_id: params.monitor_id,
          rtsp_url: params.source_url,
          webhook_url: webhookUrl,
          pipeline: params.pipeline_config ?? {
            motion: { enabled: true },
            prefilter: { enabled: false },
            recording: { enabled: true, interval_seconds: 60 },
          },
        }),
        signal: AbortSignal.timeout(10_000),
      }).then(async (r) => {
        if (!r.ok) {
          const t = await r.text().catch(() => "");
          throw new Error(`analytics register_source failed ${r.status}: ${t.slice(0, 200)}`);
        }
      });

      return { success: true, monitor_id: params.monitor_id };
    }

    case "unregister": {
      if (!params.monitor_id) {
        throw new Error("monitor_id is required for unregister");
      }
      // Remove from analytics service
      await fetch(`${analyticsUrl}/sources/${params.monitor_id}`, {
        method: "DELETE",
        signal: AbortSignal.timeout(10_000),
      }).catch(() => {
        // Non-fatal: DB deletion proceeds even if analytics is down
      });
      db.deleteMonitor(params.monitor_id);
      return { success: true, monitor_id: params.monitor_id };
    }

    case "start": {
      if (!params.monitor_id) {
        throw new Error("monitor_id is required for start");
      }
      await fetch(`${analyticsUrl}/sources/${params.monitor_id}/resume`, {
        method: "POST",
        signal: AbortSignal.timeout(10_000),
      }).catch(() => {});
      db.updateMonitorStatus(params.monitor_id, "online");
      return { success: true, monitor_id: params.monitor_id, status: "online" };
    }

    case "stop": {
      if (!params.monitor_id) {
        throw new Error("monitor_id is required for stop");
      }
      await fetch(`${analyticsUrl}/sources/${params.monitor_id}/pause`, {
        method: "POST",
        signal: AbortSignal.timeout(10_000),
      }).catch(() => {});
      db.updateMonitorStatus(params.monitor_id, "offline");
      return { success: true, monitor_id: params.monitor_id, status: "offline" };
    }

    case "status": {
      if (!params.monitor_id) {
        throw new Error("monitor_id is required for status");
      }
      const monitor = db.getMonitor(params.monitor_id);
      if (!monitor) {
        throw new Error(`Monitor not found: ${params.monitor_id}`);
      }
      try {
        const resp = await fetch(`${analyticsUrl}/sources/${params.monitor_id}/status`, {
          signal: AbortSignal.timeout(5000),
        });
        if (resp.ok) {
          const live = await resp.json();
          return { ...monitor, analyticsStatus: live };
        }
      } catch {
        // analytics unreachable
      }
      return { ...monitor, analyticsStatus: null };
    }

    default:
      throw new Error(`Unknown action: ${(params as any).action}`);
  }
}
