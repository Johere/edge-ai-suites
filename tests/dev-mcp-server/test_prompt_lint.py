#!/usr/bin/env python3
"""Test Case: Prompt lint contract for P3 LLM autogen.

The TypeScript packages do not use a JS test runner today, so this test follows
the existing dev test style and invokes the compiled ESM export with Node.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conftest import REPO_ROOT, TestResult


def run_prompt_lint(payload: dict) -> dict:
    script = f"""
import {{ promptLint }} from './packages/tools/dist/index.js';
const result = promptLint({json.dumps(payload, ensure_ascii=False)});
console.log(JSON.stringify(result));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"node exited {result.returncode}: {result.stderr}")
    return json.loads(result.stdout)


def test_prompt_lint_pass(t: TestResult) -> None:
    prompt = """## LOCAL_PROMPT

请分析 10 秒摄像头片段。

输出字段:
- SEVERITY: critical, warn, info
- EVENT: pet_stuck, pet_escape, pet_normal
- DESC: 一句话描述
- PET_ZONE: sofa, door, window

示例:
    SEVERITY: critical
    EVENT: pet_stuck
    DESC: 宠物卡在沙发和墙之间
    PET_ZONE: sofa
"""
    result = run_prompt_lint({
        "prompt_text": prompt,
        "event_types": [
            {"name": "pet_stuck"},
            {"name": "pet_escape"},
            {"name": "pet_normal"},
        ],
        "schema_extensions": [
            {"name": "pet_zone", "required": True},
        ],
    })
    t.check_equal(result["ok"], True, "valid prompt passes lint")
    t.check_equal(result["errors"], [], "valid prompt has no errors")
    t.check_equal(result["warnings"], [], "valid prompt has no warnings")


def test_prompt_lint_errors(t: TestResult) -> None:
    prompt = """请分析视频。

```text
EVENT: pet_stuck
```

字段: SEVERITY: critical | warn | info
"""
    result = run_prompt_lint({
        "prompt_text": prompt,
        "event_types": [
            {"name": "pet_stuck"},
            {"name": "pet_escape"},
        ],
        "schema_extensions": [
            {"name": "pet_zone", "required": True},
        ],
    })
    codes = {issue["code"] for issue in result["issues"]}
    t.check_equal(result["ok"], False, "invalid prompt fails lint")
    t.check("missing_local_prompt" in codes, "reports missing LOCAL_PROMPT section")
    t.check("code_fence" in codes, "reports banned code fence")
    t.check("pipe_enum" in codes, "reports pipe enum warning")
    t.check("missing_event" in codes, "reports missing expected event")
    t.check("missing_required_schema_field" in codes, "reports missing required schema field")


def test_prompt_lint_strict(t: TestResult) -> None:
    prompt = """## LOCAL_PROMPT

输出字段:
- SEVERITY: critical | warn | info
- EVENT: safe
- DESC: 描述
"""
    relaxed = run_prompt_lint({"prompt_text": prompt})
    strict = run_prompt_lint({"prompt_text": prompt, "strict": True})

    t.check_equal(relaxed["ok"], True, "warning-only prompt passes relaxed mode")
    t.check_equal(strict["ok"], False, "warning-only prompt fails strict mode")


def main() -> bool:
    print("\n=== Test: Prompt Lint ===\n")
    t = TestResult("Prompt Lint")

    test_prompt_lint_pass(t)
    test_prompt_lint_errors(t)
    test_prompt_lint_strict(t)

    return t.summary()


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)