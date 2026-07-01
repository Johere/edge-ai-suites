# Use Case Adapters

Each subdirectory here is a **use case adapter**: the small amount of code and
prompt content that specialises the generic MCP server to a specific scenario
(e.g. `child_safety`, `elder_wakeup`, `fridge`). Directories are wired into the
server via `config.yaml` → `use_case_dict.<name>`.

The framework is designed so that adding a new use case does not require
modifying core components — a new directory plus a `use_case_dict` entry is
enough.

## Directory layout

```
use-cases/
├── README.md                     # this file
├── child_safety/
│   ├── evaluate_rules.py         # optional Python rule override (see §1)
│   └── prompt.md                 # VLM task prompt (see §2)
├── elder_wakeup/
│   ├── evaluate_rules.py
│   └── prompt.md
└── fridge/
    ├── config.md                 # per-use-case notes
    ├── evaluate_rules.py         # no-alert stub
    ├── prompt.md                 # Chinese task prompt
    └── prompt_en.md              # English variant
```

Missing files are legal:

- No `evaluate_rules.py` — the built-in `defaultRuleEvaluator` fires when the
  parsed `severity` field is `critical` or `warn`.
- No `prompt.md` — the VLM task registration step is skipped; monitors of this
  use case rely on prompts registered out of band.

## 1. `evaluate_rules.py` protocol

Invoked by `packages/rule-engine/src/index.ts` (`evaluateWithOverride`) via
`execFile("python3", [<script>, <json>])`.

**Input** — `sys.argv[1]` is a JSON-encoded `RuleContext` object:

```jsonc
{
  "monitorId": "cam_child_01",
  "useCase":   "child_safety",
  "taskId":    42,
  "summaryText": "SEVERITY: critical\nEVENT: child_fall\nDESC: ...",
  "payload": {
    "fields": {                                // parsed by built-in summary parser
      "severity":    "critical",
      "event":       "child_fall",
      "desc":        "child fell from sofa",
      "description": "child fell from sofa"    // legacy alias
    },
    "rules": {                                 // from config.yaml use_case_dict.<name>.rules
      "severityThreshold": "warn"
    }
  }
}
```

**Output** — a single JSON object on `stdout`:

```jsonc
{
  "should_alert": true,
  "alert_message": "[child_safety] child_fall: critical — child fell from sofa"
}
```

Contract:

| Field | Required | Type | Meaning |
|-------|----------|------|---------|
| `should_alert` | ✅ | `bool` | Whether an alert row should be inserted for this task. |
| `alert_message` | conditional | `string` | Populated when `should_alert` is `true`. Stored verbatim in `alerts.description`. |

If the script exits non-zero, prints invalid JSON, or throws, the caller falls
back to `defaultRuleEvaluator`; the failure is logged at `warn` and does not
abort the task-poller loop.

## 2. `prompt.md` protocol

Declares the VLM task prompt shipped to `multilevel-video-understanding`.

A `prompt.md` file is a plain Markdown document divided by `##` headings, one
heading per prompt section:

```markdown
Free-form intro / rationale for the prompt (optional).

## LOCAL_PROMPT

...per-clip prompt content, including the required output shape...

## GLOBAL_PROMPT

...aggregation prompt used by the report generator...
```

Recognised section names (all optional; only the ones the operator registers
need to be present):

| Section | Purpose |
|---------|---------|
| `LOCAL_PROMPT` | Per-clip prompt used when the video-worker calls `POST /v1/summary` for a single motion segment. Must produce output the built-in `parseSummaryFields` parser can decode (line-oriented `KEY: value`, keys aligned with the DB schema). |
| `GLOBAL_PROMPT` | Aggregation prompt used by the report generator (daily / weekly summary flow). Consumes SRT-style captions built from stored events. |
| `MACRO_CHUNK_PROMPT` | Optional per-macro-chunk prompt for chained summaries. When absent the summary service falls back to `GLOBAL_PROMPT`. |
| `T_MINUS_1_PROMPT` | Optional context prompt for the preceding chunk (used by chained motion segments). |

Everything above the first `##` heading is treated as intro prose and ignored
at runtime.

Both `LOCAL_PROMPT` and `GLOBAL_PROMPT` may reference the following
placeholders, filled by the VLM service at request time:

| Placeholder | Meaning |
|-------------|---------|
| `{question}` | Optional user question forwarded to the VLM. |
| `{st_tm}` | Chunk start time in seconds. |
| `{end_tm}` | Chunk end time in seconds. |
| `{dur}` | Duration of the preceding chunk (used by chained summaries). |
| `{past_summary}` | Summary of the preceding chunk. |

**Format history**: earlier revisions of these adapters shipped `prompt.py`
files whose sole purpose was to hold `NAME = '''...'''` string constants.
Nothing ever executed as Python — the file was read verbatim as text and
POSTed to the VLM `/v1/tasks` endpoint. Switching to Markdown makes that
reality explicit and gives editors syntax highlighting for prose, tables, and
placeholders without the `'''` clutter.

**Runtime loading**: at present, prompt files are registered out of band by
the operator flow; the MCP server does not import them automatically.
`smartbuilding_use_case_validate` continues to work — it fetches the task's
`LOCAL_PROMPT` string from the VLM service and searches for required schema
field names, unchanged by this format switch.

## Scope in Phase 10

`parse_summary.py` and `on_task_completed.py` overrides listed in the design
document are wired via optional `use_case_dict.<uc>.parse_summary_path` /
`on_task_completed_path` config keys — the built-in summary parser and a
fire-and-forget subprocess callback respectively. See
[docs/use-case-adapter.md](../docs/use-case-adapter.md) for the full recipe.
