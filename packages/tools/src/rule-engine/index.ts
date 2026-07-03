import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { existsSync } from "node:fs";
import { parseSummaryFields } from "./summary-parser.js";
import { formatAlertMessage } from "./alert-message.js";

export { parseSummaryFields } from "./summary-parser.js";
export type { ParsedSummary } from "./summary-parser.js";
export { formatAlertMessage } from "./alert-message.js";
export type { AlertMessageParts } from "./alert-message.js";

const execFileAsync = promisify(execFile);

/** Severity ordinals used by defaultRuleEvaluator for threshold comparison. */
const SEVERITY_ORDER: Record<string, number> = {
  info: 0,
  warn: 1,
  critical: 2,
};

/**
 * Rules-block keys recognised by `defaultRuleEvaluator`. Any Python override
 * is free to interpret `rules` however it likes.
 */
interface DefaultRuleOptions {
  /** Minimum severity (`"info" | "warn" | "critical"`) that fires. Default `"warn"`. */
  severityThreshold?: string;
  /** Events that never fire even at or above the threshold. */
  excludeEvents?: string[];
  /**
   * Whitelist single event value — when set, only `fields.event === requireEvent`
   * fires. Combines with severityThreshold (both must pass). Used by
   * high_altitude_safety to gate on `high_altitude_throw` only.
   */
  requireEvent?: string;
  /**
   * Whitelist single direction value — when set, `fields.motion_direction`
   * must equal this (case-insensitive). Used by high_altitude_safety to
   * suppress e.g. balloon rising upward.
   */
  requireDirection?: string;
  /**
   * Zones that never fire even when event / severity pass. Compared against
   * `fields.parking_zone`. Used by parking_safety to opt-out specific zones
   * (e.g. deprioritise visitor spots on weekends).
   */
  excludeZones?: string[];
  /**
   * When present, the alert message will carry a suffix `(<label>=<value>)`
   * where `<value>` is read from `fields[<this key>]` and `<label>` is a
   * human-friendly short form (see EXTRA_LABEL_MAP). Empty / missing fields
   * result in no suffix.
   */
  alertMessageExtraField?: string;
}

/**
 * Short label used when composing `alertMessage` suffix. Keeps the alerts
 * table readable (`zone=fire_lane` reads better than `parking_zone=fire_lane`)
 * while preserving the schema field name in DB columns.
 * Fallback: unknown fields use the field name verbatim.
 */
const EXTRA_LABEL_MAP: Record<string, string> = {
  parking_zone: "zone",
  motion_direction: "direction",
  pet_zone: "zone",
};

export interface RuleContext {
  monitorId: string;
  useCase: string;
  taskId: number;
  /** Full VLM summary text — kept for Python overrides that want raw access. */
  summaryText: string;
  /**
   * Parsed schema fields injected by task-poller (already extracted via parseSummaryFields).
   * Caller-provided so rule engine doesn't re-parse.
   *
   * `rules` is the per-use-case rules block copied from
   * `config.useCaseDict[useCase].rules` (Phase 10). Python overrides read it
   * via argv[1].payload.rules; the built-in evaluator ignores it.
   */
  payload: {
    fields?: Record<string, string>;
    rules?: Record<string, unknown>;
  } & Record<string, unknown>;
}

export interface RuleResult {
  shouldAlert: boolean;
  /** Human-readable alert text. Stored in alerts.description (no separate alert_type column). */
  alertMessage?: string;
}

export type RuleEvaluator = (context: RuleContext) => Promise<RuleResult>;

/**
 * Default rule: alert when the parsed `severity` field is at or above the
 * configured threshold and the `event` field is not in the exclusion list.
 *
 * Behaviour is controlled by the per-use-case `rules` block loaded from
 * `config.yaml → use_case_dict.<name>.rules`. Recognised keys (all optional):
 *   - `severityThreshold`: `"info" | "warn" | "critical"` (default `"warn"`)
 *   - `excludeEvents`: `string[]` — events that never fire regardless of severity
 *   - `requireEvent`: single event whitelist (paired with severity check)
 *   - `requireDirection`: `fields.motion_direction` must match (case-insensitive)
 *   - `excludeZones`: `string[]` compared against `fields.parking_zone`
 *   - `alertMessageExtraField`: field to append as `(label=value)` suffix
 *
 * Complex use-case logic (time comparisons, multi-event joint decisions,
 * external service calls) still needs a Python override — see
 * `evaluateWithOverride`. `elder_wakeup` is a canonical example.
 */
export async function defaultRuleEvaluator(context: RuleContext): Promise<RuleResult> {
  const fields = context.payload?.fields ?? {};
  const rules = (context.payload?.rules ?? {}) as DefaultRuleOptions;

  const severity = (fields["severity"] ?? "").toLowerCase();
  const severityLevel = SEVERITY_ORDER[severity];
  if (severityLevel === undefined) return { shouldAlert: false };

  const thresholdName = (rules.severityThreshold ?? "warn").toLowerCase();
  const thresholdLevel = SEVERITY_ORDER[thresholdName] ?? SEVERITY_ORDER["warn"];
  if (severityLevel < thresholdLevel) return { shouldAlert: false };

  const eventField = fields["event"] ?? "alert";
  const excludeEvents = Array.isArray(rules.excludeEvents) ? rules.excludeEvents : [];
  if (excludeEvents.includes(eventField)) return { shouldAlert: false };

  if (rules.requireEvent && eventField !== rules.requireEvent) {
    return { shouldAlert: false };
  }

  if (rules.requireDirection) {
    const observed = (fields["motion_direction"] ?? "").toLowerCase();
    if (observed !== rules.requireDirection.toLowerCase()) {
      return { shouldAlert: false };
    }
  }

  if (Array.isArray(rules.excludeZones) && rules.excludeZones.length > 0) {
    const zone = fields["parking_zone"] ?? "";
    if (zone && rules.excludeZones.includes(zone)) {
      return { shouldAlert: false };
    }
  }

  let extra: string | undefined;
  if (rules.alertMessageExtraField) {
    const value = fields[rules.alertMessageExtraField];
    if (value) {
      const label = EXTRA_LABEL_MAP[rules.alertMessageExtraField] ?? rules.alertMessageExtraField;
      extra = `${label}=${value}`;
    }
  }

  const desc = fields["desc"] ?? fields["description"] ?? "";
  return {
    shouldAlert: true,
    alertMessage: formatAlertMessage({
      useCase: context.useCase,
      alertType: eventField,
      severity,
      desc,
      extra,
    }),
  };
}

/**
 * Run a Python rule override at the given path, falling back to defaultRuleEvaluator
 * when overridePath is null or the file does not exist.
 *
 * The override script receives the RuleContext as JSON on argv[1] and is expected to
 * print a JSON object: { should_alert: bool, alert_message?: string }.
 *
 * Path is supplied by the caller (typically derived from config.useCaseDict[useCase].evaluate_rules_path)
 * rather than hard-coded — use case adapters live anywhere on disk.
 */
export async function evaluateWithOverride(
  context: RuleContext,
  overridePath: string | null,
): Promise<RuleResult> {
  if (!overridePath || !existsSync(overridePath)) {
    return defaultRuleEvaluator(context);
  }

  try {
    const { stdout } = await execFileAsync("python3", [
      overridePath,
      JSON.stringify(context),
    ], { timeout: 10_000 });
    const result = JSON.parse(stdout.trim());
    return {
      shouldAlert: Boolean(result.should_alert),
      alertMessage: result.alert_message,
    };
  } catch (err: any) {
    console.error(`[rule-engine] Python override failed for ${context.useCase}:`, err.message);
    return defaultRuleEvaluator(context);
  }
}

