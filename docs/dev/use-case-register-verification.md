# `smartbuilding_use_case_register` — 手动验证步骤

本文档面向零重启动态注册 use case 功能的**手动 gap 测试**。每一步都给出：

1. 前置条件
2. 执行的命令
3. **期望输出**（关键字段）
4. 失败时的定位方向

对应的用户使用指南：[use-case-adapter-gsg.md §10](../use-case-adapter-gsg.md)。

---

## 0. 环境准备

假设你已按 [use-case-adapter-gsg.md §3](../use-case-adapter-gsg.md) 起了以下三服务
（**都不允许重启，验证的就是零重启**）：

- MediaMTX + ffmpeg 推 4 条基线流（`./demo-videos/start-streams.sh`）
- Videostream Analytics（`http://localhost:8999`）
- Multilevel-video-understanding VLM（`http://localhost:8192`）
- MCP server（`http://localhost:3100/mcp`），**且启动前 `config.yaml.example` 里没有 `pet_safety` 条目**

**前置校验**：

```bash
# T1: 三服务活着
curl -sf http://localhost:8999/health >/dev/null && echo "VSA ok"
curl -sf http://localhost:8192/v1/tasks | jq '.tasks|length' | xargs -I{} echo "VLM ok, {} tasks"
curl -sf -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | grep "^data:" | head -1 | sed 's/^data: //' \
  | jq '.result.tools[].name' | grep -c smartbuilding | xargs -I{} echo "MCP ok, {} tools"

# T2: pet_safety 目前不存在
curl -sf http://localhost:8192/v1/tasks | jq '.tasks[].name' | grep -c pet_safety_monitor
# 期望：0

# T3: 数据库里 video_summary_tasks 表没有 pet_zone 列
sqlite3 "${SMARTBUILDING_DATA_DIR:-$HOME/.mcp-smartbuilding}/smartbuilding.db" \
  "PRAGMA table_info(video_summary_tasks);" | grep -c pet_zone
# 期望：0
```

**期望**：三条 `ok` 全出，且 pet_safety 相关都是 0。

---

## 1. 验证 `tools/list` 里有新 tool

```bash
curl -sf -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | grep "^data:" | head -1 | sed 's/^data: //' \
  | jq '.result.tools[] | select(.name=="smartbuilding_use_case_register") | {name, description}'
```

**期望输出**：

```json
{
  "name": "smartbuilding_use_case_register",
  "description": "Dynamically add or remove a use_case at runtime without restarting..."
}
```

**失败**：如果空——MCP server 用的还是老的编译产物。跑：

```bash
cd /home/user/jie/smarthome/smart-community
npm run --workspace=@smartbuilding-video/tools build
npm run --workspace=@smartbuilding-video/mcp-server build
# 然后重启 MCP（Ctrl-C 那个终端，再启动一次）
```

---

## 2. 参数校验（负例先跑）

### 2.1 use_case 名字不合规

```bash
curl -sf -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
    "name":"smartbuilding_use_case_register",
    "arguments":{"action":"register","use_case":"Pet-Safety"}}}' \
  | grep "^data:" | head -1 | sed 's/^data: //' \
  | jq '.result.content[0].text | fromjson | {ok, errors}'
```

**期望**：

```json
{
  "ok": false,
  "errors": ["use_case \"Pet-Safety\" must match /^[a-z][a-z0-9_]{1,63}$/"]
}
```

### 2.2 video_summary_task 撞 builtin

```bash
curl -sf -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
    "name":"smartbuilding_use_case_register",
    "arguments":{
      "action":"register",
      "use_case":"pet_safety",
      "video_summary_task":"refrigerator_monitor"
    }}}' \
  | grep "^data:" | head -1 | sed 's/^data: //' \
  | jq '.result.content[0].text | fromjson | {ok, errors}'
```

**期望**：

```json
{
  "ok": false,
  "errors": ["video_summary_task \"refrigerator_monitor\" is a VLM builtin (immutable); pick a different name"]
}
```

### 2.3 use_case 已存在但没传 overwrite

先注册一次（步骤 3），然后再重复调用（不加 `overwrite: true`）。

**期望**：`ok: false, errors: ["use_case \"pet_safety\" already exists ... pass overwrite=true"]`。

---

## 3. 完整注册（正例）

先在磁盘上准备 evaluate_rules.py（**这是磁盘 side effect，MCP 不会替你建**）：

```bash
cd /home/user/jie/smarthome/smart-community
mkdir -p use-cases/pet_safety

cat > use-cases/pet_safety/prompt.md <<'EOF'
## LOCAL_PROMPT

You are a home pet-safety camera. Watch the 10-second clip and output EXACTLY these fields:

SEVERITY: critical | warn | info
EVENT: <one of: pet_stuck, pet_escape, pet_normal, no_incident>
DESC: <one sentence>
PET_ZONE: <one of: cage, sofa, floor, door, unknown>

Rules:
- pet_stuck = animal trapped / immobile in unnatural position → critical
- pet_escape = animal reaching for door/window → warn
- pet_normal = resting / playing / eating → info
- no visible pet = no_incident, info
EOF

cat > use-cases/pet_safety/evaluate_rules.py <<'EOF'
import sys, json

def main():
    ctx = json.load(sys.stdin)
    fields = (ctx.get("fields") or {})
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

    msg = f"[pet_safety] {event}: {severity} — {desc} (zone={zone})"
    print(json.dumps({"should_alert": True, "alert_message": msg}))

if __name__ == "__main__":
    main()
EOF
```

然后调 register：

```bash
PROMPT_TEXT=$(cat use-cases/pet_safety/prompt.md)

jq -n \
  --arg pt "$PROMPT_TEXT" \
  --arg erp "$(pwd)/use-cases/pet_safety/evaluate_rules.py" \
  '{
    jsonrpc: "2.0", id: 1, method: "tools/call",
    params: {
      name: "smartbuilding_use_case_register",
      arguments: {
        action: "register",
        use_case: "pet_safety",
        video_summary_task: "pet_safety_monitor",
        description: "Pet safety monitoring (dynamic)",
        evaluate_rules_path: $erp,
        rules: { severityThreshold: "warn", cooldownSeconds: 300 },
        reports: { data_source: "alerts", default_type: "daily", filter: {} },
        prompt_text: $pt,
        schema_extensions: [
          { name: "pet_zone", type: "text", required: false }
        ]
      }
    }
  }' | curl -s -X POST http://localhost:3100/mcp \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        --data-binary @- \
     | grep "^data:" | head -1 | sed 's/^data: //' | jq '.result.content[0].text | fromjson'
```

**期望完整响应**：

```json
{
  "action": "register",
  "use_case": "pet_safety",
  "ok": true,
  "steps": {
    "schema": {
      "added": ["video_summary_tasks.pet_zone"],
      "warnings": []
    },
    "vlm_task": "registered",
    "use_case_dict": "added",
    "validate": {
      "valid": true,
      "use_case": "pet_safety",
      "video_summary_task": "pet_safety_monitor",
      "checks": {
        "use_case_known": true,
        "task_registered": true,
        "schema_consistent": true
      },
      "required_fields": ["event", "severity", "desc"],
      "optional_fields": ["confidence", "motion_direction", "parking_zone", "pet_zone"],
      "missing_required_in_prompt": [],
      "missing_optional_in_prompt": [<不包含 pet_zone>]
    }
  },
  "warnings": [],
  "errors": []
}
```

关键点：
- `steps.schema.added` 有且只有 `video_summary_tasks.pet_zone`
- `steps.vlm_task = "registered"`（不是 `"updated"`——第一次注册）
- `steps.validate.valid = true`
- `missing_required_in_prompt = []`（prompt 里有 EVENT / SEVERITY / DESC）
- `pet_zone` 应该出现在 `optional_fields` 但**不**出现在 `missing_optional_in_prompt`（因为 prompt 里显式写了 `PET_ZONE:`）

---

## 4. 每一步的独立验证

### 4.1 VLM 端

```bash
curl -sf http://localhost:8192/v1/tasks/pet_safety_monitor | jq '{name, source, description}'
```

**期望**：

```json
{
  "name": "pet_safety_monitor",
  "source": "dynamic",
  "description": "Pet safety monitoring (dynamic)"
}
```

再看下 content 是不是 4 常量结构：

```bash
curl -sf http://localhost:8192/v1/tasks/pet_safety_monitor | jq -r '.content' | head -20
```

**期望**：以 `GLOBAL_PROMPT = '''` 开头，能看到 `LOCAL_PROMPT = '''` 段。

### 4.2 DB schema

```bash
sqlite3 "${SMARTBUILDING_DATA_DIR:-$HOME/.mcp-smartbuilding}/smartbuilding.db" \
  "PRAGMA table_info(video_summary_tasks);" | grep pet_zone
```

**期望**：一行 `<idx>|pet_zone|TEXT|0||0`。

### 4.3 In-memory use_case_dict

调 `smartbuilding_use_case_validate` 单独验证一次：

```bash
curl -sf -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
    "name":"smartbuilding_use_case_validate",
    "arguments":{"use_case":"pet_safety"}}}' \
  | grep "^data:" | head -1 | sed 's/^data: //' | jq '.result.content[0].text | fromjson'
```

**期望**：`valid: true`；三个 `checks` 全 true。这一步等于用另一个 tool 反向证明内存里已经有了 pet_safety。

---

## 5. 端到端跑通（如果你手上有 pet 视频）

放一段 10 秒 pet 视频到 `~/.mcp-smartbuilding/test-videos/pet_safety/pet_stuck.mp4`（
容器内路径 `/data/test-videos/pet_safety/pet_stuck.mp4`），然后直接调 VLM：

```bash
curl -sf -X POST http://localhost:8192/v1/summary \
  -H "Content-Type: application/json" \
  -d '{"video":"/data/test-videos/pet_safety/pet_stuck.mp4","task":"pet_safety_monitor"}' \
  | jq .
```

**期望**：`status: "completed"`，`summary` 里包含 `SEVERITY:` / `EVENT:` / `DESC:` / `PET_ZONE:` 关键字。

如果视频里模拟了 pet_stuck 场景，rule 层应该判 alert：

```bash
# 手工塞一个 completed task 到 DB，事件带 pet_stuck + critical
python3 - <<'PY'
import sqlite3, os
con = sqlite3.connect(f"{os.environ.get('SMARTBUILDING_DATA_DIR', os.path.expanduser('~/.mcp-smartbuilding'))}/smartbuilding.db")
con.execute("""INSERT INTO video_summary_tasks
    (monitor_id, event_id, status, summary_text, event, severity, desc, pet_zone, created_at)
    VALUES ('cam_pet', NULL, 'completed',
            'SEVERITY: critical\nEVENT: pet_stuck\nDESC: dog trapped between sofa and wall\nPET_ZONE: sofa',
            'pet_stuck', 'critical', 'dog trapped between sofa and wall', 'sofa', datetime('now'))""")
con.commit()
tid = con.execute("SELECT id FROM video_summary_tasks WHERE monitor_id='cam_pet' ORDER BY id DESC LIMIT 1").fetchone()[0]
print("task_id:", tid)
PY

# 用 rule_eval dry-run 验证
curl -sf -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
    "name":"smartbuilding_rule_eval",
    "arguments":{"monitor_id":"cam_pet","task_id":<上面输出的 id>}}}' \
  | grep "^data:" | head -1 | sed 's/^data: //' | jq '.result.content[0].text | fromjson | .rule_result'
```

**期望**：

```json
{
  "shouldAlert": true,
  "alertMessage": "[pet_safety] pet_stuck: critical — dog trapped between sofa and wall (zone=sofa)"
}
```

关键**证明**：`evaluate_rules.py` 是磁盘上刚才写的那个文件；`rule_result.alertMessage`
的格式和它 return 的完全一致——说明 in-memory `useCaseDict.pet_safety.evaluate_rules_path`
生效了，且 task-poller / rule_eval 路径**完全没重启就读到了新配置**。

---

## 6. 未提供 prompt_text 的场景（VLM 侧手动注册）

跳过 `prompt_text` 时，tool 只做 schema + use_case_dict 注入；VLM task 需要你自己
POST。这在"prompt 已经通过别的脚本注册好"的场景常见。

```bash
# 先手动 POST 到 VLM（略）...
# 然后调 register 但不传 prompt_text
curl -sf -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
    "name":"smartbuilding_use_case_register",
    "arguments":{
      "action":"register",
      "use_case":"pet_safety",
      "video_summary_task":"pet_safety_monitor",
      "rules":{"severityThreshold":"warn"},
      "overwrite":true
    }}}' | grep "^data:" | head -1 | sed 's/^data: //' | jq '.result.content[0].text | fromjson | {ok, steps, warnings}'
```

**期望**：

```json
{
  "ok": true,
  "steps": {
    "vlm_task": "skipped",
    "use_case_dict": "updated",
    "validate": { "valid": true, ... }
  },
  "warnings": [
    "prompt_text omitted — VLM task must be registered out-of-band before this use_case can produce alerts"
  ]
}
```

---

## 7. Unregister

```bash
curl -sf -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
    "name":"smartbuilding_use_case_register",
    "arguments":{"action":"unregister","use_case":"pet_safety"}}}' \
  | grep "^data:" | head -1 | sed 's/^data: //' | jq '.result.content[0].text | fromjson'
```

**期望**：

```json
{
  "action": "unregister",
  "use_case": "pet_safety",
  "ok": true,
  "steps": {
    "vlm_task": "deleted",
    "use_case_dict": "removed"
  },
  "warnings": [],
  "errors": []
}
```

反向验证：

```bash
curl -sf http://localhost:8192/v1/tasks/pet_safety_monitor -o /dev/null -w "%{http_code}\n"
# 期望：404

curl -sf -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
    "name":"smartbuilding_use_case_validate",
    "arguments":{"use_case":"pet_safety"}}}' \
  | grep "^data:" | head -1 | sed 's/^data: //' | jq '.result.content[0].text | fromjson | {valid, error}'
# 期望：{ "valid": false, "error": "unknown use_case \"pet_safety\". Known: [...]" }
```

**注意**：`pet_zone` schema 列**不会**被 drop（sqlite 限制 + 数据安全）。想清理：手动 `sqlite3 ... ALTER TABLE ... DROP COLUMN pet_zone`（sqlite ≥ 3.35）。

---

## 8. 已知 gap 一览（跑完上面能观察到的）

| Gap | 表现 | 缓解方式 |
|---|---|---|
| **重启丢失** | 重启 MCP 后 `smartbuilding_use_case_validate use_case=pet_safety` 返回 `unknown use_case`；如果 monitor `cam_pet` 还在 DB，MCP 启动会因 `monitors reference unknown use_case keys` 直接 exit | 手改 `config.yaml.example` 追加 `use_case_dict.pet_safety`；或在重启前先 unregister monitor |
| **`config.yaml` 不写回** | 磁盘上的 config.yaml 永远只有启动时的内容 | 目前只能手抄一份到 `config.yaml.example`；P3 计划加 `persist: true` |
| **`evaluate_rules.py` 需手写** | Tool 不生成 Python 脚本，只登记路径 | 用文档里的模板照抄；后续可加"生成骨架"参数 |
| **schema 列不能撤销** | `unregister` 保留 `pet_zone` 列 | 手动 `ALTER TABLE ... DROP COLUMN`（sqlite 3.35+） |
| **prompt_text 换行处理** | Markdown 里含 `'''` 会污染 Python 源码字符串 | 目前用 `'''` 作 heredoc；如 prompt 里有三单引号需要人工 escape。P3 改用 `"""` + smart quoting |
| **并发写入** | 两个客户端同时 register 同一个 use_case，最后写入者赢 | MCP 单进程；实际不会并发；如担心可加分布式锁（超出当前范围）|

---

## 9. 附录：完整清理

```bash
# 反向清掉所有 side effects（假设 unregister 已跑）
rm -rf use-cases/pet_safety
sqlite3 "${SMARTBUILDING_DATA_DIR:-$HOME/.mcp-smartbuilding}/smartbuilding.db" \
  "DELETE FROM video_summary_tasks WHERE monitor_id='cam_pet';"
# schema 列 pet_zone 可选保留

# 再跑一次 §0 前置校验，应回到"pet_safety 相关全 0"的初始态
```
