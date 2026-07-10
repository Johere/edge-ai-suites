import sys, json

def main():
    ctx = json.loads(sys.argv[1])
    fields = (ctx.get("payload", {}).get("fields") or {})
    event = fields.get("event", "")
    severity = fields.get("severity", "info")
    desc = fields.get("desc", "")
    zone = fields.get("pet_zone", "unknown")

    rules = (ctx.get("payload", {}).get("rules") or {})
    threshold = rules.get("severityThreshold", "warn")
    order = {"info": 0, "warn": 1, "critical": 2}

    if event == "no_incident":
        print(json.dumps({"should_alert": False})); return
    if order.get(severity, 0) < order.get(threshold, 1):
        print(json.dumps({"should_alert": False})); return

    msg = f"[pet_safety] {event}: {severity} - {desc} (zone={zone})"
    print(json.dumps({"should_alert": True, "alert_message": msg}))

if __name__ == "__main__":
    main()
