import json, sys

ALERT_EVENTS = {"restlessness", "night_out_of_room"}

def main():
    fields = json.loads(sys.argv[1])
    event = (fields.get("event") or "").strip()
    severity = (fields.get("severity") or "info").strip().lower()
    desc = (fields.get("desc") or "").strip()
    subject = (fields.get("subject") or "").strip()

    # Custom alert semantics for elder_care:
    # Only restlessness and night_out_of_room fire warn-level alerts.
    # Every other event records info-level timeline entries with no alert row.
    # critical is forbidden by contract (server caps at info|warn|critical,
    # but the prompt never emits critical and any such input is downgraded).
    if severity not in ("info", "warn", "critical"):
        severity = "info"
    if severity == "critical":
        severity = "info"

    if event in ALERT_EVENTS and severity == "warn":
        outcome = {
            "alertType": f"event:{event}",
            "severity": "warn",
            "description": f"{desc} (subject={subject or 'unknown'})",
        }
        print(json.dumps(outcome))
        return

    print("null")

if __name__ == "__main__":
    main()