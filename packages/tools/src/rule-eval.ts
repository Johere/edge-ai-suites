import type { SmartBuildingDB } from "@smartbuilding-video/db";

export interface RuleEvalParams {
  monitor_id: string;
  // Optional: only evaluate rules for tasks completed since this timestamp (ISO 8601)
  since?: string;
}

export interface RuleEvalResult {
  monitor_id: string;
  evaluated: number;
  triggered: number;
  alerts_created: number;
}

/**
 * Manually trigger rule evaluation for a monitor.
 * Inspects recent completed video_summary_tasks, applies severity threshold,
 * and inserts alerts for tasks that haven't been alerted yet.
 *
 * This is a generic fallback implementation — use-case-specific adapters
 * (registered via rule engine) can override the evaluation logic.
 */
export async function ruleEval(
  db: SmartBuildingDB,
  params: RuleEvalParams
): Promise<RuleEvalResult> {
  const since = params.since ?? new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();

  // Find completed tasks not yet alerted
  const rows = db.rawQuery(
    `SELECT t.*
     FROM video_summary_tasks t
     LEFT JOIN alerts a ON a.source_id = t.monitor_id
     WHERE t.monitor_id = ?
       AND t.status = 'completed'
       AND t.created_at >= ?
       AND a.id IS NULL`,
    [params.monitor_id, since]
  ) as any[];

  let alertsCreated = 0;

  for (const task of rows) {
    // Generic severity extraction: look for SEVERITY: critical/warn line in summary
    const summary: string = task.summary ?? "";
    const severityMatch = summary.match(/SEVERITY:\s*(critical|warn|info)/i);
    const severity = severityMatch?.[1]?.toLowerCase() ?? "info";

    if (severity === "critical" || severity === "warn") {
      db.createAlert({
        monitorId: params.monitor_id,
        taskId: task.id,
        useCase: "",
        alertType: "rule_eval",
        description: summary.slice(0, 200),
      });
      alertsCreated++;
    }
  }

  return {
    monitor_id: params.monitor_id,
    evaluated: rows.length,
    triggered: alertsCreated,
    alerts_created: alertsCreated,
  };
}
