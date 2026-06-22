#!/usr/bin/env python3
"""Test Case 6: Rule Engine — 默认规则 + Python override。

直接用 Python 测试规则引擎逻辑（无需 Node.js）。
"""

import json
import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conftest import get_temp_dir, cleanup_dir, TestResult

SEVERITY_LEVELS = {"low": 1, "medium": 2, "high": 3, "critical": 4}
THRESHOLD = 2  # medium and above


def default_rule_evaluate(context: dict) -> dict:
    """Python implementation of the default rule evaluator (mirrors TS logic)."""
    level = SEVERITY_LEVELS.get(context["severity"].lower(), 0)
    should_alert = level >= THRESHOLD
    return {
        "should_alert": should_alert,
        "alert_message": f"[{context['useCaseId']}] {context['event']}: {context['severity']}" if should_alert else None,
    }


def evaluate_with_override(context: dict, use_cases_dir: Path) -> dict:
    """Attempt Python override, fallback to default."""
    override_path = use_cases_dir / context["useCaseId"] / "evaluate_rules.py"

    if not override_path.exists():
        return default_rule_evaluate(context)

    try:
        result = subprocess.run(
            [sys.executable, str(override_path), json.dumps(context)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr)
        return json.loads(result.stdout.strip())
    except Exception as e:
        print(f"  [rule-engine] Override failed for {context['useCaseId']}: {e}")
        return default_rule_evaluate(context)


def main():
    print("\n=== Test: Rule Engine ===\n")
    t = TestResult("Rule Engine")

    # --- Default rule: severity >= medium → alert ---
    high_result = default_rule_evaluate({
        "monitorId": "cam-01", "useCaseId": "child_safety",
        "event": "child_jumping", "severity": "high", "payload": {},
    })
    t.check_equal(high_result["should_alert"], True, "Default rule: high severity → alert")
    t.check("child_jumping" in (high_result["alert_message"] or ""), "Alert message contains event name")

    critical_result = default_rule_evaluate({
        "monitorId": "cam-01", "useCaseId": "child_safety",
        "event": "fire_detected", "severity": "critical", "payload": {},
    })
    t.check_equal(critical_result["should_alert"], True, "Default rule: critical → alert")

    medium_result = default_rule_evaluate({
        "monitorId": "cam-01", "useCaseId": "child_safety",
        "event": "child_walking", "severity": "medium", "payload": {},
    })
    t.check_equal(medium_result["should_alert"], True, "Default rule: medium → alert (threshold=medium)")

    low_result = default_rule_evaluate({
        "monitorId": "cam-01", "useCaseId": "child_safety",
        "event": "normal_activity", "severity": "low", "payload": {},
    })
    t.check_equal(low_result["should_alert"], False, "Default rule: low severity → no alert")
    t.check_equal(low_result["alert_message"], None, "Low severity: no alert message")

    # --- Python override: success case ---
    tmp = get_temp_dir("rule-engine")
    use_cases_dir = tmp / "use-cases"
    child_safety_dir = use_cases_dir / "child_safety"
    child_safety_dir.mkdir(parents=True)

    override_script = '''
import json, sys
context = json.loads(sys.argv[1])
# Custom rule: only alert for "child_jumping" event, regardless of severity
should_alert = context["event"] == "child_jumping"
result = {"should_alert": should_alert, "alert_message": f"Custom: {context['event']}" if should_alert else None}
print(json.dumps(result))
'''
    (child_safety_dir / "evaluate_rules.py").write_text(override_script)

    override_result = evaluate_with_override({
        "monitorId": "cam-01", "useCaseId": "child_safety",
        "event": "child_jumping", "severity": "low", "payload": {},
    }, use_cases_dir)
    t.check_equal(override_result["should_alert"], True, "Python override: custom rule triggers for child_jumping")
    t.check("Custom" in (override_result["alert_message"] or ""), "Python override: custom message")

    override_no_alert = evaluate_with_override({
        "monitorId": "cam-01", "useCaseId": "child_safety",
        "event": "child_walking", "severity": "high", "payload": {},
    }, use_cases_dir)
    t.check_equal(override_no_alert["should_alert"], False, "Python override: custom rule skips non-jumping events")

    # --- Missing override file → falls back to default ---
    fallback_result = evaluate_with_override({
        "monitorId": "cam-01", "useCaseId": "nonexistent_case",
        "event": "something", "severity": "high", "payload": {},
    }, use_cases_dir)
    t.check_equal(fallback_result["should_alert"], True, "Missing override: falls back to default rule")

    # --- Broken script → falls back to default ---
    broken_dir = use_cases_dir / "broken_case"
    broken_dir.mkdir(parents=True)
    (broken_dir / "evaluate_rules.py").write_text('raise Exception("intentional error")')

    broken_result = evaluate_with_override({
        "monitorId": "cam-01", "useCaseId": "broken_case",
        "event": "test", "severity": "critical", "payload": {},
    }, use_cases_dir)
    t.check_equal(broken_result["should_alert"], True, "Broken script: falls back to default rule")

    cleanup_dir(tmp)
    passed = t.summary()
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
