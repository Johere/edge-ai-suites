import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { parseSummaryFields } from "./summary-parser.js";

export { parseSummaryFields } from "./summary-parser.js";

const execFileAsync = promisify(execFile);

export interface RuleContext {
  monitorId: string;
  useCase: string;
  taskId: number;
  summaryText: string;              // full VLM output — rule engine extracts what it needs
  payload: Record<string, unknown>; // TODO: use-case adapter fills custom fields here
}

export interface RuleResult {
  shouldAlert: boolean;
  alertType?: string;    // written to alerts.alert_type
  alertMessage?: string;
}

export type RuleEvaluator = (context: RuleContext) => Promise<RuleResult>;

const SEVERITY_LEVELS: Record<string, number> = {
  low: 1,
  medium: 2,
  high: 3,
  critical: 4,
  warn: 2,
  info: 1,
};

/**
 * Default rule engine: parses summaryText for a SEVERITY field and triggers
 * an alert when severity level >= threshold (medium/warn = 2).
 * Field names (SEVERITY/EVENT/DESC) are the default schema convention, not
 * a hard contract — use-case adapters or Python overrides can use any fields.
 */
export async function defaultRuleEvaluator(context: RuleContext): Promise<RuleResult> {
  const fields = parseSummaryFields(context.summaryText);
  const severity = fields["severity"] ?? "info";
  const level = SEVERITY_LEVELS[severity.toLowerCase()] ?? 0;
  const threshold = 2;

  if (level < threshold) {
    return { shouldAlert: false };
  }

  const eventField = fields["event"] ?? fields["alert_type"] ?? "alert";
  const desc = fields["desc"] ?? fields["description"] ?? context.summaryText.slice(0, 200);

  return {
    shouldAlert: true,
    alertType: eventField,
    alertMessage: `[${context.useCase}] ${eventField}: ${severity} — ${desc}`,
  };
}

/**
 * TODO: use-case adapter hook — load a Python override for the given use case.
 * Looks for use-cases/{useCase}/evaluate_rules.py.
 * Falls back to defaultRuleEvaluator when the file doesn't exist.
 *
 * This is a stub. Use-case-specific adapters are implemented in a later phase.
 */
export async function evaluateWithOverride(
  context: RuleContext,
  useCasesDir: string,
): Promise<RuleResult> {
  const overridePath = resolve(useCasesDir, context.useCase, "evaluate_rules.py");

  if (!existsSync(overridePath)) {
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
      alertType: result.alert_type,
      alertMessage: result.alert_message,
    };
  } catch (err: any) {
    console.error(`[rule-engine] Python override failed for ${context.useCase}:`, err.message);
    return defaultRuleEvaluator(context);
  }
}
