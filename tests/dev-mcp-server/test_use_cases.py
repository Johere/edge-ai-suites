#!/usr/bin/env python3
"""Test Case 7: Use Case Adapter — child_safety / elder_wakeup evaluate_rules.py.

Invokes each adapter via `subprocess.run(python3, [script, json_ctx])`, using
the exact protocol implemented by `packages/rule-engine/src/index.ts`
(`evaluateWithOverride`). Verifies the smart-community contract:

  argv[1]  = RuleContext JSON
  stdout   = {"should_alert": bool, "alert_message": str?}

Only the two ported use cases are covered here; `fridge` has no override and
is exercised by test_rule_engine.py's defaultRuleEvaluator suite.
"""

import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
from conftest import REPO_ROOT, TestResult

USE_CASES_DIR = REPO_ROOT / "use-cases"
CHILD_SAFETY = USE_CASES_DIR / "child_safety" / "evaluate_rules.py"
ELDER_WAKEUP = USE_CASES_DIR / "elder_wakeup" / "evaluate_rules.py"
FRIDGE = USE_CASES_DIR / "fridge" / "evaluate_rules.py"


def run_override(script: Path, ctx: dict) -> dict:
    """Invoke a Python override the same way task-poller does; parse stdout."""
    result = subprocess.run(
        [sys.executable, str(script), json.dumps(ctx)],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"override exited {result.returncode}: stderr={result.stderr!r}"
        )
    return json.loads(result.stdout.strip())


def make_ctx(
    use_case: str,
    fields: dict,
    rules: dict | None = None,
    monitor_id: str = "cam-01",
    task_id: int = 42,
) -> dict:
    """Assemble a minimal RuleContext identical to what task-poller sends."""
    return {
        "monitorId": monitor_id,
        "useCase": use_case,
        "taskId": task_id,
        "summaryText": "\n".join(f"{k.upper()}: {v}" for k, v in fields.items()),
        "payload": {
            "fields": fields,
            "rules": rules or {},
        },
    }


def test_child_safety(t: TestResult) -> None:
    """severity threshold semantics + alert_message format."""
    # critical → fires
    r = run_override(CHILD_SAFETY, make_ctx(
        "child_safety",
        {"severity": "critical", "event": "child_fall", "desc": "child fell from sofa"},
        {"severityThreshold": "warn"},
    ))
    t.check_equal(r["should_alert"], True, "child_safety critical → alert")
    t.check("child_fall" in r["alert_message"], "alert_message contains event")
    t.check("critical" in r["alert_message"], "alert_message contains severity")
    t.check("child fell from sofa" in r["alert_message"], "alert_message contains desc")
    t.check(r["alert_message"].startswith("[child_safety]"), "alert_message prefixed with use case")

    # warn at threshold warn → fires
    r = run_override(CHILD_SAFETY, make_ctx(
        "child_safety",
        {"severity": "warn", "event": "child_climb", "desc": "climbing window"},
        {"severityThreshold": "warn"},
    ))
    t.check_equal(r["should_alert"], True, "child_safety warn at threshold=warn → alert")

    # warn below threshold critical → skips
    r = run_override(CHILD_SAFETY, make_ctx(
        "child_safety",
        {"severity": "warn", "event": "child_climb", "desc": ""},
        {"severityThreshold": "critical"},
    ))
    t.check_equal(r["should_alert"], False, "child_safety warn below threshold=critical → skip")
    t.check_equal(r.get("alert_message"), None, "skip → no alert_message")

    # info → never fires
    r = run_override(CHILD_SAFETY, make_ctx(
        "child_safety",
        {"severity": "info", "event": "child_walk", "desc": ""},
        {"severityThreshold": "warn"},
    ))
    t.check_equal(r["should_alert"], False, "child_safety info → skip")

    # description fallback: reads `description` if `desc` absent
    r = run_override(CHILD_SAFETY, make_ctx(
        "child_safety",
        {"severity": "critical", "event": "child_fire",
         "description": "fire play detected"},
    ))
    t.check("fire play detected" in r["alert_message"],
            "child_safety reads `description` field when `desc` missing")


def test_elder_wakeup(t: TestResult) -> None:
    """late_wakeup fires only when event=get_up AND local time > expected+grace."""
    # Freeze `datetime.now()` inside the subprocess by patching the module.
    # Simpler approach: pass a "late" scenario by picking expected=00:00, grace=0,
    # which any real time-of-day exceeds. And a "not late" scenario with
    # expected=23:59, grace=59 which no real clock exceeds.

    # get_up + wide-open trigger window → fires
    r = run_override(ELDER_WAKEUP, make_ctx(
        "elder_wakeup",
        {"severity": "info", "event": "get_up", "desc": "got out of bed",
         "wakeup_time": "25.5"},
        {"expectedWakeupLocal": "00:00", "graceMinutes": 0},
    ))
    t.check_equal(r["should_alert"], True, "elder_wakeup get_up past expected+grace → alert")
    t.check("late_wakeup" in r["alert_message"], "alert_message contains alert_type=late_wakeup")
    t.check("wakeup_time=25.5" in r["alert_message"],
            "alert_message includes wakeupTime extra")

    # get_up but within tolerance → skip
    r = run_override(ELDER_WAKEUP, make_ctx(
        "elder_wakeup",
        {"severity": "info", "event": "get_up", "desc": ""},
        {"expectedWakeupLocal": "23:59", "graceMinutes": 59},
    ))
    t.check_equal(r["should_alert"], False, "elder_wakeup get_up within tolerance → skip")

    # event != get_up → skip regardless of clock
    r = run_override(ELDER_WAKEUP, make_ctx(
        "elder_wakeup",
        {"severity": "info", "event": "still_in_bed", "desc": ""},
        {"expectedWakeupLocal": "00:00", "graceMinutes": 0},
    ))
    t.check_equal(r["should_alert"], False, "elder_wakeup non-get_up event → skip")

    # missing expectedWakeupLocal → skip (no crash)
    r = run_override(ELDER_WAKEUP, make_ctx(
        "elder_wakeup",
        {"severity": "info", "event": "get_up", "desc": ""},
        {"graceMinutes": 30},
    ))
    t.check_equal(r["should_alert"], False, "elder_wakeup missing expectedWakeupLocal → skip")

    # malformed expectedWakeupLocal → skip (no crash)
    r = run_override(ELDER_WAKEUP, make_ctx(
        "elder_wakeup",
        {"severity": "info", "event": "get_up", "desc": ""},
        {"expectedWakeupLocal": "not-a-time", "graceMinutes": 30},
    ))
    t.check_equal(r["should_alert"], False, "elder_wakeup malformed HH:MM → skip")


def test_override_files_exist(t: TestResult) -> None:
    """Sanity: the three shipped adapters exist where config.yaml.example points."""
    t.check(CHILD_SAFETY.exists(),
            f"child_safety/evaluate_rules.py exists at {CHILD_SAFETY}")
    t.check(ELDER_WAKEUP.exists(),
            f"elder_wakeup/evaluate_rules.py exists at {ELDER_WAKEUP}")
    t.check(FRIDGE.exists(),
            f"fridge/evaluate_rules.py exists at {FRIDGE} (no-alert stub)")


def test_fridge_never_alerts(t: TestResult) -> None:
    """Fridge stub must return should_alert=false for any RuleContext."""
    r = run_override(FRIDGE, make_ctx(
        "fridge",
        {"severity": "critical", "event": "food_spoiled", "desc": "..."},
        {},
    ))
    t.check_equal(r["should_alert"], False, "fridge critical → still no alert")

    r = run_override(FRIDGE, make_ctx(
        "fridge",
        {"severity": "warn", "event": "shortage", "desc": "milk out"},
        {},
    ))
    t.check_equal(r["should_alert"], False, "fridge warn → still no alert")


def main() -> bool:
    print("\n=== Test: Use Case Adapters ===\n")
    t = TestResult("Use Case Adapters")

    test_override_files_exist(t)
    test_child_safety(t)
    test_elder_wakeup(t)
    test_fridge_never_alerts(t)

    return t.summary()


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
