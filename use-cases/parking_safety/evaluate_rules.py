"""parking_safety evaluate_rules override.

Fires an alert when the VLM classifies a parking violation:
  - `illegal_parking` in fire lane / entrance / handicapped spot → critical
  - other severities gated by `rules.severityThreshold` (default "warn")
  - unknown / no_incident → suppressed

The `parking_zone` field (extension column) is passed through in the alert
message for downstream reporting. `rules.excludeZones` optionally lets
operators suppress specific zones (e.g. deprioritise visitor-spot violations
during weekends).

Input : RuleContext JSON on argv[1]
Output: JSON {should_alert, alert_message}
"""

import json
import sys

SEVERITY_ORDER = {"info": 0, "warn": 1, "critical": 2}


def evaluate(fields: dict, rules: dict) -> dict:
    event = fields.get("event", "")
    if event in ("no_incident", "uncertain", ""):
        return {"fired": False}

    severity = fields.get("severity", "info")
    threshold = rules.get("severityThreshold", "warn")
    if SEVERITY_ORDER.get(severity, 0) < SEVERITY_ORDER.get(threshold, 1):
        return {"fired": False}

    zone = fields.get("parking_zone", "")
    exclude = rules.get("excludeZones", []) or []
    if zone and zone in exclude:
        return {"fired": False}

    return {
        "fired": True,
        "alert_type": event,
        "severity": severity,
        "description": fields.get("desc") or fields.get("description", ""),
        "zone": zone,
    }


def _format_alert_message(use_case: str, result: dict) -> str:
    base = (
        f"[{use_case}] {result['alert_type']}: {result['severity']} "
        f"— {result['description']}"
    )
    if result.get("zone"):
        return f"{base} (zone={result['zone']})"
    return base


def main() -> None:
    ctx = json.loads(sys.argv[1])
    fields = (ctx.get("payload") or {}).get("fields") or {}
    rules = (ctx.get("payload") or {}).get("rules") or {}
    result = evaluate(fields, rules)

    if result["fired"]:
        print(json.dumps({
            "should_alert": True,
            "alert_message": _format_alert_message(ctx.get("useCase", ""), result),
        }))
    else:
        print(json.dumps({"should_alert": False}))


if __name__ == "__main__":
    main()
