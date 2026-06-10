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

/**
 * Default rule engine: triggers alert when severity >= threshold
 * and event is not in the exclusion list.
 */
export async function defaultRuleEvaluator(context: RuleContext): Promise<RuleResult> {
  const severityLevels: Record<string, number> = {
    low: 1,
    medium: 2,
    high: 3,
    critical: 4,
  };

  const level = severityLevels[context.severity.toLowerCase()] ?? 0;
  const threshold = 2; // medium and above

  return {
    shouldAlert: level >= threshold,
    alertMessage: level >= threshold
      ? `[${context.useCaseId}] ${context.event}: ${context.severity}`
      : undefined,
  };
}
