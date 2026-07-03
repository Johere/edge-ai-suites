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
│   │   ├── evaluate_rules.py     # optional Python rule override
│   │   └── prompt.md             # VLM task prompts (LOCAL / GLOBAL sections)
│   ├── elder_wakeup/
│   │   ├── evaluate_rules.py
│   │   └── prompt.md
│   └── fridge/
│       ├── config.md             # per-use-case notes
│       ├── evaluate_rules.py     # no-alert stub
│       ├── prompt.md             # Chinese prompt
│       └── prompt_en.md          # English variant
└── config.yaml                   # wiring via use_case_dict.<name>
```

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
                                       payload: {fields, rules}}
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

`payload.rules` is copied verbatim from `use_case_dict.<useCase>.rules` in
`config.yaml`; Python overrides read it out of `argv[1]`.

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

Empirical rules extracted from real VLM (Qwen3.5-0.8B) verification runs
against the `high_altitude_safety` adapter. Following these avoids known
failure modes that are hard to diagnose after the fact.

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

Skip this step to rely on `defaultRuleEvaluator` (fires when
`fields.severity ∈ {critical, warn}`). Otherwise implement a Python script
that follows the protocol in [use-cases/README.md](../use-cases/README.md):

```python
import json, sys

def main():
    ctx = json.loads(sys.argv[1])
    fields = ctx["payload"].get("fields", {})
    rules  = ctx["payload"].get("rules", {})

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
    rules:
      # arbitrary shape — whatever your override consumes
      cooldownSeconds: 60
```

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

| Use case | `evaluate_rules.py` | Alert semantics |
|----------|---------------------|-----------------|
| `child_safety` | present | Fires when `severity ≥ severityThreshold` (default `warn`); `info`-severity clips never fire. |
| `elder_wakeup` | present | Fires `late_wakeup` when `event=get_up` AND current local time > `expectedWakeupLocal + graceMinutes`. |
| `fridge` | present | Uses `use-cases/fridge/evaluate_rules.py` no-alert stub; even if a task is manually edited to `severity=critical`, it still returns `should_alert=false`. |

`rules` block defaults are documented in each `evaluate_rules.py` header and
in [config.yaml.example](../config.yaml.example).

## 5. Protocol reference

For the exact I/O contract expected of every `evaluate_rules.py`, see
[use-cases/README.md](../use-cases/README.md).

Design context: [smartbuilding-video-design-2026.2.md §5](./smartbuilding-video-design-2026.2.md).

Runtime source: [packages/rule-engine/src/index.ts](../packages/rule-engine/src/index.ts)
(`evaluateWithOverride`), invoked from
[packages/mcp-server/src/video-worker/task-poller.ts](../packages/mcp-server/src/video-worker/task-poller.ts).
