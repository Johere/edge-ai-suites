# `smartbuilding_use_case_register` — 手动验证步骤

本文档面向零重启动态注册 use case 功能的**手动 gap 测试**。每一步都给出：

1. 前置条件
2. 执行的命令
3. **期望输出**（关键字段）
4. 失败时的定位方向

对应的用户使用指南：[use-case-adapter-gsg.md §10](../use-case-adapter-gsg.md)。

**Tool 覆盖**（`smartbuilding_use_case_register` 3 个 action，本文档全部验证）：

| Action | 语义 | 本文档节 |
|---|---|---|
| ~~`generate_prompt`~~ | ⛔ 已移除（2026-07，迁至 `video-summary-prompt-studio` skill）；§3 仅存历史记录 | §3 |
| `register` | schema ALTER + VLM POST /v1/tasks + inject useCaseDict（可选 `persist=true` 写回 config.yaml）| §4-§6 |
| `unregister` | 反向清除（可选 `persist=true` 从 config.yaml 删条目）| §10 |

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

先注册一次（步骤 4），然后再重复调用（不加 `overwrite: true`）。

**期望**：`ok: false, errors: ["use_case \"pet_safety\" already exists ... pass overwrite=true"]`。

---

## 3. `action=generate_prompt`：让 vLLM 生成 prompt.md 骨架（2026-07-03 晚新增；⛔ 2026-07 已移除）

> **⛔ 本节已过时（历史记录，保留不删）**。`action=generate_prompt` 已从 MCP 移除，
> prompt 起草改由 `video-summary-prompt-studio` skill（agent + router）承担，落地经
> `action=register` 的 `prompt_text`。下文命令仅作历史留档，勿再照此调用。理由见
> [gap-analysis §6.2](./use-case-adapter-gap-analysis.md)。

**目的（历史）**：验证"零 prompt 手工"入口——从 3 个语义输入让 vLLM 生成 `## LOCAL_PROMPT` 骨架，不 mutate 任何状态。

```bash
curl -sS -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
    "name":"smartbuilding_use_case_register",
    "arguments":{
      "action":"generate_prompt",
      "use_case":"pet_safety",
      "description":"监控家里的宠物是否处于危险状态",
      "event_types":[
        {"name":"pet_stuck","severity":"critical","desc":"宠物被卡住/困在狭窄处"},
        {"name":"pet_escape","severity":"warn","desc":"宠物尝试跳门/翻窗逃跑"},
        {"name":"pet_normal","severity":"info","desc":"宠物正常休息/玩耍/进食"},
        {"name":"no_incident","severity":"info","desc":"画面无宠物"}
      ],
      "schema_extensions":[{"name":"pet_zone","type":"text","required":false}],
      "language":"zh"
    }}}' \
  | grep "^data:" | head -1 | sed 's/^data: //' \
  | jq '.result.content[0].text | fromjson | {ok, warnings, has_prompt: (.generated_prompt|length>0), preview: (.generated_prompt|.[0:500]), next_steps}'
```

**期望**：

```json
{
  "ok": true,
  "warnings": [],
  "has_prompt": true,
  "preview": "## LOCAL_PROMPT\n\n你是一个家庭宠物看护摄像头...\n\n输出示例 1 (positive case):\n    SEVERITY: critical\n    EVENT: pet_stuck\n    DESC: 宠物被卡在两个家具之间\n    PET_ZONE: sofa\n\n字段取值范围:\n- SEVERITY 只能是: critical, warn, info\n...",
  "next_steps": [
    "1. Save 'generated_prompt' to use-cases/pet_safety/prompt.md",
    "2. Manually refine business boundaries — spell out concrete edge cases (see Convention 3 in use-case-adapter.md)",
    "3. Call smartbuilding_use_case_register action=register with prompt_text=$(cat use-cases/pet_safety/prompt.md) persist=true"
  ]
}
```

**如果 `warnings` 里出现下面 3 类之一**（vLLM 违反 Convention）：

- `contains triple-backtick code fence` → **必须手动删掉** ```，否则 POST /v1/tasks 会被 `banned_token` 拒收
- `contains A | B | C pipe-separated enum` → **建议手动改** 成"输出示例"块 + 独立"字段取值范围"列表（Convention 1）
- `event names missing: <list>` → **必须手动补齐**遗漏的 event，否则 downstream rule engine 会短路

**存盘 + 手工 refine**：

```bash
mkdir -p use-cases/pet_safety
curl -sS ... generate_prompt ... \
  | grep "^data:" | head -1 | sed 's/^data: //' \
  | jq -r '.result.content[0].text | fromjson | .generated_prompt' \
  > use-cases/pet_safety/prompt.md

vim use-cases/pet_safety/prompt.md   # 加业务细节（Convention 3 强调具体案例）
```

**验证 side effect（不应有任何 mutation）**：

```bash
# VLM 端不应出现 pet_safety_monitor
curl -sf http://localhost:8192/v1/tasks | jq '.tasks[].name' | grep -c pet_safety_monitor
# 期望：0

# 内存 useCaseDict 里也不应有 pet_safety
curl -sf -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
    "name":"smartbuilding_use_case_validate",
    "arguments":{"use_case":"pet_safety"}}}' \
  | grep "^data:" | head -1 | sed 's/^data: //' | jq '.result.content[0].text | fromjson | .valid'
# 期望：false（尚未 register）
```

`generate_prompt` 是**纯 vLLM 咨询**，不落 DB、不改 useCaseDict、不 POST /v1/tasks。是 `register` 的 pre-step。

---

## 4. 完整注册（正例）

先在磁盘上准备 evaluate_rules.py（**这是磁盘 side effect，MCP 不会替你建**）。

**注意**：以下 prompt.md 是**简化占位**（Convention 1 反例，仅示例用）。生产环境用 `video-summary-prompt-studio` skill（agent + router）起草 + `vim refine` 得到合规版；或参考现有 `use-cases/child_safety/prompt.md` 手写。（§3 的 `generate_prompt` 已移除。）

```bash
cd /home/user/jie/smarthome/smart-community
mkdir -p use-cases/pet_safety

cat > use-cases/pet_safety/prompt.md <<'EOF'
## LOCAL_PROMPT

You are a home pet-safety camera. Watch the 10-second clip and output EXACTLY these fields:

SEVERITY: (one of critical, warn, info)
EVENT: (one of pet_stuck, pet_escape, pet_normal, no_incident)
DESC: (one sentence)
PET_ZONE: (one of cage, sofa, floor, door, unknown)

Rules:
- pet_stuck = animal trapped / immobile in unnatural position → critical
- pet_escape = animal reaching for door/window → warn
- pet_normal = resting / playing / eating → info
- no visible pet = no_incident, info
EOF

# ⚠️ 关键：override 必须从 argv[1] 读 ctx，不能用 sys.stdin（会挂死 rule_eval，已知 Issue #3）
# ⚠️ 关键：fields / rules 都在 ctx.payload.<...> 下，不在 ctx 顶层
cat > use-cases/pet_safety/evaluate_rules.py <<'EOF'
import sys, json

def main():
    ctx = json.loads(sys.argv[1])
    payload = ctx.get("payload") or {}
    fields = payload.get("fields") or {}
    event = fields.get("event", "")
    severity = fields.get("severity", "info")
    desc = fields.get("desc", "")
    zone = fields.get("pet_zone", "unknown")

    rules = payload.get("rules") or {}
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

**替代方案：完全不写 evaluate_rules.py**（用 `defaultRuleEvaluator + rules dict`）。参考 `child_safety` / `parking_safety` / `high_altitude_safety` 已经迁到这个模式：

```yaml
# config.yaml.example use_case_dict.pet_safety.rules:
severityThreshold: warn
excludeEvents: [no_incident, pet_normal]
alertMessageExtraField: pet_zone   # 拼 "(zone=X)" 尾缀
cooldownSeconds: 300
```

`defaultRuleEvaluator` 完全等价上面 Python 逻辑，且不用写文件。

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
- `steps.use_case_dict = "added"`
- `steps.config_yaml` **不存在**（本轮没传 `persist: true`，见 §5 单独测）
- `steps.validate.valid = true`
- `missing_required_in_prompt = []`（prompt 里有 EVENT / SEVERITY / DESC）
- `pet_zone` 应该出现在 `optional_fields` 但**不**出现在 `missing_optional_in_prompt`（因为 prompt 里显式写了 `PET_ZONE:`）

**注意**：`severity` 在 `config.yaml.example` 的 schema 里已从 `required: true` 改为 `required: false`（2026-07-03 修 Issue #5），所以最新的 `required_fields` 应该是 `["event", "desc"]`（**不含** `severity`），`optional_fields` 里应含 `severity`。

---

## 5. `persist: true`：register 时同步写回 config.yaml（2026-07-03 晚新增）

**目的**：验证"零 YAML 手工"——`persist: true` 让 tool 用 yaml `Document` API 把 use_case 条目**写回**磁盘 `config.yaml.example`，注释和字段顺序保留。MCP 重启后仍在。

**前置**：MCP 必须以 `--config config.yaml.example` 启动（否则 `ServerConfig.configPath` 是 undefined，persist 会 skip）。

**为了独立测 persist（不干扰 §4 已 register 的 pet_safety）**，用不同的 `use_case` 名 `pet_safety_persisted`：

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
        use_case: "pet_safety_persisted",
        video_summary_task: "pet_safety_persisted_monitor",
        description: "Pet safety (with persist=true test)",
        evaluate_rules_path: $erp,
        rules: { severityThreshold: "warn", cooldownSeconds: 300 },
        prompt_text: $pt,
        schema_extensions: [{ name: "pet_zone", type: "text", required: false }],
        persist: true,
        overwrite: true
      }
    }
  }' | curl -sS -X POST http://localhost:3100/mcp \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        --data-binary @- \
     | grep "^data:" | head -1 | sed 's/^data: //' \
     | jq '.result.content[0].text | fromjson | {ok, config_yaml: .steps.config_yaml, use_case_dict: .steps.use_case_dict, vlm_task: .steps.vlm_task, warnings}'
```

**期望**：

```json
{
  "ok": true,
  "config_yaml": "written",
  "use_case_dict": "added",
  "vlm_task": "registered",
  "warnings": []
}
```

**磁盘校验**（关键）：

```bash
grep -A6 "^  pet_safety_persisted:" config.yaml.example
```

**期望**：能看到条目 + `video_summary_task` / `evaluate_rules_path` / `rules` / `description` 字段。同时**其他 use case 的注释和字段顺序应该保留**（yaml Document API 是 comment-preserving，虽然 stringify 后 `#` 前空格、`[ ]` 数组间距会做 normalize，但语义等价）：

```bash
# 校验 child_safety 的注释还在
grep -B1 -A3 "^  child_safety:" config.yaml.example
```

**期望**：看到 `severityThreshold: warn` 后面的 `# ... — fires at or above this` 注释还在。

**若 `config_yaml: "skipped"`** + 出现 warning：
- `"persist requested but configPath is unset..."` → MCP 启动没带 `--config`，只能改内存，磁盘不落
- `"persist to <path> failed: <err>"` → 写盘 IO 报错（权限 / 磁盘满等），in-memory 依然生效

**MCP 重启验证磁盘写回真正生效**（可选，用 §10 unregister 前跑一次）：

```bash
# 停 MCP
pkill -f "packages/mcp-server/dist/index.js"
sleep 2
# 重启（磁盘上 pet_safety_persisted 条目应该还在）
grep pet_safety_persisted config.yaml.example
# 期望：看到条目（重启前 persist=true 写下的）
# 重启 MCP
cd /home/user/jie/smarthome/smart-community
node packages/mcp-server/dist/index.js --http \
  --config config.yaml.example --monitors monitors.yaml.example &
sleep 3
# 校验 pet_safety_persisted 从磁盘加载到了内存
curl -sf -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
    "name":"smartbuilding_use_case_validate",
    "arguments":{"use_case":"pet_safety_persisted"}}}' \
  | grep "^data:" | head -1 | sed 's/^data: //' | jq '.result.content[0].text | fromjson | {valid, checks}'
# 期望：valid=true 且 checks 三段都 true —— 重启后 use case 从磁盘恢复
```

---

## 6. 每一步的独立验证

### 6.1 VLM 端

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

### 6.2 DB schema

```bash
sqlite3 "${SMARTBUILDING_DATA_DIR:-$HOME/.mcp-smartbuilding}/smartbuilding.db" \
  "PRAGMA table_info(video_summary_tasks);" | grep pet_zone
```

**期望**：一行 `<idx>|pet_zone|TEXT|0||0`。

### 6.3 In-memory use_case_dict

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

## 7. 从零真实链路端到端（pet_safety.mp4，走完整 VSA → MCP → VLM → rule 管线）

> 这一节是**从零、走真实管线**的完整走查，用 `demo-videos/cam_pet/pet_safety.mp4`。
> 下面 §8 是**只验规则**的捷径（手塞 task + rule_eval），§7 跑不通时可退到 §8 分段定位。
> 管线对应 design [§5 use-case-adapter](../smartbuilding-video-design-2026.2.md#5-use-case-adapter)：
>
> ```
> ffmpeg 推流 → MediaMTX(:8554) → VSA(:8999) motion 检测 → webhook POST → MCP(:3101/events)
>   → 建 pending video_summary_task → task-poller 轮询 → ffmpeg 切 clip
>   → POST /v1/summary 到 multilevel-video-understanding(:8192) → summary_text
>   → parseSummaryFields 抽字段(event/severity/desc/pet_zone) → evaluate_rules.py 判定
>   → 命中则写 alerts 行 + broadcast notifications/resources/updated
> ```

### Phase 0 — 起 4 个服务（都不需要为 pet_safety 改任何配置，这就是"从零"）

```bash
export SMARTBUILDING_DATA_DIR="${SMARTBUILDING_DATA_DIR:-$HOME/.mcp-smartbuilding}"

# (a) VLM 后端：vllm-ipex-serving(:41091) + multilevel-video-understanding(:8192)
cd docker/video-summary && source set_env.sh && docker compose up -d
#   等两个容器 healthy：
docker compose ps        # STATUS 都是 healthy 再继续（vllm 首次编译 FP8 可能数分钟）
curl -sf http://localhost:8192/v1/health && echo " VLM ok"

# (b) videostream-analytics(:8999)
cd videostream-analytics && docker compose -f docker/docker-compose.yaml up -d
curl -sf http://localhost:8999/health && echo " VSA ok"

# (c) MediaMTX(:8554) — 提供 RTSP
~/.local/bin/mediamtx /path/to/mediamtx.yml &

# (d) MCP server(:3100 + :3101) —— 用 config.yaml.example 起，里面【没有】pet_safety
cd <repo-root>
npm run build
node packages/mcp-server/dist/index.js --http --config config.yaml.example
#   启动日志含：[mcp-server] Streamable HTTP on :3100/mcp + [events-endpoint] Listening on :3101
```

前置校验（pet_safety 应处处不存在）：

```bash
curl -sf http://localhost:8192/v1/tasks | jq '[.tasks[].name]|map(select(test("pet_safety")))'   # []
sqlite3 "$SMARTBUILDING_DATA_DIR/smartbuilding.db" "PRAGMA table_info(video_summary_tasks);" | grep -c pet_zone  # 0
```

### Phase 1 — use case 素材（已在 repo 里，无需新建）

- [use-cases/pet_safety/prompt.md](../../use-cases/pet_safety/prompt.md) —— `## LOCAL_PROMPT`，输出
  `SEVERITY` / `EVENT`(pet_stuck|pet_escape|pet_normal|no_incident) / `DESC` + 可选 `pet_zone`。
- [use-cases/pet_safety/evaluate_rules.py](../../use-cases/pet_safety/evaluate_rules.py) —— 从 `argv[1]`
  读 ctx，按 `rules.severityThreshold` 门限判 `should_alert`（`no_incident` 直接不报）。

### Phase 2 — 零重启注册 use case（`smartbuilding_use_case_register action=register`）

一次调用做 4 件事：① `ALTER TABLE` 加 `pet_zone` 列 ② POST `/v1/tasks` 把 prompt 注册到 VLM（409 自动 PATCH）
③ 注入内存 `useCaseDict.pet_safety` ④ 复跑 `use_case_validate`。用 jq 把 prompt.md 塞进请求体：

```bash
PROMPT=$(cat use-cases/pet_safety/prompt.md)
jq -n --arg p "$PROMPT" '{jsonrpc:"2.0",id:1,method:"tools/call",params:{
  name:"smartbuilding_use_case_register",
  arguments:{
    action:"register",
    use_case:"pet_safety",
    video_summary_task:"pet_safety_monitor",
    description:"Household pet safety monitoring",
    prompt_text:$p,
    evaluate_rules_path:"./use-cases/pet_safety/evaluate_rules.py",
    rules:{severityThreshold:"warn"},
    schema_extensions:[{name:"pet_zone",type:"text",required:false}],
    reports:{data_source:"alerts",default_type:"daily",filter:{}}
  }}}' | curl -sf -X POST http://localhost:3100/mcp \
    -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
    -d @- | grep "^data:" | head -1 | sed 's/^data: //' \
    | jq '.result.content[0].text | fromjson | {ok, steps, warnings, validate}'
```

**期望**：`ok:true`，`steps` 含 schema/vlm/useCaseDict/validate 四段成功；`validate` 三项 check 为 true。
逐项复核：

```bash
curl -sf http://localhost:8192/v1/tasks | jq '[.tasks[].name]|map(select(test("pet_safety")))'  # ["pet_safety_monitor"]
sqlite3 "$SMARTBUILDING_DATA_DIR/smartbuilding.db" "PRAGMA table_info(video_summary_tasks);" | grep pet_zone  # 有
```

### Phase 3 —（可选）单独打样 VLM，先确认 prompt 本身能出结构化输出

把测试视频放到 VLM 容器能看见的路径（VLM 容器把 host `$SMARTBUILDING_DATA_DIR` 经 path_remap 映射到 `/data`）：

```bash
mkdir -p "$SMARTBUILDING_DATA_DIR/test-videos/pet_safety"
cp demo-videos/cam_pet/pet_safety.mp4 "$SMARTBUILDING_DATA_DIR/test-videos/pet_safety/pet_safety.mp4"

# ⚠️ 必须显式传 method + processor_kwargs（省略 method 会踩上游 default 分支 bug，见 vlm gsg Issue #1）
curl -sf -X POST http://localhost:8192/v1/summary -H "Content-Type: application/json" -d '{
  "video":"/data/test-videos/pet_safety/pet_safety.mp4",
  "task":"pet_safety_monitor",
  "method":"SIMPLE",
  "processor_kwargs":{"levels":1,"level_sizes":[-1],"process_fps":2}
}' | jq '{status, summary}'
```

**期望**：`status:"completed"`，`summary` 里有 `SEVERITY:` / `EVENT:` / `DESC:`（+ 可能 `pet_zone`）。

### Phase 4 — 注册 monitor + 推流（走真实管线）

```bash
# (a) 注册 monitor（monitor_ctl register_source）—— MCP 会把 data_dir、webhook 都配好
jq -n '{jsonrpc:"2.0",id:1,method:"tools/call",params:{
  name:"smartbuilding_monitor_ctl",
  arguments:{
    action:"register_source",
    monitor_id:"cam_pet",
    source_url:"rtsp://localhost:8554/live/pet",
    use_case:"pet_safety",
    video_summary_task:"pet_safety_monitor",
    webhook_url:"http://localhost:3101/events"
  }}}' | curl -sf -X POST http://localhost:3100/mcp \
    -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
    -d @- | grep "^data:" | head -1 | sed 's/^data: //' | jq '.result.content[0].text | fromjson'
#   期望：{"success":true,"monitor_id":"cam_pet"}；VSA /sources 里出现 cam_pet

# (b) 推流：把 pet_safety.mp4 循环推到 /live/pet
ffmpeg -re -stream_loop -1 -i demo-videos/cam_pet/pet_safety.mp4 \
  -c copy -f rtsp rtsp://localhost:8554/live/pet
```

### Phase 5 — 观察全链路落库

```bash
DB="$SMARTBUILDING_DATA_DIR/smartbuilding.db"

# 1) VSA 产生 motion → MCP 建 task（先 pending，poller 处理后 completed）
watch -n 3 "sqlite3 -header '$DB' \"SELECT id,status,event,severity,pet_zone,substr(summary_text,1,40) \
  FROM video_summary_tasks WHERE monitor_id='cam_pet' ORDER BY id DESC LIMIT 5;\""

# 2) clip 落到 host（恒等挂载生效的证明）
ls "$SMARTBUILDING_DATA_DIR/segments/cam_pet/motion_events/$(date +%F)/"

# 3) 命中规则的 alert
sqlite3 -header "$DB" "SELECT id,use_case,description,created_at FROM alerts WHERE monitor_id='cam_pet' ORDER BY id DESC LIMIT 5;"

# 4) 用 MCP 工具查（等价于 agent 会看到的）
jq -n '{jsonrpc:"2.0",id:1,method:"tools/call",params:{name:"smartbuilding_alert_query",
  arguments:{monitor_id:"cam_pet",limit:5}}}' | curl -sf -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d @- | grep "^data:" | head -1 | sed 's/^data: //' | jq '.result.content[0].text | fromjson'
```

**判定通过**：`video_summary_tasks` 出现 `status=completed` 且 `event`/`pet_zone` 被抽出；若视频里有
`pet_stuck`/`pet_escape` 且 severity ≥ warn，则 `alerts` 出现对应行、`alert_query` 能查到。

> 若 §7 Phase 5 里 motion 一直不触发（`motion_events/` 空）——这是**视频内容/motion 阈值**问题（参考
> 之前 Issue #4：短 loop 视频画面变化过小）。此时退到 §8 用 `rule_eval` 手塞 task 单独验规则链路。

### 清理

```bash
# unregister monitor + use case
# monitor_ctl action=unregister monitor_id=cam_pet；use_case_register action=unregister use_case=pet_safety
```

---

## 8. 端到端跑通（如果你手上有 pet 视频）

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

## 9. 未提供 prompt_text 的场景（VLM 侧手动注册）

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

## 10. Unregister

### 10.1 不带 persist（只清内存，磁盘 config 里的条目保留）

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

### 10.2 带 persist=true（同时清磁盘 config 里的条目）

针对 §5 里落盘的 `pet_safety_persisted`：

```bash
curl -sf -X POST http://localhost:3100/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
    "name":"smartbuilding_use_case_register",
    "arguments":{"action":"unregister","use_case":"pet_safety_persisted","persist":true}}}' \
  | grep "^data:" | head -1 | sed 's/^data: //' \
  | jq '.result.content[0].text | fromjson | {ok, config_yaml: .steps.config_yaml, use_case_dict: .steps.use_case_dict, vlm_task: .steps.vlm_task}'
```

**期望**：

```json
{
  "ok": true,
  "config_yaml": "removed",
  "use_case_dict": "removed",
  "vlm_task": "deleted"
}
```

**磁盘校验**：

```bash
grep pet_safety_persisted config.yaml.example
# 期望：无输出（条目已从磁盘删除，其他 use case 条目和注释保留）
```

**注意**：`pet_zone` schema 列**不会**被 drop（sqlite 限制 + 数据安全）。想清理：手动 `sqlite3 ... ALTER TABLE ... DROP COLUMN pet_zone`（sqlite ≥ 3.35）。

---

## 11. 已知 gap 一览（跑完上面能观察到的）

| Gap | 表现 | 缓解方式 |
|---|---|---|
| ~~**重启丢失**~~ | ~~重启 MCP 后 `smartbuilding_use_case_validate use_case=pet_safety` 返回 `unknown use_case`~~ | ✅ **已修**（Plan §27 Step 2）：register 时传 `persist: true` 让 tool 用 yaml Document API 写回 config.yaml；MCP 重启后自动从磁盘加载。见 §5 |
| ~~**`config.yaml` 不写回**~~ | ~~磁盘上的 config.yaml 永远只有启动时的内容~~ | ✅ **已修**（Plan §27 Step 2）：`persist: true` 参数上线 |
| **`prompt.md` 需手写** | Tool 不生成 prompt | ⛔ 早期 `action=generate_prompt`（Plan §29）已于 2026-07 移除；prompt 起草改由 `video-summary-prompt-studio` skill（agent + router）承担，落地经 `action=register` 的 `prompt_text`。见 [gap-analysis §6.2](./use-case-adapter-gap-analysis.md) |
| **`evaluate_rules.py` 需手写** | Tool 不生成 Python 脚本，只登记路径 | ✅ **已缓解**（Plan §27 Step 1）：`defaultRuleEvaluator` 加 4 keys（`requireEvent` / `requireDirection` / `excludeZones` / `alertMessageExtraField`）后，简单 UC 完全用 rules dict 表达，**无需 evaluate_rules.py**。见 §4 结尾的"替代方案" |
| **schema 列不能撤销** | `unregister` 保留 `pet_zone` 列 | 手动 `ALTER TABLE ... DROP COLUMN`（sqlite 3.35+） |
| **prompt_text 换行处理** | Markdown 里含 `'''` 会污染 Python 源码字符串 | 目前用 `'''` 作 heredoc；如 prompt 里有三单引号需要人工 escape。P3 改用 `"""` + smart quoting |
| **并发写入** | 两个客户端同时 register 同一个 use_case，最后写入者赢 | MCP 单进程；实际不会并发；如担心可加分布式锁（超出当前范围）|
| **VLM 端 dynamic task delete 不清 monitors 表** | unregister 时如果对应 monitor 还 registered，DELETE /v1/tasks 成功但 monitors 表引用悬空 | 先 `smartbuilding_monitor_ctl unregister monitor_id=<x>` 再 use_case_register unregister |

---

## 12. 附录：完整清理

```bash
# 反向清掉所有 side effects（假设 unregister 已跑）
rm -rf use-cases/pet_safety
sqlite3 "${SMARTBUILDING_DATA_DIR:-$HOME/.mcp-smartbuilding}/smartbuilding.db" \
  "DELETE FROM video_summary_tasks WHERE monitor_id='cam_pet';"
# schema 列 pet_zone 可选保留

# 再跑一次 §0 前置校验，应回到"pet_safety 相关全 0"的初始态
```
