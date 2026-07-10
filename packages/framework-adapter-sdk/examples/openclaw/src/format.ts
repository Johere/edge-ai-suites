import type { AlertPayload } from "@smartbuilding-video/framework-adapter-sdk";

type Alert = AlertPayload["alert"];

/** Read an optional schema-extension field as a trimmed string, or undefined.
 *  The base Alert row is use-case-agnostic (no severity/event/alert_type — those live on the
 *  JOIN'd task), so we probe defensively: present only if a deployment extends the alert schema. */
function str(alert: Alert, key: string): string | undefined {
  const v = (alert as unknown as Record<string, unknown>)[key];
  return typeof v === "string" && v.trim() ? v.trim() : undefined;
}

const USE_CASE_EMOJI: Record<string, string> = {
  refrigerator_monitor: "🧊",
  child_safety_monitor: "🛡️",
  elder_wakeup_monitor: "🌅",
};

function emoji(alert: Alert): string {
  return USE_CASE_EMOJI[alert.useCase] ?? "🔔";
}

/**
 * Short one-line user "separator" shown above the alert. Breaks ControlUI's same-role grouping
 * (see session-append.ts) and gives the operator an at-a-glance marker.
 *   e.g. `🔔 [CRITICAL] climb — 2026-07-09T10:44:39Z cam_child`
 */
export function formatSeparator(alert: Alert): string {
  const sev = str(alert, "severity");
  const event = str(alert, "event") ?? str(alert, "alert_type") ?? alert.useCase;
  const sevTag = sev ? `[${sev.toUpperCase()}] ` : "";
  return `🔔 ${sevTag}${event} — ${alert.createdAt} ${alert.monitorId}`;
}

/**
 * The alert body delivered into the session — raw pass-through (no persona polish, by design).
 *   e.g. `🛡️ [child_safety_monitor] Child climbing on the window sill`
 */
export function formatAlert(alert: Alert): string {
  const desc = alert.description?.trim() || "(no description)";
  return `${emoji(alert)} [${alert.useCase}] ${desc}`;
}
