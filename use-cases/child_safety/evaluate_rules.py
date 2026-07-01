"""child_safety evaluate_rules override.

Ported from agent-ai.smarthome/smartbuilding-video-mcp/use-cases/child_safety/
evaluate_rules.py. The core `evaluate()` function is copied verbatim; a thin
protocol adapter converts between the smart-community `RuleContext` (argv[1]
JSON) and the {parsed, rules} shape the ported logic already understands, and
between the ported {fired, alert_type, ...} output and the smart-community
`{should_alert, alert_message}` contract documented in `use-cases/README.md`.

Fires an alert when the VLM-reported severity is at or above the configured
threshold (default "warn"). `info`-severity events never fire.
"""

import json
import sys

SEVERITY_ORDER = {"info": 0, "warn": 1, "critical": 2}


def evaluate(parsed: dict, rules: dict) -> dict:
    severity = parsed.get("severity", "info")
    event = parsed.get("event", "")
    description = parsed.get("description", "")

    if severity == "info":
        return {"fired": False}

    threshold = rules.get("severityThreshold", "warn")
    sev_level = SEVERITY_ORDER.get(severity, 0)
    threshold_level = SEVERITY_ORDER.get(threshold, 1)

    if sev_level < threshold_level:
        return {"fired": False}

    return {
        "fired": True,
        "alert_type": event or "danger",
        "severity": severity,
        "description": description,
    }


def _context_to_parsed(ctx: dict) -> dict:
    """Translate smart-community RuleContext into the {parsed} shape."""
    fields = (ctx.get("payload") or {}).get("fields") or {}
    return {
        "severity": fields.get("severity", "info"),
        "event": fields.get("event", ""),
        "description": fields.get("desc") or fields.get("description", ""),
        "fields": fields,
    }


def _format_alert_message(use_case: str, result: dict) -> str:
    return (
        f"[{use_case}] {result['alert_type']}: {result['severity']} — "
        f"{result['description']}"
    )


def main() -> None:
    ctx = json.loads(sys.argv[1])
    parsed = _context_to_parsed(ctx)
    rules = (ctx.get("payload") or {}).get("rules") or {}
    result = evaluate(parsed, rules)

    if result["fired"]:
        print(json.dumps({
            "should_alert": True,
            "alert_message": _format_alert_message(ctx.get("useCase", ""), result),
        }))
    else:
        print(json.dumps({"should_alert": False}))


if __name__ == "__main__":
    main()
