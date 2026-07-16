# Use Case Adapter Guide

This document explains how the smart-community MCP server uses **use case
adapters** to specialise its generic pipeline to a particular scenario
(`child_safety`, `elder_wakeup`, `fridge`, …), and how to add a new use case
without modifying any core packages. See the design document §5 for the
architectural framing; this file is the operator-facing recipe.

Core packages are use-case agnostic. Everything scenario-specific lives in
**one directory per use case** under `use-cases/`, wired in via a single
`use_case_dict.<name>` entry in `config.yaml`.

## 1. Directory layout

```
smart-community/
├── use-cases/
│   ├── README.md                 # protocol reference for override authors
│   ├── child_safety/
│   │   └── prompt.md             # no evaluate_rules.py — uses defaultRuleEvaluator
│   ├── elder_wakeup/
│   │   ├── evaluate_rules.py     # time comparison → needs a Python override
│   │   └── prompt.md
│   ├── fridge/
│   │   ├── config.md             # per-use-case notes
│   │   ├── prompt.md             # Chinese prompt (report-only, no evaluate_rules.py)
│   │   └── prompt_en.md          # English variant
│   ├── high_altitude_safety/     # extension template (prompt only — NOT wired into config.yaml.example)
│   │   └── prompt.md
│   ├── parking_safety/           # extension template (prompt only — NOT wired into config.yaml.example)
│   │   └── prompt.md
│   └── pet_safety/               # dynamic-register demo (see use-case-adapter-gsg.md §9)
│       ├── evaluate_rules.py
│       └── prompt.md
└── config.yaml                   # wiring via use_case_dict.<name>
```

> Only `elder_wakeup` (and the `pet_safety` demo) ship a Python override.
> `child_safety` / `fridge` are handled by `defaultRuleEvaluator` — no Python.
> `config.yaml.example` only wires up `fridge` / `child_safety` / `elder_wakeup`;
> `high_altitude_safety` / `parking_safety` are prompt-only templates you register
> yourself (see [use-case-adapter-gsg.md §9.7](./use-case-adapter-gsg.md); the
> `pet_safety` walkthrough in §9 is the canonical dynamic-register recipe).

## 2. Runtime flow

```
videostream-analytics → POST /events → EventsEndpoint
                                          │
                                          ▼
                       video_summary_tasks row (pending)
                                          ▲
                                          │ 5 s poll
                                          ▼
                                  TaskPoller (task-poller.ts)
                                          │
                                          │ clip → VLM summary_service
                                          ▼
                       summary_text saved to DB row
                                          │
                                          │ parseSummaryFields → fields dict
                                          ▼
                          RuleContext {monitorId, useCase, taskId,
                                       summaryText,
                                       payload: {fields}}
                                          │
                              ┌───────────┴───────────┐
                              │                       │
                        evaluate_rules_path?          no override
                              │                       │
                              ▼                       ▼
                     execFile python3 <path>   defaultRuleEvaluator
                              │                       │
                              └───────────┬───────────┘
                                          │
                                {should_alert, alert_message}
                                          │
                                          ▼
                              alerts row + MCP notification
```

Use-case-specific rule data is not part of the core payload. Python overrides
read parsed fields from `argv[1].payload.fields` and keep their own constants or
configuration when custom behavior is needed.

## 3. Adding a new use case

Assume you are adding `pet_safety`.

### Step 1 — create the adapter directory

```bash
mkdir -p use-cases/pet_safety
```

### Step 2 — write the VLM prompt (`prompt.md`)

Copy an existing adapter's `prompt.md` as a starting point. The file is a
plain Markdown document split into sections by `##` headings:

```markdown
Free-form intro / rationale (optional).

## LOCAL_PROMPT

… per-clip prompt; produce output the built-in parser can decode …
SEVERITY: ...
EVENT: ...
DESC: ...

## GLOBAL_PROMPT

… aggregation prompt used by daily / weekly reports …
```

The `LOCAL_PROMPT` output must be line-oriented `KEY: value`; keys align with
`schema.video_summary_tasks.extensions` in `config.yaml` (`event`, `severity`,
`desc`, plus any custom columns your use case declares). Optional
`MACRO_CHUNK_PROMPT` and `T_MINUS_1_PROMPT` sections are also recognised for
chained-summary flows.

#### Prompt writing conventions (learned the hard way)

Empirical rules extracted from real VLM verification runs against the
`high_altitude_safety` adapter (originally on a small Qwen3.5 variant; the
failure modes below get worse the smaller the model). Following these avoids
known failure modes that are hard to diagnose after the fact.

**Convention 1 — Do NOT use pipe-separated enum syntax** (`A | B | C`).

Small VLMs interpret `SEVERITY: critical | warn | info` as a literal template
and echo the whole line back verbatim. Use two blocks instead: one or more
concrete output examples, plus a plain-language "allowed values" list.

```markdown
❌  SEVERITY: critical | warn | info
❌  EVENT: high_altitude_throw | no_incident | uncertain

✅  输出示例 1 (positive case):
        SEVERITY: critical
        EVENT: high_altitude_throw
        DESC: 观测到白色塑料袋从阳台向下坠落
        MOTION_DIRECTION: downward

✅  字段取值范围:
    - SEVERITY 只能是: critical, warn, info (三选一)
    - EVENT 只能是: high_altitude_throw, no_incident, uncertain (三选一)
```

**Convention 2 — Do NOT use markdown code fences** (` ``` `).

The video-summary service's `POST /v1/tasks` rejects any prompt containing
triple backticks with `banned_token`. Use 4-space indentation to mark examples
instead, or plain "以下是示例:" prose. Any snippet enclosed by ``` in your
prompt.md will fail registration outright.

```markdown
❌  ```
    SEVERITY: critical
    ```

✅  以下是示例输出:
        SEVERITY: critical
        EVENT: high_altitude_throw
```

**Convention 3 — Spell out the business boundary with concrete examples.**

VLMs are literal readers. Abstract phrases like "non-natural objects" leave
too much room for interpretation. For every ambiguous edge case in your
domain, name the concrete object.

For `high_altitude_safety` the initial prompt said "自然坠物 (树叶、鸟粪) → no_incident;
其他 → alert". The VLM classified a **plastic bag drifting from a balcony** as
`no_incident` because it "flew rather than fell". Rewriting the rule as:

```markdown
1. 人造物品 (塑料袋、瓶子、纸盒、烟头、饮料罐、衣物、玩具、生活垃圾等)
   从楼上/建筑物上方向下坠落 → SEVERITY=critical, EVENT=high_altitude_throw
   即使物体"飘"或速度慢也算 (塑料袋在气流中飘落也视为高空抛物)
2. 自然物 (仅限: 树叶、鸟粪、水滴、雪花) 缓慢飘落 → SEVERITY=info, EVENT=no_incident
```

flipped the verdict on the same video from `no_incident` to `critical` with
zero code changes. **Prompt precision matters far more than model size** —
enumerate concrete examples on both sides of every judgement boundary.

**Convention 4 — Repeat the "don't copy the example" instruction.**

Small models sometimes still echo the example when the prompt is long. Adding
`不要照抄示例, 必须根据视频内容选择一个值` before the examples and
`只输出四行, 每字段一行, 不要额外说明` at the end reinforces the intent.

### Step 3 — (optional) write `evaluate_rules.py`

**Prefer skipping this step for simple severity-based use cases.**
`defaultRuleEvaluator` fires when `fields.severity` is `warn` or `critical` (see
[packages/tools/src/rule-engine/index.ts](../packages/tools/src/rule-engine/index.ts)).

> If `fields.severity` is missing or unrecognised, `defaultRuleEvaluator`
> short-circuits to `shouldAlert=false` **before** any threshold/filter check.
> This is exactly why `fridge` is report-only: its VLM task emits no `SEVERITY`
> line, so the severity lookup fails and nothing fires.

Only reach for a Python override when the decision needs logic the built-in
severity rule can't express — time comparisons, multi-event joins, or external calls
(`elder_wakeup` is the canonical example). Follow the protocol in
[use-cases/README.md](../use-cases/README.md):

```python
import json, sys

def main():
    ctx = json.loads(sys.argv[1])
    fields = ctx["payload"].get("fields", {})

    if fields.get("event") == "pet_escape":
        print(json.dumps({
            "should_alert": True,
            "alert_message": f"[{ctx['useCase']}] pet_escape: {fields.get('desc', '')}",
        }))
        return

    print(json.dumps({"should_alert": False}))

if __name__ == "__main__":
    main()
```

### Step 4 — register in `config.yaml`

```yaml
use_case_dict:
  pet_safety:
    description: "Pet safety monitoring"
    video_summary_task: pet_safety_monitor
        evaluate_rules_path: ./use-cases/pet_safety/evaluate_rules.py
```

Omit `evaluate_rules_path` only when the built-in `warn`/`critical` severity
rule is sufficient.

Monitors that reference this use case pick up the wiring on next server
restart:

```yaml
# monitors.yaml (passed via --monitors <path>)
monitors:
  cam_pet_01:
    source_url: rtsp://…/live/pet
    use_case: pet_safety
```

### Step 5 — add unit tests (optional but recommended)

Extend [tests/dev-mcp-server/test_use_cases.py](../tests/dev-mcp-server/test_use_cases.py)
with cases for the new adapter. The pattern is `subprocess.run(python3, [script,
json.dumps(ctx)])`, then assert on the parsed stdout.

## 4. Bundled adapters

Wired into `config.yaml.example`:

| Use case | `evaluate_rules.py` | Alert semantics |
|----------|---------------------|-----------------|
| `child_safety` | none — default evaluator | Fires when `severity` is `warn` or `critical`; `info`-severity clips never fire. |
| `elder_wakeup` | present | Fires `late_wakeup` when `event=get_up` AND current local time > `expectedWakeupLocal + graceMinutes`. |
| `fridge` | none — default evaluator | Report-only: the `fridge_monitor` task emits no `SEVERITY` line, so `defaultRuleEvaluator` short-circuits to `shouldAlert=false`. It is not a hard stub: if a task's `severity` column is manually set to `warn`/`critical`, the evaluator will fire. |

Prompt-only extension templates (in `use-cases/` but **not** wired into
`config.yaml.example` — register them per
[use-case-adapter-gsg.md §9.7](./use-case-adapter-gsg.md)):

| Use case | Alert semantics |
|----------|-----------------|
| `high_altitude_safety` | Generate `evaluate_rules.py` when you need to require downward motion or a specific event. |
| `parking_safety` | Generate `evaluate_rules.py` when you need zone exclusions or custom alert-message suffixes. |

The default evaluator behavior is documented in
[packages/tools/src/rule-engine/index.ts](../packages/tools/src/rule-engine/index.ts).

## 5. Protocol reference

For the exact I/O contract expected of every `evaluate_rules.py`, see
[use-cases/README.md](../use-cases/README.md).

Design context: [smartbuilding-video-design-2026.2.md §5](./smartbuilding-video-design-2026.2.md).

Runtime source: [packages/tools/src/rule-engine/index.ts](../packages/tools/src/rule-engine/index.ts)
(`defaultRuleEvaluator` + `evaluateWithOverride`), invoked from
[packages/mcp-server/src/video-worker/task-poller.ts](../packages/mcp-server/src/video-worker/task-poller.ts).
