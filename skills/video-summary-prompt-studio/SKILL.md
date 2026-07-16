---
name: video-summary-prompt-studio
description: "Author, register, list, edit, and delete prompt-driven video summary tasks on the multilevel-video-understanding service via `/v1/tasks` REST endpoints. Use when the user wants to add a new video analytics scenario (pet watch, elder fall, warehouse safety, ...), refine an existing custom task's prompt, inspect what tasks are registered, or remove one. The calling agent drafts the four-section prompt (LOCAL / MACRO / GLOBAL / T-1) following the guidance here, then POSTs via `curl`."
homepage: https://github.com/open-edge-platform/edge-ai-libraries
metadata:
  {
    "openclaw":
      {
        "emoji": "✍️",
        "requires": { "env": ["VIDEO_SUMMARY_BASE_URL"] }
      }
  }
---

# Video Summary Prompt Studio

Manages runtime prompts for the video summary service. A task is a bundle of
four prompts that drive a multi-level hierarchy: **LOCAL** (per micro-chunk)
→ **MACRO** (per macro-chunk) → **GLOBAL** (whole video) + a **T_MINUS_1**
context envelope for continuity.

Pure skill, no plugin — the agent uses `bash` + `curl` to hit `/v1/tasks`.

---

## Hard Invariants (check before every POST/PATCH)

| Rule | Value |
|---|---|
| Anchor names (**CASE-SENSITIVE, literal match**) | `GLOBAL_PROMPT`, `MACRO_CHUNK_PROMPT`, `LOCAL_PROMPT`, `T_MINUS_1_PROMPT` |
| Required placeholders — `LOCAL`, `MACRO` | `{st_tm}`, `{end_tm}` |
| Required placeholders — `T_MINUS_1` | `{dur}`, `{st_tm}`, `{end_tm}`, `{past_summary}` |
| Optional placeholder — `GLOBAL`, `MACRO`, `LOCAL` | `{question}` |
| `task_name` regex | `^[a-z][a-z0-9_]{1,63}$` (lowercase ASCII + underscore) |
| Name suffix convention | `_zh` or `_en` (`pet_guard_zh`, `warehouse_ppe_en`) |
| Banned tokens anywhere in any section | Triple-backtick code fences, and the literal string `<<<` |
| Built-in names (never shadow, never modify, never delete) | `summary`, `engine_valves_sop`, `refrigerator_monitor`, `daily_report`, `daily_report_en`, `refrigerator_monitor_en`, `child_safety_monitor` |
| Final gate before POST/PATCH | Run the 6-item checklist in `Lint checklist (self-check before POST)` |

**Missing placeholders** get smart-autofilled server-side (safe to skip).
**Missing or misspelled anchors** cause 422 with a `missing` list + a
reference template — fix and retry. The anchor names are case-sensitive:
`global_prompt` or `GlobalPrompt` will **not** match.

---

## Prompt Language (auto-select)

- Detect the language of the user's latest request and author **all four
  sections in that same language**. Do not mix languages inside one prompt.
- If the user explicitly asks for a language (e.g. "write it in English" /
  "请用中文写"), honor that.
- Placeholder names (`{st_tm}`, `{end_tm}`, `{dur}`, `{past_summary}`,
  `{question}`) stay as literal English tokens in both languages.
- Use the `_zh` / `_en` suffix on `task_name` accordingly.

---

## Prerequisites

```bash
: "${VIDEO_SUMMARY_BASE_URL:=http://localhost:8192}"
export VIDEO_SUMMARY_BASE_URL
curl -fsS "$VIDEO_SUMMARY_BASE_URL/v1/health" | jq .
```

---

## Read The Output Schema (before drafting)

Always read schema first, then draft prompts. Field names in
`schema.video_summary_tasks.extensions` are consumed downstream by
`parseSummaryFields`; the model must emit those exact field names as
`field_name: value` lines, or extraction/rules can silently miss.

1. Prefer workspace runtime config: `config.yaml`
2. Fallback: `config.yaml.example`

Suggested extraction flow:

```bash
if [[ -f config.yaml ]]; then
  CFG=config.yaml
else
  CFG=config.yaml.example
fi

yq '.schema.video_summary_tasks.extensions // []' "$CFG"
```

Build a working field list before writing prompt text:
- `required=true` fields: must appear as one line each in output contract.
- `required=false` fields: emit only when detectable in the clip.
- Keep original lowercase field names from schema (no renaming/translation in key).

---

## Writing the 4 Sections — What Each Is For

The four prompts do **different jobs**; scope and detail differ accordingly.

### LOCAL_PROMPT — seconds granularity; the VLM sees raw frames

**This is the only section where perceptual detail enters the system.** If a
hazard is not captured in LOCAL, it will not appear in MACRO or GLOBAL.

Must contain:
- Domain-focus heading
- Time line using `{st_tm}` and `{end_tm}`
- Priority-ordered **focus list** (3–5 items for monitoring use cases):
  1. Actor presence + appearance (clothing / age / location)
  2. Hazardous objects in hand or nearby
  3. Hazardous actions (climbing / falling / ingesting / ...)
  4. Guardian / operator presence & intervention
  5. Safe activity — 1–2 sentences only
- Output rules:
  - 2–5 sentences total
  - **Tag every hazard with a severity keyword: `critical` / `warn` / `info` / `normal`**
  - On-screen text: original + parenthetical translation
  - If no actor visible, describe the scene truthfully; no hallucination
  - No `[` `]` characters; no echo of the time lines
  - After narrative, append structured lines for schema extraction:
    - One line per required field: `<field_name>: <value>`
    - Optional fields: include only when detected
    - Field names must exactly match schema declarations
  - If hierarchy has levels > 1 and a field is intentionally cross-window,
    place the field line in GLOBAL output contract instead of LOCAL

Spend ~50% of drafting effort here.

### MACRO_CHUNK_PROMPT — minutes granularity; LLM sees micro summaries joined by `>|<`

A **compression pass**. Must contain:
- Merge-goal heading
- Time line with `{st_tm}` / `{end_tm}`
- **Promote critical/warn events to the front, verbatim**
- **Collapse consecutive safe periods into a single sentence**
- Keep actor identity consistent via appearance features
- Do not carry earlier objects/scenes forward unless they still appear
- No `[` `]`, no echo of time lines

### GLOBAL_PROMPT — whole-video summary; the final deliverable

A **narrative pass**, not a ledger. Must contain:
- Product heading ("safety-oriented summary", "daily report", ...)
- **A parseable opening-line convention** — critical triggers a fixed warning
  token so downstream code can detect it:
  - English: start with `ALERT:` when critical, else "Overall safe." /
    "N warn-level events occurred."
  - Chinese: start with `【注意】` when critical, else "整体安全" /
    "出现 N 次 warn 级别事件"
- **No timestamps in the prose**
- Statistics to report (domain-specific): actor count, hazard-type list,
  intervention count, ...
- Do not fabricate beyond macro summaries
- Optional `{question}` — weave in if present

Keep GLOBAL ≤ 5 short paragraphs.

### T_MINUS_1_PROMPT — previous-window context envelope

Small templated section. Must contain:
- Context heading + "this is prior context; do not copy into output"
- Domain-specific continuity note (was the hazard still present? did it
  end?)
- The bracketed envelope:
  ```
  [
  <time line with {st_tm} / {end_tm}>
  {past_summary}
  ]
  ```

---

## Skeleton (English; translate into the user's language as needed)

Draft each section, concatenate into one `content.text` string, then POST.
Only the placeholder names in braces are literal; everything else is prose.

```text
GLOBAL_PROMPT = '''
## Task:
<product name, e.g. "safety-oriented summary of <domain>">.
- Start with "Overall safe." / "N warn-level events occurred." / "ALERT: <critical hazard>".
- Use "ALERT:" as the fixed opening token whenever any critical event occurs.
- Expand event details grouped by category; NO timestamps in the prose.
- Report statistics: <actor-count, hazard-type list, intervention count, ...>.
- Do not fabricate content not present in the macro summaries.
User question: {question}
'''

MACRO_CHUNK_PROMPT = '''
## Task:
Merge sub-chunks into a concise narrative for this window. Critical / warn events first.
Start time: {st_tm}s
End time: {end_tm}s
## Guidelines:
- Collapse consecutive safe/inactive periods into one sentence.
- Keep actor identity consistent via appearance features (e.g. "the girl in a red dress").
- Do not carry earlier objects/scenes forward unless they still appear.
- No "[" or "]"; no echo of the time lines.
User question: {question}
'''

LOCAL_PROMPT = '''
## Task:
Describe activity in this short clip for <domain>.
Start time: {st_tm}s
End time: {end_tm}s
## Focus (priority order):
1. <actor presence and appearance>
2. <hazardous objects in hand or nearby>
3. <hazardous actions>
4. <guardian / operator presence & intervention>
5. <safe activity — 1–2 sentences only>
## Guidelines:
- 2–5 sentences total.
- Tag every hazard with a severity keyword: critical / warn / info / normal.
- On-screen text: original + parenthetical translation.
- If no actor visible, describe truthfully; no hallucination.
- No "[" or "]"; no echo of the time lines.
'''

T_MINUS_1_PROMPT = '''
## Context:
The previous {dur}s video summary is below in brackets.
**Important** Use it only as context; do not copy into the current output.
Watch for continuity of <actor position / action / contact with hazards>.
If the previous window's state has ended (e.g. the hazard has been resolved), say so explicitly.
[
Start time: {st_tm}s
End time: {end_tm}s
{past_summary}
]
'''
```

When the user writes in Chinese, keep the same structure but write the
prose in Chinese: `##任务:` / `##重点关注的内容:` / `##指南:` / `##上下文:`,
opening-line token `【注意】`, etc. Placeholder names stay in English.

---

## Lint checklist (self-check before POST)

Run this checklist on the final prompt text before POST/PATCH. These checks
mirror the removed MCP prompt-lint behavior and should be enforced inline.

1. `missing_local_prompt`
Symptom: no `## LOCAL_PROMPT` section header.
Fix: add a real `## LOCAL_PROMPT` section; do not hide LOCAL rules elsewhere.

2. `code_fence`
Symptom: contains triple-backtick code fence.
Fix: remove all fences; keep plain text/indented examples only.

3. `missing_event`
Symptom: expected event names do not appear in prompt text.
Fix: add each event name explicitly in LOCAL guidance/examples.

4. `missing_required_schema_field`
Symptom: required schema field name not present in prompt text.
Fix: add the missing field name verbatim (case-insensitive substring check is
the acceptance rule; exact key spelling is still strongly recommended).

5. `pipe_enum`
Symptom: `A | B | C` pipe-style enums appear.
Fix: rewrite as bullet lists or explicit sentence rules; no pipe enums.

6. `think_block`
Symptom: `<think>` markup remains from model output.
Fix: strip all `<think>...</think>` blocks before submission.

After POST/PATCH, optionally run server-side validation via
`smartbuilding_use_case_validate` for a second gate (task registration +
schema consistency).

---

## Curl Recipes

```bash
# List all tasks (built-in + dynamic)
curl -sS "$VIDEO_SUMMARY_BASE_URL/v1/tasks" | jq .

# Inspect one task (built-in or dynamic) — returns `{name, source, description,
# content}` where `content` is a single round-trip-safe string with all four
# anchor sections concatenated. Copy it, edit, and re-submit as `content.text`.
curl -sS "$VIDEO_SUMMARY_BASE_URL/v1/tasks/<name>" | jq .

# Delete a dynamic task (built-ins are 403).
curl -sS -X DELETE "$VIDEO_SUMMARY_BASE_URL/v1/tasks/<name>" -w "%{http_code}\n"
```

### Register full-mode (the primary workflow)

Write the body to a file so shell-quoting doesn't interfere:

```bash
cat > /tmp/body.json <<'JSON'
{
  "task_name": "pet_guard_en",
  "mode": "full",
  "description": "Pet-at-home monitoring; detect abnormal behaviors.",
  "content": {
    "text": "<<< the 4-anchor content string, with literal \\n between lines >>>"
  }
}
JSON

curl -sS -X POST "$VIDEO_SUMMARY_BASE_URL/v1/tasks" \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/body.json | jq .
```

### PATCH variants (rename / replace content / edit description)

```bash
# Rename only
curl -sS -X PATCH "$VIDEO_SUMMARY_BASE_URL/v1/tasks/<name>" \
  -H 'Content-Type: application/json' \
  -d '{"new_task_name": "<new>"}' | jq .

# Replace all four sections (same body shape as register, plus "mode":"full")
curl -sS -X PATCH "$VIDEO_SUMMARY_BASE_URL/v1/tasks/<name>" \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/body.json | jq .

# Description only
curl -sS -X PATCH "$VIDEO_SUMMARY_BASE_URL/v1/tasks/<name>" \
  -H 'Content-Type: application/json' \
  -d '{"description": "<new>"}' | jq .
```

### Autogen mode (fallback, lower quality)

Use only if drafting a full prompt is not feasible. Quality depends on the
model the service is configured with via `LLM_MODEL_NAME` / `LLM_BASE_URL`.

```bash
curl -sS -X POST "$VIDEO_SUMMARY_BASE_URL/v1/tasks" \
  -H 'Content-Type: application/json' \
  -d '{"task_name":"<name>","mode":"autogen","description":"<natural language use case>"}' | jq .
```

---

## Error Handling

| Status | Code | Fix |
|---|---|---|
| 201 | (success) | Show the four sections to the user |
| 422 | `missing_anchors` | Read `missing` + `reference_template`; add the anchors, retry |
| 422 | `missing_placeholders` | Section names a required `{foo}`; reply with `section` + `missing` |
| 422 | `autogen_empty_output` | Service LLM returned nothing; retry once, else switch to `mode=full` |
| 400 | `parse_error` | Content malformed (unbalanced `'''`, stray token); compare with `reference_template` |
| 400 | `duplicate_anchor` | Same anchor twice; keep one |
| 400 | `invalid_name` | `task_name` doesn't match `^[a-z][a-z0-9_]{1,63}$` |
| 400 | `banned_token` | Contains triple-backtick fence or `<<<`; remove |
| 400 | `invalid_url` | Non-HTTPS or private-network URL |
| 409 | `builtin_conflict` | Name matches a built-in; pick a different name |
| 409 | `already_registered` | Name used by another dynamic task; pick different or PATCH |
| 403 | `builtin_immutable` | Tried to PATCH / DELETE a built-in; register a new one instead |
| 404 | `not_found` | Typo or never registered; list first |

Retry budget: ≤ 2 attempts on 4xx. On the third failure, surface the server's
`detail` + `reference_template` to the user and ask for guidance.

---

## Intent Mapping

| User utterance (sample) | Action |
|---|---|
| "Add a pet-at-home monitoring task" / "给视频摘要服务加个宠物看家任务" | Draft 4 sections in the user's language → POST `/v1/tasks` mode=full |
| "List all video summary tasks" / "列一下任务" | GET `/v1/tasks` |
| "Show me the `child_safety_monitor` prompt" | GET `/v1/tasks/child_safety_monitor` |
| "Make `pet_guard_en`'s local prompt stricter" | GET the task → edit `content` → confirm with user → PATCH mode=full |
| "Delete `pet_guard_en`" | Confirm → DELETE `/v1/tasks/pet_guard_en` |
| "Use the LLM to draft a prompt for me" | Prefer `mode=full` (draft via this SKILL); use `mode=autogen` only for a throwaway first cut |

---

## Notes

- **Persistence**: dynamic tasks live under the service's
  `VIDEO_SUMMARY_CACHE` dir (default `~/.cache/.multilevel-video-understanding`
  on the host). They survive container restarts.
- **Round-trip editing**: the `content` field returned by GET is ready to
  POST/PATCH back — no reformatting needed.
- **URL content**: `content.url` (HTTPS only, ≤ 256 KB, public hosts) is an
  alternative to `content.text` for loading the four-section string from a
  remote file.
