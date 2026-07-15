# Use Case Adapter API Reference

The MCP server exposes a set of **MCP tools** for managing use case adapters at
runtime — creating, validating, and tearing down a scenario (`child_safety`,
`pet_safety`, `high_altitude_safety`, …) **without restarting the server and
without editing any core package**. This document is the **contract** for those
tools: given a tool name and an input object, the server applies the same schema
mutation, VLM-task registration, in-memory wiring, and config write-back
regardless of which MCP client issued the call.

Unlike the [webhook event API](./mcp_webhook_event_api.md) (a plain HTTP `POST`),
these are **JSON-RPC `tools/call` methods** delivered over the MCP transport
(stateful HTTP on `:3100/mcp`, or stdio). See the conceptual guide
[use-case-adapter.md](../use-case-adapter.md) for the adapter model and
[use-case-adapter-gsg.md](../use-case-adapter-gsg.md) for an end-to-end recipe.

Implementation entry points:
- Tool registration: [packages/mcp-server/src/tools.ts](../../packages/mcp-server/src/tools.ts)
- `smartbuilding_use_case_register`: [packages/tools/src/use-case-register.ts](../../packages/tools/src/use-case-register.ts)
- `smartbuilding_use_case_validate`: [packages/tools/src/use-case-validate.ts](../../packages/tools/src/use-case-validate.ts)
- `smartbuilding_prompt_lint`: [packages/tools/src/prompt-lint.ts](../../packages/tools/src/prompt-lint.ts)
- `generate_prompt` backend: [packages/tools/src/prompt-autogen.ts](../../packages/tools/src/prompt-autogen.ts)
- Rule evaluator (consumes `rules`): [packages/tools/src/rule-engine/index.ts](../../packages/tools/src/rule-engine/index.ts)

---

## 1. Transport & invocation

These are MCP tools, not REST endpoints. A client calls them via the standard
`tools/call` JSON-RPC method.

| Item | Value |
|------|-------|
| Transport | MCP stateful HTTP (`POST http://<mcp-host>:3100/mcp`) or stdio |
| Method | JSON-RPC `tools/call`, `params.name = <tool>`, `params.arguments = <input object>` |
| Session | Stateful HTTP requires an `initialize` handshake first; reuse the returned `Mcp-Session-Id` header on every subsequent call. A bare `tools/call` without a session is rejected with `Server not initialized`. See [use-case-adapter-gsg.md §3.3](../use-case-adapter-gsg.md). |
| Auth | None (loopback / intranet deployment) |
| Result shape | `result.content[0].text` is a **JSON string** — parse it once more to get the structured object documented below. |
| Error flag | Each tool sets `isError: true` in the tool result when the operation did not fully succeed (`register`/`generate_prompt`: `ok=false`; `validate`: `valid=false`; `prompt_lint`: `ok=false`). The structured body is still returned in `content[0].text`. |

### 1.1 Tool inventory

| Tool | Purpose | Mutates state? |
|------|---------|----------------|
| `smartbuilding_use_case_register` | Lifecycle management: `generate_prompt` (draft a prompt), `register` (schema + VLM task + wiring + optional config write-back), `unregister` (reverse). | `register`/`unregister`: yes. `generate_prompt`: no. |
| `smartbuilding_use_case_validate` | Read-only three-stage validation of an existing use case (known → task registered → prompt/schema consistent). | No |
| `smartbuilding_prompt_lint` | Static lint of a prompt string before registration. | No |
| `smartbuilding_video_summary_task` | Low-level management of VLM `/v1/tasks` (`list` / `get` / `delete`). Complements `register`. | `delete`: yes |

> The register tool is the one-call front door. `validate` / `prompt_lint` /
> `video_summary_task` are the read/inspect/low-level companions.

---

## 2. `smartbuilding_use_case_register`

Manage a use case's full lifecycle at runtime. One tool, three `action`s. The
in-memory `use_case_dict` is mutated by reference, so the task-poller and every
other tool observe changes on their next tick — no restart required.

### 2.1 Input schema (all actions)

| Field | Type | Required | Applies to | Description |
|-------|------|----------|------------|-------------|
| `action` | `"register" \| "unregister" \| "generate_prompt"` | ✅ | all | Which lifecycle operation to run. |
| `use_case` | `string` | ✅ | all | Use case key. Must match `/^[a-z][a-z0-9_]{1,63}$/`. |
| `video_summary_task` | `string` | ⚠️ | register | VLM task name. Default `<use_case>_monitor`. Must match the same regex and must **not** collide with a VLM builtin (`summary`, `summary_zh`). |
| `description` | `string` | ⚠️ | register / generate_prompt | Human description; shown by `/v1/tasks`. Required for `generate_prompt`. |
| `prompt_text` | `string` | ⚠️ | register | Full prompt. Either Markdown with `## LOCAL_PROMPT` / `## GLOBAL_PROMPT` sections, **or** a raw 4-constant Python source (detected by a `GLOBAL_PROMPT =` / `LOCAL_PROMPT =` token). Omit to skip VLM-task registration (see §2.6). |
| `rules` | `object` | ⚠️ | register | Free-form rules dict, copied **verbatim** into `use_case_dict.<uc>.rules`. Consumed by `defaultRuleEvaluator` (see §5) or passed to a Python override at `payload.rules`. |
| `schema_extensions` | `Array<{name, type, required}>` | ⚠️ | register / generate_prompt | Extra `video_summary_tasks` columns. `type ∈ {text, integer, real}`. Applied via idempotent `ALTER TABLE ADD COLUMN` and merged into the in-memory schema. |
| `evaluate_rules_path` | `string` | ⚠️ | register | Path to a Python `evaluate_rules.py` override. Omit for zero-Python (`defaultRuleEvaluator`) use cases. |
| `reports` | `object` | ⚠️ | register | Report config `{data_source, default_type, filter}`. Stored verbatim. |
| `summarize` | `object` | ⚠️ | register | Per-clip summarize config `{method, processor_kwargs}`. Stored verbatim. |
| `overwrite` | `boolean` | ⚠️ | register | Replace an existing `use_case_dict` entry. Default `false`; without it, registering an existing key is an error. |
| `persist` | `boolean` | ⚠️ | register / unregister | Mirror the mutation to the config.yaml the server booted from (comment-preserving via `yaml.Document`). Requires the server to have been started with `--config <path>`. A write failure is only a warning; the in-memory change still stands. |
| `event_types` | `Array<{name, severity, desc}>` | ⚠️ | generate_prompt | Semantic event triples the autogen meta-prompt turns into a `## LOCAL_PROMPT` draft. Must be non-empty for `generate_prompt`. |
| `language` | `"zh" \| "en"` | ⚠️ | generate_prompt | Output language of the generated prompt. Default `"zh"`. |

### 2.2 Output schema (all actions)

```jsonc
{
  "action":    "register",              // echo of the request action
  "use_case":  "pet_safety",
  "ok":        true,                    // false ⇒ tool result isError=true
  "steps": {
    "schema":        { "added": ["video_summary_tasks.pet_zone"], "warnings": [] },
    "vlm_task":      "registered",       // registered | updated | unchanged | deleted | skipped
    "use_case_dict": "added",            // added | updated | removed | skipped
    "config_yaml":   "written",          // written | removed | skipped
    "validate":      { /* UseCaseValidateResult — see §3.2 */ }
  },
  "generated_prompt": "## LOCAL_PROMPT\n…",  // generate_prompt only
  "lint":             { /* PromptLintResult — see §4.2 */ },  // generate_prompt only
  "next_steps":       ["1. Save …", "2. Refine …", "3. Register …"],  // generate_prompt only
  "warnings": [],
  "errors":   []
}
```

| `steps.*` field | Values | Meaning |
|-----------------|--------|---------|
| `schema` | `{added: string[], warnings: string[]}` | Columns actually added by `ALTER TABLE`. Empty `added` = all columns already existed (idempotent re-run). |
| `vlm_task` | `registered` \| `updated` \| `unchanged` \| `deleted` \| `skipped` | `registered` = `POST /v1/tasks` 201/200. `updated` = 409 → auto-`PATCH`. `deleted` = unregister removed it. `skipped` = no `prompt_text` given, or delete hit a builtin/absent task. |
| `use_case_dict` | `added` \| `updated` \| `removed` \| `skipped` | In-memory wiring outcome. `updated` requires `overwrite=true`. |
| `config_yaml` | `written` \| `removed` \| `skipped` | `written`/`removed` only when `persist=true` **and** the server has a `--config` path. Otherwise `skipped` (with a warning). |

### 2.3 `action=generate_prompt`

No state is mutated. Given `description` + `event_types` (+ optional
`schema_extensions`), the tool builds a meta-prompt encoding the four
production-tested prompt conventions (no pipe enums, no code fences, concrete
boundary examples, repeated "don't copy the example") and asks the configured
vLLM (`vlm_service.url`) to draft a `## LOCAL_PROMPT`. Human-in-the-loop by
design: review and refine `generated_prompt`, then call `action=register`.

**Preconditions**: `vlm_service` configured on the server; `description`
present; `event_types` non-empty. Missing any → `ok=false` with a message in
`errors`.

**Returns**: `generated_prompt` (draft text), `lint` (a `PromptLintResult`, see
§4.2, run over the draft), and `next_steps`. Any lint finding (code fence, pipe
enum, missing event) is surfaced in `warnings`.

### 2.4 `action=register`

Runs up to five steps in order; the first hard failure populates `errors` and
returns `ok=false`:

1. **Schema** — if `schema_extensions` given, `ALTER TABLE video_summary_tasks ADD COLUMN` (idempotent) and merge into the in-memory `config.schema`.
2. **VLM task** — if `prompt_text` given, `POST /v1/tasks`; on `409 Conflict`, auto-`PATCH /v1/tasks/<name>`. A Markdown prompt is assembled into the 4-constant form the service expects; a raw 4-const source is passed through unchanged.
3. **Wiring** — inject `{video_summary_task, description?, rules?, evaluate_rules_path?, …}` into `config.useCaseDict[use_case]`.
4. **Config write-back** — if `persist=true`, write the entry back to config.yaml.
5. **Validate** — re-run `use_case_validate` (§3); result nested at `steps.validate`. A failing validate is a **warning**, not an error — registration still stands.

> Guard: registering a `use_case` already present in `use_case_dict` without
> `overwrite=true` returns `ok=false` (`errors: ["… already exists …"]`) and
> mutates nothing.

### 2.5 `action=unregister`

`DELETE /v1/tasks/<video_summary_task>` and `delete config.useCaseDict[use_case]`.
If `persist=true`, the entry is also removed from config.yaml. Schema extension
columns are **not** rolled back (SQLite cannot drop a column without a table
rewrite). A builtin/absent VLM task yields `vlm_task: "skipped"` with a warning;
the `use_case_dict` removal still happens. Returns `ok=true` even when the VLM
delete is skipped.

### 2.6 Registering without a prompt

If `prompt_text` is omitted, step 2 is skipped (`vlm_task: "skipped"`) and a
warning is added: the VLM task must be registered out-of-band before this use
case can produce alerts. This is valid when the task already exists (e.g. a
builtin) or will be registered separately via `smartbuilding_video_summary_task`.

### 2.7 Example — register a zero-Python use case (`pet_safety`)

**Input** (`tools/call arguments`):

```json
{
  "action": "register",
  "use_case": "pet_safety",
  "video_summary_task": "pet_safety_monitor",
  "description": "Pet safety monitoring (dynamic)",
  "rules": {
    "severityThreshold": "warn",
    "excludeEvents": ["pet_normal", "no_incident"],
    "alertMessageExtraField": "pet_zone",
    "cooldownSeconds": 60
  },
  "summarize": { "method": "SIMPLE", "processor_kwargs": { "levels": 1, "level_sizes": [-1], "process_fps": 2 } },
  "prompt_text": "## LOCAL_PROMPT\n…",
  "schema_extensions": [{ "name": "pet_zone", "type": "text", "required": false }],
  "persist": true,
  "overwrite": true
}
```

**Output** (`result.content[0].text` parsed):

```json
{
  "action": "register",
  "use_case": "pet_safety",
  "ok": true,
  "steps": {
    "schema": { "added": ["video_summary_tasks.pet_zone"], "warnings": [] },
    "vlm_task": "registered",
    "use_case_dict": "added",
    "config_yaml": "written",
    "validate": {
      "valid": true,
      "use_case": "pet_safety",
      "video_summary_task": "pet_safety_monitor",
      "checks": { "use_case_known": true, "task_registered": true, "schema_consistent": true }
    }
  },
  "warnings": [],
  "errors": []
}
```

### 2.8 Example — unregister

**Input**: `{ "action": "unregister", "use_case": "pet_safety", "persist": true }`

**Output**:

```json
{
  "action": "unregister",
  "use_case": "pet_safety",
  "ok": true,
  "steps": { "vlm_task": "deleted", "use_case_dict": "removed", "config_yaml": "removed" },
  "warnings": [],
  "errors": []
}
```

---

## 3. `smartbuilding_use_case_validate`

Read-only, side-effect-free. Validates one use case end-to-end.

### 3.1 Input schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `use_case` | `string` | ✅ | Use case key from `config.yaml` `use_case_dict`. |

### 3.2 Output schema

```jsonc
{
  "valid":  true,                      // false ⇒ tool result isError=true
  "use_case": "pet_safety",
  "video_summary_task": "pet_safety_monitor",
  "checks": {
    "use_case_known":   true,          // exists in use_case_dict
    "task_registered":  true,          // GET /v1/tasks/<name> succeeded (not 404)
    "schema_consistent": true          // every required schema field appears in LOCAL_PROMPT
  },
  "required_fields":            ["event", "severity"],   // present when it reached check 3
  "optional_fields":            ["desc", "pet_zone"],
  "missing_required_in_prompt": [],
  "missing_optional_in_prompt": [],
  "prompt_tail":  "…last 200 chars…",  // only on schema_consistent=false
  "suggestion":   "Append the following required fields to LOCAL_PROMPT …",  // only on failure
  "error":        "unknown use_case \"…\". Known: [fridge, child_safety, …]"  // only on early failure
}
```

### 3.3 Behavior — three sequential checks

The checks run in order; the **first failure short-circuits** the rest (later
`checks.*` stay `false`). Read `valid` for a yes/no, or `checks` to know which
stage failed.

| # | Check | Fails when | `error` / `suggestion` |
|---|-------|-----------|------------------------|
| 1 | `use_case_known` | `use_case` not in `use_case_dict` | `error`: unknown use_case, lists known keys |
| 2 | `task_registered` | `GET /v1/tasks/<task>` returns 404, non-2xx, or the summary service is unreachable | `error`: task not registered / HTTP status / unreachable |
| 3 | `schema_consistent` | A **required** `schema.video_summary_tasks.extensions` field is absent from the task's `LOCAL_PROMPT` | `suggestion`: which required fields to append; `prompt_tail` for context |

> `register` (§2.4 step 5) and `monitor_ctl register_source` both call this
> internally as a pre-check, so a registered use case is validated the moment it
> is wired in.

---

## 4. `smartbuilding_prompt_lint`

Static, offline lint of a prompt string. No network, no state. Use it as a
quality gate for both LLM-generated drafts and hand-written `prompt.md`.

### 4.1 Input schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `prompt_text` | `string` | ✅ | Full prompt text to lint (typically `prompt.md` content). |
| `event_types` | `Array<{name, severity?, desc?}>` | ⚠️ Optional | Expected event names. Lint fails (`missing_event`) if any name is absent from `prompt_text`. |
| `schema_extensions` | `Array<{name, type?, required?, values?}>` | ⚠️ Optional | Schema fields. **Required** fields must appear in `prompt_text` (`missing_required_schema_field`). |
| `strict` | `boolean` | ⚠️ Optional | When `true`, warning-level findings also force `ok=false`. Default `false`. |

### 4.2 Output schema

```jsonc
{
  "ok":       true,          // errors empty AND (not strict OR warnings empty)
  "errors":   [],            // messages of severity=error
  "warnings": [],            // messages of severity=warning
  "issues": [               // full structured findings
    { "code": "pipe_enum", "severity": "warning", "message": "…", "details": { … } }
  ]
}
```

### 4.3 Lint checks

| `code` | Severity | Triggered by |
|--------|----------|--------------|
| `missing_local_prompt` | error | No `## LOCAL_PROMPT` section header. |
| `code_fence` | error | Contains triple-backtick ` ``` ` — `POST /v1/tasks` rejects these with `banned_token`. |
| `missing_event` | error | An expected `event_types[].name` does not appear in the prompt. |
| `missing_required_schema_field` | error | A `required` `schema_extensions` field name does not appear in the prompt. |
| `pipe_enum` | warning | Contains `A \| B \| C` pipe-separated enum syntax — small VLMs may echo the line verbatim. |
| `think_block` | warning | Contains Qwen-style `<think>` markup left in the draft. |

> `generate_prompt` (§2.3) runs this lint automatically over its draft and nests
> the result at `lint`; a standalone `prompt_lint` call with `strict=true` is the
> stricter gate for a human-refined `prompt.md`.

---

## 5. The `rules` contract (consumed by `defaultRuleEvaluator`)

The `rules` object passed to `register` is copied verbatim into
`use_case_dict.<uc>.rules` and reaches the rule engine at `payload.rules`. When
no Python override is wired (`evaluate_rules_path` omitted),
[`defaultRuleEvaluator`](../../packages/tools/src/rule-engine/index.ts) interprets
these keys (all optional):

| `rules` key | Type | Effect | Default |
|-------------|------|--------|---------|
| `severityThreshold` | `"info" \| "warn" \| "critical"` | Fires only when `fields.severity` is at or above this | `"warn"` |
| `excludeEvents` | `string[]` | These `fields.event` values never fire | `[]` |
| `requireEvent` | `string` | Whitelist a single `fields.event`; only it fires (still subject to severity) | — |
| `requireDirection` | `string` | `fields.motion_direction` must equal this (case-insensitive) | — |
| `excludeZones` | `string[]` | Matched against `fields.parking_zone`; matches never fire | — |
| `alertMessageExtraField` | `string` | Append `(label=value)` from `fields[<key>]` to the alert text; `label` is a short alias (`parking_zone`/`pet_zone`→`zone`, `motion_direction`→`direction`, else the field name) | — |
| `cooldownSeconds` | `number` | Suppress repeat alerts for the same use case within this window (applied by the caller when `create_alert=true`) | — |

> If `fields.severity` is missing or unrecognised, `defaultRuleEvaluator`
> short-circuits to `shouldAlert=false` **before** any threshold/filter check —
> this is why a `SEVERITY`-less prompt (e.g. `fridge`) is report-only.

Anything the `rules` keys cannot express (time comparisons, multi-event joins,
external calls) needs a Python override via `evaluate_rules_path`. Full override
I/O contract: [use-cases/README.md](../../use-cases/README.md).

---

## 6. Restart persistence

Which layer survives an MCP server restart depends on `persist`:

| Layer | Survives restart? |
|-------|-------------------|
| VLM `/v1/tasks/<name>` | ✅ Persisted inside the summary-service container. |
| `video_summary_tasks` schema columns | ✅ `ALTER TABLE` is on disk. |
| Monitors added via `monitor_ctl register_source` | ✅ Written to the SQLite `monitors` table. |
| `config.useCaseDict[<name>]` | ✅ with `persist:true` (written to config.yaml) · ❌ without (in-memory only) |

> Without `persist`, the DB columns / VLM task / monitor rows all remain, but a
> restart drops the in-memory `use_case_dict` entry — and any monitor that
> references it makes startup abort with `monitors reference unknown use_case
> keys`. Use `persist:true`, or unregister the monitor before restart. See
> [use-case-adapter-gsg.md §9.4](../use-case-adapter-gsg.md).

---

## 7. Related documents

- Adapter model & authoring recipe: [docs/use-case-adapter.md](../use-case-adapter.md)
- End-to-end test recipe (register → monitor → alert): [docs/use-case-adapter-gsg.md](../use-case-adapter-gsg.md)
- Rule override I/O protocol: [use-cases/README.md](../../use-cases/README.md)
- Webhook event ingestion API: [docs/apis/mcp_webhook_event_api.md](./mcp_webhook_event_api.md)
- Analytics-side REST API: [docs/apis/videostream_analytics_api.md](./videostream_analytics_api.md)
- Overall design: [docs/smartbuilding-video-design-2026.2.md](../smartbuilding-video-design-2026.2.md)
- Rule evaluator source: [packages/tools/src/rule-engine/index.ts](../../packages/tools/src/rule-engine/index.ts)
