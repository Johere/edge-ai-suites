
```bash
jq -Rs '{task_name: "fridge", mode: "full", content: {text: .}}' \
  fridge.txt \
| curl http://localhost:8192/v1/tasks -H "Content-Type: application/json" --data-binary @-
```

```bash
jq -Rs '{task_name: "child_safety", mode: "full", content: {text: .}}' \
  child_safety_monitor.txt \
| curl http://localhost:8192/v1/tasks -H "Content-Type: application/json" --data-binary @-
```

```bash
jq -Rs '{task_name: "elder_wakeup", mode: "full", content: {text: .}}' \
  elder_wakeup_monitor.txt \
| curl http://localhost:8192/v1/tasks -H "Content-Type: application/json" --data-binary @-
```