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
│   │   └── prompt.py             # VLM task prompts (LOCAL / GLOBAL)
│   ├── elder_wakeup/
│   │   ├── evaluate_rules.py
│   │   └── prompt.py
│   └── fridge/
│       ├── config.md             # per-use-case notes
│       └── prompt.py
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

### Step 2 — write the VLM prompt (`prompt.py`)

Copy an existing adapter's `prompt.py` as a starting point. The file must
export module-level string constants:

```python
LOCAL_PROMPT = """
… per-clip prompt ; produce output the built-in parser can decode …
SEVERITY: ...
EVENT: ...
DESC: ...
"""

GLOBAL_PROMPT = """
… aggregation prompt used by daily / weekly reports …
"""
```

The `LOCAL_PROMPT` output must be line-oriented `KEY: value`; keys align with
`schema.video_summary_tasks.extensions` in `config.yaml` (`event`, `severity`,
`desc`, plus any custom columns your use case declares).

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
| `fridge` | absent | Uses `defaultRuleEvaluator` (`severity ∈ {critical, warn}`); the fridge VLM prompt normally emits `info`, so alerts are suppressed. |

`rules` block defaults are documented in each `evaluate_rules.py` header and
in [config.yaml.example](../config.yaml.example).

## 5. Protocol reference

For the exact I/O contract expected of every `evaluate_rules.py`, see
[use-cases/README.md](../use-cases/README.md).

Design context: [smartbuilding-video-design-2026.2.md §5](./smartbuilding-video-design-2026.2.md).

Runtime source: [packages/rule-engine/src/index.ts](../packages/rule-engine/src/index.ts)
(`evaluateWithOverride`), invoked from
[packages/mcp-server/src/video-worker/task-poller.ts](../packages/mcp-server/src/video-worker/task-poller.ts).
