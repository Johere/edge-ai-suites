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
}

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
 * `config.yaml → use_case_dict.<name>.rules`. Recognised keys:
 *   - `severityThreshold`: `"info" | "warn" | "critical"` (default `"warn"`)
 *   - `excludeEvents`: `string[]` — events that never fire regardless of severity
 *
 * Complex use-case logic (time comparisons, multi-event joint decisions,
 * external service calls) should live in a Python override — see
 * `evaluateWithOverride`.
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

  const desc = fields["desc"] ?? fields["description"] ?? "";
  return {
    shouldAlert: true,
    alertMessage: formatAlertMessage({
      useCase: context.useCase,
      alertType: eventField,
      severity,
      desc,
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
    ]);
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

