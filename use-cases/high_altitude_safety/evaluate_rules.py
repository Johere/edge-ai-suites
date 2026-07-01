"""high_altitude_safety evaluate_rules override.

Fires a `high_altitude_throw` alert when:
  1. VLM event is `high_altitude_throw`, AND
  2. `motion_direction` matches `rules.requireDirection` (default: "downward"),
     AND
  3. severity meets `rules.severityThreshold` (default "warn").

The `motion_direction` field is a Phase-added schema extension carried in
`payload.fields.motion_direction`. When the VLM output does not include the
field (older prompts), the check is skipped only if `rules.requireDirection`
is omitted; otherwise the alert is suppressed.

Input: RuleContext JSON on argv[1].
Output: JSON {should_alert, alert_message}.
"""

import json
import sys

SEVERITY_ORDER = {"info": 0, "warn": 1, "critical": 2}


def evaluate(fields: dict, rules: dict) -> dict:
    event = fields.get("event", "")
    if event != "high_altitude_throw":
        return {"fired": False}

    severity = fields.get("severity", "info")
    threshold = rules.get("severityThreshold", "warn")
    if SEVERITY_ORDER.get(severity, 0) < SEVERITY_ORDER.get(threshold, 1):
        return {"fired": False}

    require_dir = rules.get("requireDirection")
    if require_dir:
        observed_dir = (fields.get("motion_direction") or "").lower()
        if observed_dir != require_dir.lower():
            return {"fired": False}

    return {
        "fired": True,
        "alert_type": event,
        "severity": severity,
        "description": fields.get("desc") or fields.get("description", ""),
    }


def main() -> None:
    ctx = json.loads(sys.argv[1])
    fields = (ctx.get("payload") or {}).get("fields") or {}
    rules = (ctx.get("payload") or {}).get("rules") or {}
    result = evaluate(fields, rules)

    if result["fired"]:
        print(json.dumps({
            "should_alert": True,
            "alert_message": (
                f"[{ctx.get('useCase','')}] {result['alert_type']}: "
                f"{result['severity']} — {result['description']}"
            ),
        }))
    else:
        print(json.dumps({"should_alert": False}))


if __name__ == "__main__":
    main()
