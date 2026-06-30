import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { existsSync } from "node:fs";

export { parseSummaryFields } from "./summary-parser.js";
export type { ParsedSummary } from "./summary-parser.js";

const execFileAsync = promisify(execFile);

export interface RuleContext {
  monitorId: string;
  useCase: string;
  taskId: number;
  /** Full VLM summary text — kept for Python overrides that want raw access. */
  summaryText: string;
  /**
   * Parsed schema fields injected by task-poller (already extracted via parseSummaryFields).
   * Caller-provided so rule engine doesn't re-parse.
   */
  payload: { fields?: Record<string, string> } & Record<string, unknown>;
}

export interface RuleResult {
  shouldAlert: boolean;
  /** Human-readable alert text. Stored in alerts.description (no separate alert_type column). */
  alertMessage?: string;
}

export type RuleEvaluator = (context: RuleContext) => Promise<RuleResult>;

const SEVERITY_TRIGGER = new Set(["critical", "warn"]);

/**
 * Default rule: alert when the parsed `severity` field is "critical" or "warn".
 *
 * TODO: need more elegant alerts rule (may configurable per-monitor?).
 *   Current behavior is intentionally minimal — complex use-case logic should
 *   live in the Python override (see evaluateWithOverride).
 */
export async function defaultRuleEvaluator(context: RuleContext): Promise<RuleResult> {
  const fields = context.payload?.fields ?? {};
  const severity = (fields["severity"] ?? "").toLowerCase();
  if (!SEVERITY_TRIGGER.has(severity)) return { shouldAlert: false };

  const eventField = fields["event"] ?? "alert";
  const desc = fields["desc"] ?? fields["description"] ?? "";
  return {
    shouldAlert: true,
    alertMessage: `[${context.useCase}] ${eventField}: ${severity} — ${desc}`,
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

