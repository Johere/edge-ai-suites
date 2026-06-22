import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

const execFileAsync = promisify(execFile);

export interface RuleContext {
  monitorId: string;
  useCaseId: string;
  event: string;
  severity: string;
  payload: Record<string, unknown>;
}

export interface RuleResult {
  shouldAlert: boolean;
  alertMessage?: string;
}

export type RuleEvaluator = (context: RuleContext) => Promise<RuleResult>;

const SEVERITY_LEVELS: Record<string, number> = {
  low: 1,
  medium: 2,
  high: 3,
  critical: 4,
};

/**
 * Default rule engine: triggers alert when severity >= threshold
 * and event is not in the exclusion list.
 */
export async function defaultRuleEvaluator(context: RuleContext): Promise<RuleResult> {
  const level = SEVERITY_LEVELS[context.severity.toLowerCase()] ?? 0;
  const threshold = 2;

  return {
    shouldAlert: level >= threshold,
    alertMessage: level >= threshold
      ? `[${context.useCaseId}] ${context.event}: ${context.severity}`
      : undefined,
  };
}

/**
 * Attempts to load a Python callback override for the given use case.
 * Looks for use-cases/{useCaseId}/evaluate_rules.py
 */
export async function evaluateWithOverride(
  context: RuleContext,
  useCasesDir: string,
): Promise<RuleResult> {
  const overridePath = resolve(useCasesDir, context.useCaseId, "evaluate_rules.py");

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
      alertMessage: result.alert_message,
    };
  } catch (err: any) {
    console.error(`[rule-engine] Python override failed for ${context.useCaseId}:`, err.message);
    return defaultRuleEvaluator(context);
  }
}
