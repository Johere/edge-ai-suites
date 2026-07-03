/**
 * LLM-assisted prompt generation for new use cases (Design §5.2 Step 3).
 *
 * Users provide 3 semantic inputs (`description` + `event_types` + optional
 * `schema_extensions`); this function crafts a meta-prompt encoding the 4
 * production-tested conventions from `use-case-adapter.md §Prompt writing
 * conventions` and asks the local vLLM (`vlm_service.url`) to emit a
 * `## LOCAL_PROMPT` draft.
 *
 * Human-in-the-loop by design: the caller reviews the returned draft, refines
 * business-specific boundaries manually, then registers via
 * `smartbuilding_use_case_register action=register` with the refined text.
 * This function itself never writes to disk, never touches useCaseDict,
 * never registers the VLM task.
 */

export interface PromptAutogenEventType {
  name: string;
  severity: string;
  desc: string;
}

export interface PromptAutogenSchemaExtension {
  name: string;
  type: string;
  required: boolean;
  /** Allowed literal values, if the extension is a categorical field. */
  values?: string[];
}

export interface GeneratePromptParams {
  use_case: string;
  description: string;
  event_types: PromptAutogenEventType[];
  schema_extensions?: PromptAutogenSchemaExtension[];
  /** Output language for the generated prompt. Default "zh". */
  language?: "zh" | "en";
}

export interface GeneratePromptDeps {
  /** vllm-serving-ipex base URL, e.g. `http://localhost:41091/v1`. */
  vlmUrl: string;
  /** Model name recognised by the vLLM server. Default `"default"`. */
  model?: string;
}

export interface GeneratePromptResult {
  ok: boolean;
  use_case: string;
  generated_prompt?: string;
  /** Non-fatal lint findings (e.g. detected code fence, pipe enum, missing field). */
  warnings: string[];
  errors: string[];
  next_steps?: string[];
}

const REQUEST_TIMEOUT_MS = 120_000;
const CODE_FENCE_RE = /```/;
const PIPE_ENUM_RE = /\b\w+\s*\|\s*\w+\s*\|\s*\w+\b/;

export async function generatePrompt(
  params: GeneratePromptParams,
  deps: GeneratePromptDeps,
): Promise<GeneratePromptResult> {
  const result: GeneratePromptResult = {
    ok: false,
    use_case: params.use_case,
    warnings: [],
    errors: [],
  };

  if (!params.use_case || !params.description) {
    result.errors.push("use_case and description are required");
    return result;
  }
  if (!Array.isArray(params.event_types) || params.event_types.length === 0) {
    result.errors.push("event_types must be a non-empty array");
    return result;
  }

  const language = params.language ?? "zh";
  const systemMsg = buildSystemMessage(language);
  const userMsg = buildUserMessage(params, language);
  const model = deps.model ?? "default";

  let raw: string;
  try {
    const resp = await fetch(`${deps.vlmUrl}/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model,
        messages: [
          { role: "system", content: systemMsg },
          { role: "user", content: userMsg },
        ],
        max_tokens: 2048,
        temperature: 0.3,
        chat_template_kwargs: { enable_thinking: false },
      }),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    if (!resp.ok) {
      const detail = await resp.text().catch(() => "");
      result.errors.push(`vLLM HTTP ${resp.status}: ${detail.slice(0, 200)}`);
      return result;
    }
    const body = (await resp.json()) as {
      choices?: Array<{ message?: { content?: string } }>;
    };
    raw = body.choices?.[0]?.message?.content ?? "";
  } catch (err: any) {
    result.errors.push(`vLLM request failed: ${err.message}`);
    return result;
  }

  if (!raw.trim()) {
    result.errors.push("vLLM returned empty content");
    return result;
  }

  // Strip <think>...</think> blocks that Qwen3-style models emit
  let cleaned = raw.replace(/<think>[\s\S]*?<\/think>\s*/g, "").trim();

  // Ensure the draft opens with the section header the register pipeline expects
  if (!/^##\s+LOCAL_PROMPT\b/.test(cleaned)) {
    cleaned = `## LOCAL_PROMPT\n\n${cleaned}`;
  }

  // Post-processing lint checks
  if (CODE_FENCE_RE.test(cleaned)) {
    result.warnings.push(
      "generated prompt contains triple-backtick code fence — POST /v1/tasks will reject with banned_token; edit manually before register",
    );
  }
  if (PIPE_ENUM_RE.test(cleaned)) {
    result.warnings.push(
      "generated prompt contains `A | B | C` pipe-separated enum — small VLMs may echo the whole line verbatim (see Convention 1); consider refining",
    );
  }
  const eventNames = params.event_types.map((e) => e.name);
  const missingEvents = eventNames.filter((n) => !cleaned.includes(n));
  if (missingEvents.length > 0) {
    result.warnings.push(
      `event names missing from generated prompt: ${missingEvents.join(", ")} — model may have hallucinated / dropped events; verify before register`,
    );
  }

  result.generated_prompt = cleaned;
  result.next_steps = [
    `1. Save 'generated_prompt' to use-cases/${params.use_case}/prompt.md`,
    "2. Manually refine business boundaries — spell out concrete edge cases (see Convention 3 in use-case-adapter.md)",
    `3. Call smartbuilding_use_case_register action=register with prompt_text=$(cat use-cases/${params.use_case}/prompt.md) persist=true`,
  ];
  result.ok = true;
  return result;
}

function buildSystemMessage(language: "zh" | "en"): string {
  const zh = `你是为小型视觉语言模型（VLM）监控 10 秒监控视频片段编写 prompt 的专家。你要生成一个新 use case 的 \`## LOCAL_PROMPT\` 段。以下 4 条规则来自生产环境的失败经验，不可违反：

规则 1（禁止管道枚举语法）：绝对不要使用 \`A | B | C\` 这种管道分隔枚举，小模型会照抄整行。要用两个部分表达：(a) 一到两个具体的"输出示例"块（用 4 空格缩进），(b) 一个纯文本的"字段取值范围:"列表。

规则 2（禁止 markdown 代码块）：绝对不要使用 markdown 三反引号代码块 \\\`\\\`\\\`。video-summary 服务的 POST /v1/tasks 会以 banned_token 拒收含三反引号的 prompt。用 4 空格缩进或"以下是示例:"这类散文替代。

规则 3（业务边界必须具体）：业务规则必须列举具体案例，不要用抽象短语。例如不要写"非自然物"，要写"塑料袋、瓶子、纸盒、烟头、饮料罐、衣物、玩具、生活垃圾"。

规则 4（在 prompt 末尾重复禁令）：在 prompt 结尾重复"不要照抄示例"和"只输出 <字段> 三行"这类禁令（长 prompt 里位置很重要）。

结构输出为：
  # 一句话任务目标
  # 输入说明（10 秒 RTSP 摄像头片段监控 …）
  # 输出字段（含类型 + 取值范围）
  # 输出示例 1（positive case，4 空格缩进）
  # 输出示例 2（negative case，4 空格缩进）
  # 业务边界规则（具体案例枚举）
  # 禁止事项（不要输出 JSON、不要加 markdown、不要照抄示例、只输出 <字段> 若干行）

严禁在响应中包含任何 markdown 代码块（\\\`\\\`\\\`）。只输出纯粹的 \`## LOCAL_PROMPT\` 段内容，前面不要加解释性的语言。`;

  const en = `You are a prompt engineer writing prompts for small vision-language models (VLMs) monitoring 10-second surveillance camera clips. Generate a \`## LOCAL_PROMPT\` section for a new use case. Follow these 4 non-negotiable rules learned from real production failures:

RULE 1 (no pipe enum): Never use pipe-separated enum syntax \`A | B | C\` — small VLMs echo the entire line back verbatim. Use two blocks instead: (a) one or two concrete "output example" blocks (4-space indent), (b) a plain-text "allowed values:" list.

RULE 2 (no markdown code fence): Never use markdown triple-backtick code fences \\\`\\\`\\\`. The video-summary service's POST /v1/tasks rejects prompts containing triple backticks with banned_token. Use 4-space indentation or plain "here is an example:" prose instead.

RULE 3 (concrete boundaries): Business boundaries MUST be spelled out with concrete examples, not abstract phrases. E.g. do NOT say "non-natural objects", DO say "plastic bag, bottle, cardboard, cigarette butt, drink can, clothing, toy, household trash".

RULE 4 (repeat prohibitions at the end): At the END of the prompt, repeat "do not copy the examples verbatim" and "only output the <fields> lines" (position matters in long prompts).

STRUCTURE the output as:
  # One-line goal
  # Input description (10-second RTSP camera clip monitoring …)
  # Output fields (with types + allowed values)
  # Positive example (4-space indent)
  # Negative example (4-space indent)
  # Business boundary rules (concrete case enumeration)
  # Prohibitions (no JSON, no markdown, no verbatim copy, only <fields> lines)

Absolutely do NOT include any markdown code fence (\\\`\\\`\\\`) in your response. Output only the \`## LOCAL_PROMPT\` section content directly, without preamble.`;

  return language === "zh" ? zh : en;
}

function buildUserMessage(params: GeneratePromptParams, language: "zh" | "en"): string {
  const events = params.event_types
    .map((e) => `  - ${e.name} (${e.severity}): ${e.desc}`)
    .join("\n");
  const extensions = (params.schema_extensions ?? [])
    .map((s) => {
      const values = s.values && s.values.length > 0 ? ` — 取值: ${s.values.join(", ")}` : "";
      return `  - ${s.name} (${s.type}, ${s.required ? "required" : "optional"})${values}`;
    })
    .join("\n");

  if (language === "en") {
    return [
      `Use case name: ${params.use_case}`,
      `Description: ${params.description}`,
      "",
      "Event types (name — severity — description):",
      events,
      extensions ? "\nSchema extension fields (extra columns on video_summary_tasks):\n" + extensions : "",
      "",
      "Required output fields the VLM must emit for every clip:",
      "  - SEVERITY (critical|warn|info)",
      "  - EVENT (one of the event names above)",
      "  - DESC (one-sentence Chinese/English description)",
      (params.schema_extensions ?? []).length > 0
        ? "  - Plus each schema extension field name in UPPER_CASE"
        : "",
      "",
      "Now emit the `## LOCAL_PROMPT` section. Follow all 4 rules from the system message.",
    ]
      .filter(Boolean)
      .join("\n");
  }

  return [
    `Use case 名称: ${params.use_case}`,
    `描述: ${params.description}`,
    "",
    "事件类型 (name — severity — 描述):",
    events,
    extensions ? "\nSchema 扩展字段 (video_summary_tasks 的额外列):\n" + extensions : "",
    "",
    "VLM 每个片段必须输出的字段:",
    "  - SEVERITY (critical|warn|info)",
    "  - EVENT (上述 event 名字之一)",
    "  - DESC (一句话中文描述)",
    (params.schema_extensions ?? []).length > 0
      ? "  - 加上每个 schema 扩展字段（大写字段名）"
      : "",
    "",
    "现在请生成 `## LOCAL_PROMPT` 段内容。严格遵循 system message 里的 4 条规则。",
  ]
    .filter(Boolean)
    .join("\n");
}
