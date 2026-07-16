import { SchemaManager, type SchemaDefinition } from "@smartbuilding-video/db";

export interface UseCaseValidateParams {
  use_case: string;
}

export interface UseCaseValidateDeps {
  /** Loaded use_case_dict from config.yaml; `video_summary_task` + optional `rules` are read here. */
  useCaseDict: Record<string, { video_summary_task: string; rules?: Record<string, unknown> }>;
  /** multilevel-video-understanding service base URL (e.g. http://localhost:8192). */
  summaryServiceUrl: string;
  /** config.schema for required-field discovery. */
  schema?: SchemaDefinition;
}

export interface UseCaseValidateResult {
  valid: boolean;
  use_case: string;
  video_summary_task?: string;
  checks: {
    use_case_known: boolean;
    task_registered: boolean;
    schema_consistent: boolean;
    /** Every field a `rules` key depends on is declared in schema.extensions. Warn-only — never flips `valid`. */
    rules_schema_consistent: boolean;
  };
  required_fields?: string[];
  optional_fields?: string[];
  missing_required_in_prompt?: string[];
  missing_optional_in_prompt?: string[];
  prompt_tail?: string;
  suggestion?: string;
  /** Non-fatal advisories (e.g. a `rules` key references a field not declared in schema). */
  warnings?: string[];
  error?: string;
}

/**
 * Which schema field each built-in `rules` key dereferences (see
 * rule-engine defaultRuleEvaluator). A rule that reads a field the schema never
 * declares silently sees an empty value, so its logic never fires — this map
 * lets us surface that as a warning at validate/register time.
 */
const RULE_FIELD_DEPS: Record<string, string> = {
  severityThreshold: "severity",
  excludeEvents: "event",
  requireEvent: "event",
  requireDirection: "motion_direction",
  excludeZones: "parking_zone",
};

/**
 * Warn when a `rules` key references a schema field that isn't declared in
 * `schema.video_summary_tasks.extensions`. `alertMessageExtraField` is special:
 * its VALUE is the field name. Warn-only — a Python override may supply the
 * field itself, so this never fails validation.
 */
function checkRulesSchema(
  rules: Record<string, unknown> | undefined,
  extensionNames: Set<string>,
): string[] {
  if (!rules) return [];
  const warnings: string[] = [];
  for (const [key, depField] of Object.entries(RULE_FIELD_DEPS)) {
    if (key in rules && !extensionNames.has(depField)) {
      warnings.push(
        `rules.${key} depends on schema field "${depField}", which is not declared in schema.video_summary_tasks.extensions — the rule will read an empty value and never fire (unless a Python override supplies it).`,
      );
    }
  }
  const extra = rules["alertMessageExtraField"];
  if (typeof extra === "string" && !extensionNames.has(extra)) {
    warnings.push(
      `rules.alertMessageExtraField="${extra}" is not a declared schema field — the alert message suffix will be omitted.`,
    );
  }
  return warnings;
}

/**
 * One-stop validation of a use_case: existence, summary-service task registration,
 * and prompt ↔ schema consistency.
 *
 * Three sequential checks; the first failure short-circuits the rest.
 * Caller may rely on `valid` for a single yes/no, or read `checks` to know
 * which stage failed.
 */
export async function useCaseValidate(
  params: UseCaseValidateParams,
  deps: UseCaseValidateDeps,
): Promise<UseCaseValidateResult> {
  const checks = {
    use_case_known: false,
    task_registered: false,
    schema_consistent: false,
    rules_schema_consistent: true,
  };

  // 1. use_case existence
  const ucCfg = deps.useCaseDict[params.use_case];
  if (!ucCfg) {
    return {
      valid: false,
      use_case: params.use_case,
      checks,
      error: `unknown use_case "${params.use_case}". Known: [${Object.keys(deps.useCaseDict).join(", ")}]`,
    };
  }
  checks.use_case_known = true;
  const taskName = ucCfg.video_summary_task;

  // rules ↔ schema consistency (warn-only, computed early so it survives any
  // later short-circuit return). Does not affect `valid`.
  const extensionNames = new Set(
    (deps.schema?.video_summary_tasks?.extensions ?? []).map((e) => e.name),
  );
  const warnings = checkRulesSchema(ucCfg.rules, extensionNames);
  checks.rules_schema_consistent = warnings.length === 0;
  const warningsOut = warnings.length > 0 ? { warnings } : {};

  // 2. summary-service connectivity + task existence
  let taskBody: any;
  try {
    const resp = await fetch(`${deps.summaryServiceUrl}/v1/tasks/${taskName}`, {
      signal: AbortSignal.timeout(8000),
    });
    if (resp.status === 404) {
      return {
        valid: false, use_case: params.use_case, video_summary_task: taskName, checks, ...warningsOut,
        error: `task "${taskName}" not registered in multilevel-video-understanding (${deps.summaryServiceUrl}). Register first: POST /v1/tasks`,
      };
    }
    if (!resp.ok) {
      return {
        valid: false, use_case: params.use_case, video_summary_task: taskName, checks, ...warningsOut,
        error: `failed to verify task "${taskName}": HTTP ${resp.status}`,
      };
    }
    taskBody = await resp.json();
  } catch (err: any) {
    return {
      valid: false, use_case: params.use_case, video_summary_task: taskName, checks, ...warningsOut,
      error: `summary service unreachable (${deps.summaryServiceUrl}): ${err.message}`,
    };
  }
  checks.task_registered = true;

  // 3. schema consistency: required schema fields must appear in LOCAL_PROMPT
  const extensions = deps.schema?.video_summary_tasks?.extensions ?? [];
  const localPrompt = extractLocalPrompt(taskBody);
  const check = SchemaManager.validatePromptSchema(extensions, localPrompt);
  checks.schema_consistent = check.valid;

  const base = {
    use_case: params.use_case,
    video_summary_task: taskName,
    checks,
    ...warningsOut,
    required_fields: check.requiredFields,
    optional_fields: check.optionalFields,
    missing_required_in_prompt: check.missingRequired,
    missing_optional_in_prompt: check.missingOptional,
  };

  if (!checks.schema_consistent) {
    return {
      ...base,
      valid: false,
      prompt_tail: localPrompt.slice(-200),
      suggestion: `Append the following required fields to LOCAL_PROMPT of "${taskName}": ${check.missingRequired.join(", ")}`,
    };
  }

  return { ...base, valid: true };
}

/**
 * Pull LOCAL_PROMPT from the task body. The summary service may expose it under
 * several key paths depending on version; try the common ones and fall back to
 * stringifying the body so substring search still works.
 */
function extractLocalPrompt(taskBody: any): string {
  if (!taskBody || typeof taskBody !== "object") return "";
  return (
    taskBody.LOCAL_PROMPT ??
    taskBody.local_prompt ??
    taskBody.prompts?.LOCAL_PROMPT ??
    taskBody.prompts?.local_prompt ??
    JSON.stringify(taskBody)
  );
}
