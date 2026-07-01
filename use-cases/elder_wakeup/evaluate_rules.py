"""elder_wakeup evaluate_rules override.

Ported from agent-ai.smarthome/smartbuilding-video-mcp/use-cases/elder_wakeup/
evaluate_rules.py. The core `evaluate()` function is copied verbatim; a thin
protocol adapter converts between the smart-community `RuleContext` (argv[1]
JSON) and the {parsed, rules} shape the ported logic already understands, and
between the ported {fired, alert_type, ...} output and the smart-community
`{should_alert, alert_message}` contract documented in `use-cases/README.md`.

Fires a `late_wakeup` alert when:
  1. VLM-reported event is `get_up`, and
  2. current local time is later than `expectedWakeupLocal + graceMinutes`.

`rules` block (from `config.yaml` → `use_case_dict.elder_wakeup.rules`) must
supply `expectedWakeupLocal` (HH:MM) and `graceMinutes` (int).
"""

import json
import sys
from datetime import datetime


def hhmm_to_minutes(s: str) -> int | None:
    """Parse 'HH:MM' to total minutes since midnight."""
    if not s:
        return None
    parts = s.strip().split(":")
    if len(parts) != 2:
        return None
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return h * 60 + m


def current_minutes() -> int:
    """Current local time as minutes since midnight."""
    now = datetime.now()
    return now.hour * 60 + now.minute


def evaluate(parsed: dict, rules: dict) -> dict:
    event = parsed.get("event", "")

    if event != "get_up":
        return {"fired": False}

    expected_str = rules.get("expectedWakeupLocal", "")
    expected = hhmm_to_minutes(expected_str)
    if expected is None:
        return {"fired": False}

    grace = int(rules.get("graceMinutes", 0))
    observed = current_minutes()

    if observed <= expected + grace:
        return {"fired": False}

    wakeup_time = parsed.get("fields", {}).get("wakeup_time")
    extra = {}
    if wakeup_time:
        try:
            extra["wakeupTime"] = float(wakeup_time)
        except (ValueError, TypeError):
            pass

    return {
        "fired": True,
        "alert_type": "late_wakeup",
        "severity": "warn",
        "description": parsed.get("description", ""),
        **extra,
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
    parts = [f"[{use_case}] {result['alert_type']}: {result['severity']} — {result['description']}"]
    if "wakeupTime" in result:
        parts.append(f"(wakeup_time={result['wakeupTime']})")
    return " ".join(parts)


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
