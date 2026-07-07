export interface PromptLintEventType {
  name: string;
  severity?: string;
  desc?: string;
}

export interface PromptLintSchemaExtension {
  name: string;
  type?: string;
  required?: boolean;
  values?: string[];
}

export type PromptLintIssueSeverity = "error" | "warning";

export interface PromptLintIssue {
  code:
    | "missing_local_prompt"
    | "code_fence"
    | "pipe_enum"
    | "missing_event"
    | "missing_required_schema_field"
    | "think_block";
  severity: PromptLintIssueSeverity;
  message: string;
  details?: Record<string, unknown>;
}

export interface PromptLintParams {
  prompt_text: string;
  event_types?: PromptLintEventType[];
  schema_extensions?: PromptLintSchemaExtension[];
  /** When true, warning-level findings also make `ok=false`. */
  strict?: boolean;
}

export interface PromptLintResult {
  ok: boolean;
  errors: string[];
  warnings: string[];
  issues: PromptLintIssue[];
}

const CODE_FENCE_RE = /```/;
const PIPE_ENUM_RE = /\b[\w-]+\s*\|\s*[\w-]+\s*\|\s*[\w-]+\b/;
const THINK_BLOCK_RE = /<think>[\s\S]*?<\/think>|<think>|<\/think>/i;
const LOCAL_PROMPT_RE = /^\s*##\s+LOCAL_PROMPT\b/mi;

export function promptLint(params: PromptLintParams): PromptLintResult {
  const prompt = params.prompt_text ?? "";
  const issues: PromptLintIssue[] = [];

  if (!LOCAL_PROMPT_RE.test(prompt)) {
    issues.push({
      code: "missing_local_prompt",
      severity: "error",
      message: "prompt is missing a `## LOCAL_PROMPT` section header",
    });
  }

  if (CODE_FENCE_RE.test(prompt)) {
    issues.push({
      code: "code_fence",
      severity: "error",
      message:
        "prompt contains triple-backtick code fence — POST /v1/tasks rejects these with banned_token",
    });
  }

  if (PIPE_ENUM_RE.test(prompt)) {
    issues.push({
      code: "pipe_enum",
      severity: "warning",
      message:
        "prompt contains `A | B | C` pipe-separated enum syntax — small VLMs may echo the whole line verbatim",
    });
  }

  if (THINK_BLOCK_RE.test(prompt)) {
    issues.push({
      code: "think_block",
      severity: "warning",
      message: "prompt contains Qwen-style `<think>` markup; strip it before registering the VLM task",
    });
  }

  const eventNames = (params.event_types ?? [])
    .map((event) => event.name)
    .filter((name) => name.length > 0);
  const missingEvents = eventNames.filter((name) => !containsToken(prompt, name));
  if (missingEvents.length > 0) {
    issues.push({
      code: "missing_event",
      severity: "error",
      message: `event names missing from prompt: ${missingEvents.join(", ")}`,
      details: { missing_events: missingEvents },
    });
  }

  const requiredFields = (params.schema_extensions ?? [])
    .filter((field) => field.required)
    .map((field) => field.name)
    .filter((name) => name.length > 0);
  const missingFields = requiredFields.filter((name) => !containsToken(prompt, name));
  if (missingFields.length > 0) {
    issues.push({
      code: "missing_required_schema_field",
      severity: "error",
      message: `required schema fields missing from prompt: ${missingFields.join(", ")}`,
      details: { missing_required_schema_fields: missingFields },
    });
  }

  const errors = issues
    .filter((issue) => issue.severity === "error")
    .map((issue) => issue.message);
  const warnings = issues
    .filter((issue) => issue.severity === "warning")
    .map((issue) => issue.message);

  return {
    ok: errors.length === 0 && (!params.strict || warnings.length === 0),
    errors,
    warnings,
    issues,
  };
}

function containsToken(text: string, token: string): boolean {
  const escaped = token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(^|[^A-Za-z0-9_])${escaped}([^A-Za-z0-9_]|$)`, "i").test(text);
}