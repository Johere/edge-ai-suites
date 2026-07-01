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
│   └── prompt.py                 # VLM task prompt (see §2)
├── elder_wakeup/
│   ├── evaluate_rules.py
│   └── prompt.py
└── fridge/
    └── prompt.py                 # no override → defaultRuleEvaluator applies
```

Missing files are legal:

- No `evaluate_rules.py` — the built-in `defaultRuleEvaluator` fires when the
  parsed `severity` field is `critical` or `warn`.
- No `prompt.py` — the VLM task registration step is skipped; monitors of this
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

## 2. `prompt.py` protocol

Declares the VLM task prompt shipped to `multilevel-video-understanding`. Each
`prompt.py` exports two module-level string constants:

| Constant | Purpose |
|----------|---------|
| `LOCAL_PROMPT` | Per-clip prompt used when the video-worker calls `POST /v1/summary` for a single motion segment. Must produce output that the built-in `parseSummaryFields` parser can decode (line-oriented `KEY: value`, keys aligned with the DB schema). |
| `GLOBAL_PROMPT` | Aggregation prompt used by the report generator (daily / weekly summary flow). Consumes SRT-style captions built from stored events. |

Both strings may reference the following placeholders, filled by the VLM
service at request time:

| Placeholder | Meaning |
|-------------|---------|
| `{question}` | Optional user question forwarded to the VLM. |
| `{st_tm}` | Chunk start time in seconds. |
| `{end_tm}` | Chunk end time in seconds. |
| `{dur}` | Duration of the preceding chunk (used by chained summaries). |
| `{past_summary}` | Summary of the preceding chunk. |

`prompt.py` is currently loaded by the operator flow (registering a VLM task);
the runtime service does not import it automatically. Keeping the prompts under
the use-case directory means one source of truth per scenario.

## Scope in Phase 10

`parse_summary.py` and `on_task_completed.py` overrides listed in the design
document are **not** wired up in this phase — the built-in summary parser
covers every current use case and `on_task_completed` behaviour is provided
via MCP resource notifications. See dev tracker "十六、Phase 10 §6".
