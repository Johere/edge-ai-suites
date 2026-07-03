# Integration Status — 已识别的跨仓 / 跨模块 gap

本文档收集集成测试期间发现的、**跨我职责范围外**的问题：

- **§A. 跨模块改动清单** — 我负责 `videostream-analytics/` + `use-cases/` +
  `docs/use-case-*.md`；但在跟 MCP server / VLM 联调时不得不动了别的模块的代码。
  这一节列每处改动 + 为什么改 + jiaojiao / 上游后续要不要 review / 是否要移交
- **§B. 上游 bug 单** — `edge-ai-libraries/multilevel-video-understanding` 侧的
  bug（本仓无法独立修复），列复现命令 + 建议给上游的修法

对**我自己负责模块内部** gap（vsa / use-cases 内部）见
[use-case-adapter-gap-analysis.md](./use-case-adapter-gap-analysis.md)。

---

## §A. 跨模块改动清单（我改了别的模块，需要沟通/review）

我 (Jie) 负责的模块：`videostream-analytics/` + `use-cases/` +
`docs/{use-case-*,vsa-gsg,vlm-integration-gsg}.md`。以下改动落在**其他人的
模块**里，是集成测试触发的最小侵入修补，需要相应 owner 复核：

### A.1 `packages/mcp-server/src/events-endpoint.ts` — 加 `type: "status"` 支持

**为什么改**：VSA `rtsp_monitor.py` 每次 RTSP 状态变化 emit
`{"type":"status", ...}` webhook，MCP 端 `KNOWN_TYPES` 只认
`motion / static / recording`，走 default 分支返 422 `unknown_event_type`。VSA
`webhook_client.py` 只对 < 400 认为成功，422 触发 3 次 retry × 2s，每次断连日志
刷屏 + 抬高恢复延迟。

**改动**（3 处）：
- `VideoEvent.type` 联合加 `"status"`
- `KNOWN_TYPES` set 加 `"status"`
- `dispatch()` 加 `case "status"`：返 200 `{acknowledged: true}`，**不落 DB**（保持 events / recordings 表 use-case-agnostic），DEBUG 级别记状态值

**决策**：走**选项 A（静默吞 200）**而不是选项 B（新增 monitor_state 表存 status）。理由：
- 主链路 motion / recording 完全不受影响，最小侵入
- 不改 schema、不加表
- 未来若要真订阅 status（UI 显示"cam_X 掉线"），在 `case "status"` 里加 DB 写入即可，A 不阻塞 B

**owner 侧行动**：本改动完全兼容原 API 契约（外部客户端如果不发 status 事件，行为不变）；建议 jiaojiao / MCP owner **合并**。

### A.2 `packages/tools/src/rule-engine/index.ts` — 加 execFile timeout

**为什么改**：Phase 4 手工测 `smartbuilding_rule_eval` 时，MCP 侧 curl 超过 2 分钟无返回。定位：`evaluateWithOverride` 里 `execFileAsync("python3", ...)` **没设 timeout**——用户 override 里若不小心用了 `json.load(sys.stdin)`（该 API 应从 argv[1] 读），python 子进程会阻塞等 stdin，MCP 永远等 execFile。对比 `task-poller.ts` 里的 `parseSummary` / `runOnTaskCompleted` 两处都有 `timeout: 10_000`，只有 `evaluateWithOverride` 漏了。

**改动**：加一行 `{ timeout: 10_000 }` 参数（与 task-poller 一致）。

**owner 侧行动**：小改，行为增益：broken override 从"挂死" → "超时 fallback 到 defaultRuleEvaluator + console.error"。建议 review 合并。

### A.3 `packages/tools/src/use-case-register.ts` （新建）+ `packages/mcp-server/src/tools.ts` (+61 行 MCP tool 注册) + `packages/tools/src/index.ts` (export)

**为什么新增**：Design §5.2 承诺"零代码 3 输入注册 use case"，但之前完全没实现（gap-analysis P2 项）。用户加新 use case 只能：改 config.yaml + 重启 MCP + 手 curl POST /v1/tasks + 手加 schema 列。**这次实现**了 `smartbuilding_use_case_register` MCP tool 一次调用完成 schema ALTER + VLM POST /v1/tasks(409 → PATCH) + inject useCaseDict + validate 复核。

**架构决策**：
- **零重启**：`useCaseDict` 在 MCP 是启动时快照，但代码里所有 tool handler 和 `task-poller.ts:76` 都是按引用持有 `config`，每次 poll 重读 `useCaseDict[useCase]`——`config.useCaseDict[name] = entry` 会立即被下一次 poll 看到
- **不写回 config.yaml**：mutation 只改内存；用户如需持久化需自己抄回磁盘（gap 记录为 P3 `persist: true` 参数）
- **段名解析**：`parseMarkdownSections` 正则 `^##\s+([A-Z0-9_]+)\s*$` 必须含数字（不然 `T_MINUS_1_PROMPT` 段名匹配不到——见 Issue #2 教训）

**owner 侧行动**：这是**新功能**而非 bug fix。建议 jiaojiao / MCP owner：
1. Review 设计（"零重启" 是否符合他们对 MCP tool 语义的预期）
2. Review implementation（`packages/tools/src/use-case-register.ts` 是主体逻辑）
3. 讨论后续 P3 `persist: true` 是否值得做

### A.4 `docs/smart_community_mcp_gsg.md` — 补齐"启动 VLM 后端"章节

**为什么改**：原文档（jiaojiao push）§0 没有"起 VLM 后端"步骤——但 MCP 依赖 `multilevel-video-understanding` (`:8192`)，用户按 gsg 起 MCP 会报 `Connection refused`。另外 §6 配置示例是残缺版（缺 `path_remap` / `vlm_service` / `events_webhook`），§7 tool 表按老的 8 tool 写。

**改动**：
- 新增 §0 "启动 VLM 后端"章节：`source ./set_env.sh` + `docker compose up -d`，含旧 stack 停机说明
- §6 完整版配置示例（`summary_service.path_remap` + `vlm_service` + `events_webhook` + 数据目录布局）
- §7 tool 表从 8 tool 补齐为 10 tool（新增 `smartbuilding_monitors_compose` / `smartbuilding_plan_ctl` / `smartbuilding_generate_report`；原文档写的 `smartbuilding_daily_report` 是错误名字，实际是 `smartbuilding_generate_report`）
- §4 Inspector 期望 tool 数量 8 → 10

**owner 侧行动**：文档 fix。建议 jiaojiao **合并**（都是把过时/残缺信息补齐，与她的原始意图一致）。

### A.5 数据目录/命名一致性（vsa-gsg 集成过程中触碰的 config）

- `config.yaml.example` 里加 `severity: required: false`（use-case-adapter 集成侧修 Issue #5——elder_wakeup 天然不产 severity）
- `config.yaml.example` 里加 `child_safety.rules.cooldownSeconds: 60`（为跑 U8 补的示例值）
- `monitors.yaml.example` append `cam_high_altitude` / `cam_parking`（跑 §9 扩展验证补的 monitor 声明）
- `demo-videos/streams.yaml` append 同 2 条 stream

这些不算跨模块 gap——都是**我领地内**（monitors.yaml / config.yaml / streams.yaml
是用户 owned），列在这里只是为了跟集成测试过程的可追溯性。

---

## §B. 上游 bug 单

## Issue #1 — multilevel-video-understanding：不指定 `method` 时服务端自我拒绝

**发现日期**：2026-07-03
**报告人**：Jie
**上游仓**：`edge-ai-libraries/microservices/multilevel-video-understanding`

### 复现

```bash
curl -sS -X POST http://localhost:8192/v1/summary \
  -H "Content-Type: application/json" \
  -d '{
    "video": "/data/segments/cam_child/motion_events/2026-07-02/cam_child_141848.mp4",
    "task": "child_safety_monitor"
  }' | python3 -m json.tool
```

（`video` 是容器内合法路径 + `task` 是已注册的 dynamic task；**唯独没传 `method`**）

### 服务端返回

```json
{
  "detail": {
    "error_message": "Summarization failed!",
    "details": "Unsupported summarization method: SUMMARIZATION_METHOD_TYPE.USE_ALL_T_1, choices: ['SIMPLE', 'USE_VLM_T-1', 'USE_LLM_T-1', 'USE_ALL_T-1']"
  }
}
```

### 根因（推测，需要上游确认）

服务端 Python `SUMMARIZATION_METHOD_TYPE` enum 定义里 `name` 与 `value` 拼写不一致：

- `enum.name` 用**下划线**：`USE_ALL_T_1`（Python enum `name` 天生不允许 `-` 字符）
- `enum.value` 用**连字符**：`USE_ALL_T-1`

请求不带 `method` 时，服务端 fallback 逻辑用了 `enum.name`（下划线）去比对合法
choices 列表（`enum.value`，连字符），肯定不匹配，就报了这条自打耳光的
"unsupported ... choices includes it" 错。

**猜测代码位置**：`video_analyzer/schemas/summarization.py` 或
`video_analyzer/api/endpoints/summary.py` 里对 `request.method` 的 fallback /
默认值处理逻辑。**未验证**（本仓没 clone 到 edge-ai-libraries submodule 时无法读）。

### 影响面

**对生产链路（task-poller）**：**无影响**。task-poller 永远显式传 `method`，见
[task-poller.ts:89-100](../../packages/mcp-server/src/video-worker/task-poller.ts#L89-L100)：

```ts
const summarizeCfg = useCaseCfg?.summarize ?? {};
const result = await this.videoSummaryClient.summarize({
  video: videoPath,
  task: summaryTaskName,
  method: summarizeCfg.method ?? "SIMPLE",        // ← 永远传显式 method
  processor_kwargs: {
    levels: summarizeCfg.processor_kwargs?.levels ?? 1,
    level_sizes: summarizeCfg.processor_kwargs?.level_sizes ?? [-1],
    process_fps: summarizeCfg.processor_kwargs?.process_fps ?? 2,
    ...
  },
});
```

`use_case_dict.<uc>.summarize` 缺省填的就是 `SIMPLE` + `levels=1, level_sizes=[-1], process_fps=2`，配置层已经把这条路径守住了。

**对手工 curl 打样 / 集成测试**：**有影响**。凡是按 gsg 提示"跳过 VSA，直接对 VLM
打样"的场景（e.g. 验证 prompt / 校验新 use case 的 VLM 输出格式），如果按
`SummarizationRequest` OpenAPI schema 提示"method 可选"就省略，一律会踩这个坑。
误导性尤其强：

- 报错信息叫 `Summarization failed!` 看上去像 VLM 推理本身失败
- `choices` 列表里明明列了 `USE_ALL_T-1` —— 让人以为"我传了 USE_ALL_T-1 也不行"
  而非"服务端没接收到我的 method"
- 结合 `curl -sf` 的默认行为（`-f` 吞 error body）→ 一层套一层，非常难定位

### Workaround（本仓侧已应用）

**任何 `/v1/summary` 请求都显式传 `method` + `processor_kwargs`**，即使只是打样。
参考 [use-case-adapter-gsg.md §4](../use-case-adapter-gsg.md#4-vlm-输出校验前置)
已更新的示例：

```bash
curl -sS -X POST http://localhost:8192/v1/summary \
  -H "Content-Type: application/json" \
  -d "{
    \"video\": \"$CONTAINER_CLIP\",
    \"task\": \"child_safety_monitor\",
    \"method\": \"SIMPLE\",
    \"processor_kwargs\": {\"levels\": 1, \"level_sizes\": [-1], \"process_fps\": 2}
  }" | python3 -m json.tool
```

### 需要上游修的东西（沟通时可直接抛出）

请上游确认并修：

1. **是否 `enum.name` vs `enum.value` 拼写不一致**（`_` vs `-`）？如果是，把
   fallback 里的 `.name` 换成 `.value`，或者两处都用 hyphen（保持一致）。
2. **默认值行为**：不传 `method` 时应该 fallback 到哪个合法枚举？API doc /
   OpenAPI schema 里 `method` 若标了 `optional`，服务端就应有明确默认值。目前
   实际是"默认值指向了一个非法字符串"，属于 default 分支 bug。
3. **错误信息可改进**：当前 `error_message: "Summarization failed!"` 让人以为是
   推理失败，实际是入参验证问题。分开 4xx（参数错）和 5xx（推理错）会更清晰。

### 对我的集成测试的影响

- **U1-U10 基线**（use-case-adapter-gsg.md §5）：**不受影响**——都走 task-poller
  自动路径，method 已经在配置层填好
- **§4 VLM 输出校验前置** / **手工打样验证 prompt**：**受影响**——手抄命令时必须
  记得加 `method` + `processor_kwargs`；gsg 示例已更新
- **§9 扩展验证（HA / Parking 自定义 UC）**：**受影响**——如果按
  [use-case-adapter-validation.md](./use-case-adapter-validation.md) 里"手工塞
  DB + 打 VLM 样"的调试路径走，一样要加 method
- **§10 零重启 use_case_register**：**不受影响**——tool 内部注册 VLM task 时用的是
  `POST /v1/tasks`（不是 /v1/summary），根本不涉及 method 字段

**结论**：只要坚持"生产路径永远显式传 method + gsg 手工样都改用 SIMPLE"，本
issue 不阻塞任何集成测试。

### 状态

- [x] 2026-07-03 识别根因（推测）
- [x] 本仓 gsg 已加显式 `method` + 注释说明
- [ ] 上游 issue 未提
- [ ] 上游修复未合并

---

## Issue #2 — 本仓 prompt.md 段名解析漏认 `T_MINUS_1_PROMPT`（**已在本仓修复**）

**发现日期**：2026-07-03
**报告人**：Jie
**责任仓**：本仓 —— `smart-community/docs/vlm-integration-gsg.md` §3 / §3.2 的 python
注册脚本 + `packages/tools/src/use-case-register.ts` 的 `parseMarkdownSections`

### 现象

跑 `POST /v1/summary` 返 500：

```json
{
  "detail": {
    "error_message": "Summarization failed",
    "details": "An unexpected error occurred during summarization:\nMissing required fields: ['dur', 'past_summary']\n\nDebug traceback:\n  File \"/app/video_analyzer/prompts/prompt_dynamic.py\", line 66, in assign_local_prompt\n    ..."
  }
}
```

即使请求里传了 `method: "SIMPLE"`（本该只用 LOCAL_PROMPT），VLM 端在渲染
LOCAL_PROMPT 时仍报缺 `dur` / `past_summary` —— 这两个应当只出现在
T_MINUS_1_PROMPT 里的 template variable。

### 根因

**本仓 markdown 段名正则漏掉数字**。`use-cases/<uc>/prompt.md` 用 `## SECTIONNAME`
分段（GLOBAL_PROMPT / MACRO_CHUNK_PROMPT / LOCAL_PROMPT / **T_MINUS_1_PROMPT**）。
注册脚本用正则 `^##\s+([A-Z_]+)\s*$` 匹配段标题 —— 但 **T_MINUS_1_PROMPT 里含数字
`1`**，`[A-Z_]+` 不匹配数字 → `## T_MINUS_1_PROMPT` 这行被当作段内容而非段标题。

结果：从 `## LOCAL_PROMPT` 开始到文件末尾**所有内容**（**包括** `## T_MINUS_1_PROMPT`
段的原文，含 `{dur}` / `{past_summary}` 占位符）**全部塞进了 LOCAL_PROMPT 常量的字符串**；
`T_MINUS_1_PROMPT` 常量拿到的是脚本 fallback 的短模板，与 prompt.md 里精心写的
上下文块完全脱钩。

**核心证据**（`curl /v1/tasks/child_safety_monitor | jq -r .content` 的 grep）：

```
1:GLOBAL_PROMPT = '''...
67:MACRO_CHUNK_PROMPT = '''...
94:LOCAL_PROMPT = '''...
158:## T_MINUS_1_PROMPT           ← 段标题被误算作 LOCAL_PROMPT 内容
167:T_MINUS_1_PROMPT = '''...    ← 与 prompt.md 定义无关的 fallback 短模板
```

L94-166 的 `LOCAL_PROMPT` 字符串常量里意外含了 `{dur}` / `{past_summary}` —— 服务端渲染
LOCAL_PROMPT 时找不到这两个变量的值，才报出让人误以为是 "T_MINUS_1 泄漏到 SIMPLE
模式" 的错。

### 修复

**已修**（正则加数字）：

- [packages/tools/src/use-case-register.ts:295](../../packages/tools/src/use-case-register.ts#L295)：
  `[A-Z_]+` → `[A-Z0-9_]+`
- [docs/vlm-integration-gsg.md:290,370](../vlm-integration-gsg.md)：两份注册脚本样例正则同步更新
- `npm run --workspace=@smartbuilding-video/tools build` 通过

**用户侧行动**：重新跑一次 register 脚本（`POST /v1/tasks` 409 会自动 PATCH，覆盖
坏内容），然后 `curl /v1/tasks/<name> | jq -r .content | grep -n "T_MINUS_1_PROMPT"`
应只见 Python 常量定义，不再有 markdown 段标题混在中间。

### 影响面

- **对生产链路**：**有影响但被本仓 gsg 隐式绕开** —— 用户如果**没照 vlm-integration-gsg.md
  §3.2 一键脚本**注册 task（比如自己手抄 prompt 内容 curl），就不会踩此坑。**只有走
  gsg 脚本注册的 4 个 dynamic task 都受影响**：`child_safety_monitor` /
  `elder_wakeup_monitor` / `high_altitude_monitor` / `parking_safety_monitor`
- **对手工打样 / 集成测试**：**严重误导** —— 报错文本 `Missing required fields:
  ['dur', 'past_summary']` 看起来像"服务端不该渲染 T_MINUS_1_PROMPT 却渲染了"，其实
  真因是 LOCAL_PROMPT **自己**串号了

### 教训

段名任意允许字母数字下划线是行业惯例（e.g. C identifier `[A-Za-z_][A-Za-z0-9_]*`）。
本仓遗漏数字的原因是"当时的 use case 段名都不含数字（GLOBAL / MACRO / LOCAL）"—— 后
来加 `T_MINUS_1_PROMPT` 引入数字时，作者只对齐了字符串常量名而没修解析正则。类似
的"未来某天加个新段就会踩"的正则 gap 应加进 lint 检查（P3 项）。

### 对我的集成测试的影响

- **U1 - U10 基线（use-case-adapter-gsg.md §5）**：**修复前 100% 受阻**（4 个 dynamic
  task 都错），**修复并 re-register 后正常**。这就是你之前 U1 打样返 500 的直接原因
- **§9 扩展验证（HA / Parking）**：受阻程度一致（同样走注册脚本）
- **§10 零重启 use_case_register**：**修复后自动正确** —— tool 本身用同一份
  `parseMarkdownSections`，正则已修

### 状态

- [x] 2026-07-03 识别根因（100% 确认）
- [x] 本仓修复已合入（`use-case-register.ts` + `vlm-integration-gsg.md` 两处正则）
- [x] `tools` package build 通过
- [ ] 需 user 手动 re-register 4 个 dynamic task 才能验证修复效果

---

## Issue #3 — `evaluateWithOverride` 无 timeout，broken override 挂死 rule_eval（**已在本仓修复**）

**发现日期**：2026-07-03
**报告人**：Jie
**责任仓**：本仓 —— `smart-community/packages/tools/src/rule-engine/index.ts`

### 现象

Phase 4 §5 端到端手塞 `pet_safety` task 跑 `smartbuilding_rule_eval` 时，MCP 侧 curl **超过 2 分钟无返回**（curl timeout 后我 kill 掉才终止）。事后 `ps aux | grep evaluate_rules.py` 显示 python 子进程一直在跑。

### 根因

`evaluateWithOverride`（[rule-engine/index.ts:119-123](../../packages/tools/src/rule-engine/index.ts)）用 `execFileAsync("python3", [overridePath, JSON.stringify(context)])` 拉起 Python override，**没设 timeout**。对比 `task-poller.ts` 里的 `parseSummary` 和 `runOnTaskCompleted` 两处都设了 `timeout: 10_000`，只有 `evaluateWithOverride` 漏了。

问题的**触发条件**是用户的 `evaluate_rules.py` 试图从 stdin 读 ctx（本文档示例就写错过一次：`json.load(sys.stdin)`）——但 MCP 是通过 argv[1] 传 ctx，stdin 是 pipe 但无数据，`json.load(sys.stdin)` 无限阻塞 → MCP 侧永远等 execFile → MCP 请求也永远挂。

### 修复

**已修**（[rule-engine/index.ts:120-123](../../packages/tools/src/rule-engine/index.ts) 加 `timeout: 10_000` 参数）：

```ts
const { stdout } = await execFileAsync("python3", [
  overridePath,
  JSON.stringify(context),
], { timeout: 10_000 });    // ← 加这个 option
```

`tools` package build 通过。**当前跑着的 MCP 是老 dist，需要重启 MCP 生效**——但即使不重启也不影响集成测试（只要 override 里不用 stdin 就不会 hang）。

### 影响面

- **生产链路**：**低概率** —— 现有 `use-cases/*/evaluate_rules.py` 都是 argv[1] 模式，不会踩坑；只有用户手写新 override 用错 API 才会触发
- **集成测试 / Phase 4 verification.md**：直接命中 —— 文档里 §3 evaluate_rules.py 示例就是本次踩坑的现场

### 状态

- [x] 2026-07-03 识别根因（100% 确认，ps 看到挂起的 python 子进程 + 无 timeout 代码路径）
- [x] 本仓修复合入
- [x] build 通过
- [ ] 待 MCP 重启验证

---

## Issue #4 — VSA motion detection 对 5s loop 短视频不触发（观察，非 bug）

**发现日期**：2026-07-03
**报告人**：Jie

### 现象

Phase 3 U11a 试图用 [demo-videos/cam_ha_test/building-throwing-2.mp4](../../demo-videos/cam_ha_test/building-throwing-2.mp4)（5s 视频）走完整 VSA → VLM 链路。ffmpeg loop 推流 3 分钟后：

- `recordings/` 目录里 clip 95MB（VSA 一直在录）
- **`motion_events/` 目录空** —— VSA motion detector 没触发
- `video_summary_tasks` 里没 `cam_high_altitude` 相关任务

### 根因（推测）

5s 视频 loop 时，唯一"画面剧变"发生在 loop 循环点（视频末尾接到开头），可能被 VSA `motion.stable_frames=30` 的 debounce 逻辑过滤。视频本身的塑料袋坠落画面变化幅度可能低于 `diff_threshold=25`。

### 影响面

- **生产链路**：无影响（真实 RTSP 流没有 loop 循环点问题；且视频长度足够）
- **集成测试 U11 / U12**：如果**必须走完整 VSA 链路**，需要用够长（≥30s）且画面变化明显的视频。**已 workaround**：本轮 U11a/U11b/U12a/U12b 都改用"手塞 completed task 到 DB + rule_eval" 的调试路径，验证 rule engine + payload.rules 链路即可

### Workaround / 建议

- U11 / U12 已用"手塞 task" 路径完全跑通（4 个 case 都 pass）—— 详见 gsg §9.4 alternate path
- 未来若要走完整 VSA 链路：生成 ≥30s、多次坠落片段的视频（详见 [use-case-adapter-gsg.md §9.3 视频生成规范](../use-case-adapter-gsg.md#93-视频生成规范)）

### 状态

- [x] 2026-07-03 观察到
- [x] Workaround 生效（rule_eval 手塞 task 路径），U11 / U12 全部 pass
- [ ] 是否要在 gsg §9.4 里加"如果 VSA 不触发，用 rule_eval 手塞 task"作为 alternate path

---

## Issue #5 — `elder_wakeup` 天然不产 `severity` → warn 日志噪声（**已在本仓修复**）

**发现日期**：2026-07-03
**报告人**：Jie
**责任仓**：本仓 —— `smart-community/config.yaml.example`

### 现象

跑 U1-U10 期间 MCP log 刷屏：

```
[task-poller] task 125 (cam_elder_bedroom) missing required schema fields: severity
[task-poller] task 124 (cam_elder_bedroom_2) missing required schema fields: severity
```

### 根因

`config.yaml.example` 的 `schema.video_summary_tasks.extensions` 里把 `severity` 声明为 `required: true`。但 `use-cases/elder_wakeup/prompt.md` **故意不让 VLM 输出 SEVERITY 字段**（elder_wakeup 靠 `event=get_up` + `expectedWakeupLocal` 判 late，跟 severity 无关）。schema 层的 required 声明与 use-case-specific 的产出不匹配 → task-poller 的 parser 抽不到 → 每条 elder_wakeup task 都 warn。

### 修复

**已修**：把 `config.yaml.example` schema 里 `severity` 改为 `required: false` + 加注释说明"threshold-based UC 用；time-based UC 不需要"。改动零侵入，行为仍然对：
- 用 severity 判定的 UC（child_safety / high_altitude_safety / parking_safety）依然靠 VLM 输出 SEVERITY 字段
- elder_wakeup 不再触发 warn

### 影响面

- **生产链路**：仅日志噪声，无功能影响
- **集成测试**：不影响任何验收信号

### 状态

- [x] 2026-07-03 已修（config.yaml.example schema 改动）
- [x] 需 MCP 重启生效（内存 schema 快照）

---

## 记录格式约定（后续加 issue 请照这个模板）

每条 issue 包含 9 个字段：
1. **标题**（简短、可搜索）
2. **发现日期 / 报告人 / 上游仓**
3. **复现**（最小可执行命令）
4. **服务端返回**（原始 response，便于跨仓沟通时贴给对方）
5. **根因**（分"确认"和"推测"）
6. **影响面**（分"生产链路"和"集成测试"两个视角）
7. **Workaround**（本仓侧已做的规避）
8. **需要上游修的东西**（沟通时可直接抛出的 1-3 条具体建议）
9. **对我的集成测试的影响 + 状态清单**
