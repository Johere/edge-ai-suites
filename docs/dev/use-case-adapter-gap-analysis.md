# Use Case Adapter — 设计符合性报告

**设计基线**: [smartbuilding-video-design-2026.2.md](../smartbuilding-video-design-2026.2.md) §5 "Use Case Adapter"
**验证参考**:
- [use-case-adapter-validation.md](./use-case-adapter-validation.md)
- [use-case-register-verification.md](./use-case-register-verification.md)
- [use-case-adapter-gsg.md](../use-case-adapter-gsg.md)
- [use-case-adapter.md](../use-case-adapter.md)

---

## Executive Summary

- **Design §5.1 Implementation Status**: Adapter wrapper 核心能力已完整具备，包括默认 parser/rules 流程和可选 Python 回调（`evaluate_rules.py`、`parse_summary.py`、`on_task_completed.py`）。
- **Design §5.2 Implementation Status**: 用例注册全流程已由 MCP 工具编排实现（`register`/`unregister`/`generate_prompt` 及 task 管理）。独立交互式 wizard 形态仍属于待补强项。
- **Design §5.3 Implementation Status**: 后处理主链路（parser/rules/cooldown/alert 写入）功能完整；其中一条 rule_eval 触发广播链路仍需明确 E2E 证据。
- **Remaining Gaps**: 主要剩余项为设计文档对齐、prompt lint/wizard 产品化，以及自动化与端到端验证覆盖扩展。

## 1. Design Compliance Matrix

### §5.1 Adapter Wrapper

| # | 设计要求 | 状态 | 当前实现 |
|---|---|---|---|
| 1 | `use-cases/<name>/evaluate_rules.py` 可选 override | Fully Implemented | 通过 rule engine 中的 `evaluateWithOverride` 支持。
| 2 | `use-cases/<name>/on_task_completed.py` 可选 callback | Fully Implemented | 通过任务完成回调（`runOnTaskCompleted`）支持。
| 3 | 内置 parser（按 schema 字段抽取） | Fully Implemented | `parseSummaryFields` 提供默认字段抽取。
| 4 | 内置默认 rules（阈值 + 排除） | Fully Implemented | `defaultRuleEvaluator` 支持基于 rules 字典判定。
| 5 | `use-cases/README.md` callback 编写指南 | Partially Implemented | 规范说明主要在 [use-case-adapter.md](../use-case-adapter.md)，`use-cases/README.md` 相对精简。

### §5.2 Register New Use Case

| # | 设计要求 | 状态 | 当前实现 |
|---|---|---|---|
| 1 | 向导收集输入（`name/description/event_types`） | Partially Implemented | 输入契约已通过 `smartbuilding_use_case_register` 实现；独立 wizard 交互层仍待补齐。
| 2 | schema 决策（默认/扩展） | Fully Implemented | `schema_extensions` + `SchemaManager.applySchema` 支持幂等 schema 更新。
| 3 | LLM 生成 `VIDEO_SUMMARY` prompt | Fully Implemented | `smartbuilding_use_case_register action=generate_prompt` 可基于语义输入生成 `LOCAL_PROMPT` 骨架。
| 4 | prompt 与 schema 一致性校验 | Fully Implemented | `smartbuilding_use_case_validate` 提供一致性校验，注册流程可联动复核。
| 5 | 注册 VLM task | Fully Implemented | 注册流程包含 `POST /v1/tasks`，并处理冲突（`409`）场景。
| 6 | 创建 DB schema（`ALTER TABLE`） | Fully Implemented | 启动时与运行时路径均支持幂等 schema 应用。
| 7 | 注册 source（RTSP） | Fully Implemented | `smartbuilding_monitor_ctl register_source` 可用。
| 8 | 启动/接管 WorkerService | Fully Implemented | source 注册后处理链路可自动接管。
| 9 | `smartbuilding_db_manager action=register_use_case` | Not Applicable | 当前实现已统一为 `smartbuilding_use_case_register`。
| 10 | `smartbuilding_video_summary_task action=autogen` | Partially Implemented | prompt 自动生成能力存在于 `smartbuilding_use_case_register action=generate_prompt`，仅命名与设计文本不同。

### §5.3 Post-processing Callback

| # | 设计要求 | 状态 | 当前实现 |
|---|---|---|---|
| 1 | 内置 parser + required field 校验 | Fully Implemented | 默认 parser 支持必填字段校验。
| 2 | 内置 rules + cooldown | Fully Implemented | evaluator 与 poller 流程均遵守 cooldown（`cooldownSeconds`）。
| 3 | Python callback: `parse_summary.py` | Fully Implemented | 支持 `parse_summary_path` override，并有 fallback。
| 4 | Python callback: `evaluate_rules.py` | Fully Implemented | 支持 override，且可回落默认 evaluator。
| 5 | Python callback: `on_task_completed.py` | Fully Implemented | 任务完成回调链路可用。
| 6 | cooldown check -> insert alert -> MCP 流程 | Fully Implemented | 通过 latest-alert 时间窗判定并写入告警记录。
| 7 | rule 层 MCP broadcast 验证 | Partially Implemented | 告警订阅通道存在，但一条 subscribe -> rule_eval -> notify 链路仍需明确 E2E 证明。

## 2. Current Architecture Notes

- `prompt.md` 在当前实现中已是 use case 核心工件，与配置和规则逻辑并列构成关键输入。
- `rules` 字典机制是通用扩展面，可在运行时上下文中传递，供默认 evaluator 与 override 共同消费。
- 运行时注册是可变模型：`useCaseDict` 可经由 MCP 注册流程动态更新，不受仅启动期静态加载限制。
- 动态 task 在校验链路中可用：`use_case_validate` 对 dynamic task 与 builtin task 均可通过 task API 进行解析校验。
- 默认 evaluator 覆盖常见条件较完整（`requireEvent`、`requireDirection`、`excludeZones`、`alertMessageExtraField`），复杂逻辑可选择保留 Python override。
- `parse_summary_path` 提供 parser override 灵活性，并在脚本不可执行或结果异常时回落到内置 parser。

## 3. Completion Assessment

| Area | Status | Notes |
|---|---|---|
| Adapter Core（parser/rules/override 生命周期） | Strong | 默认与回调两种模式均具备稳定能力。
| Use Case Setup Flow | Strong | 端到端搭建流程可由 MCP 工具编排完成。
| Zero-Code Workflow | Mostly Supported | 工具层已实现一站式流程；独立交互式 wizard 仍是待补产品特性。
| Dynamic Runtime Registration | Supported | 已支持运行时注册与可选持久化写回。
| Documentation Alignment | Partially Supported | 功能文档可用；设计基线中的命名与结构仍需进一步对齐。
| Automated Test Coverage | Partial | 已覆盖规则判定与部分 E2E；注册/task/prompt 生成自动化覆盖仍可扩展。

## 4. API & Tool Alignment

| Design Name | Current Implementation | Notes |
|---|---|---|
| `smartbuilding_daily_report` | `smartbuilding_generate_report` | 代码中的当前工具名为 `smartbuilding_generate_report`。
| `smartbuilding_db_manager action=register_use_case` | `smartbuilding_use_case_register action=register` | 注册能力已收敛至 use case register 工具。
| `smartbuilding_video_summary_task action=autogen` | `smartbuilding_use_case_register action=generate_prompt` | prompt 自动生成能力在 register 工具 action 下提供。
| `smartbuilding_video_summary_task action=list/get/delete` | `smartbuilding_video_summary_task action=list/get/delete` | task 清单与生命周期操作能力可用。
| `parseScript` 命名 | `parse_summary_path` | parser override 的实现键名为 `parse_summary_path`。
| `smartbuilding_use_case_validate` dynamic 行为 | `smartbuilding_use_case_validate` | 当前实现支持基于 task API 的 dynamic task 校验。

## 5. MCP Tool Inventory

### Current Tool Set

以 `packages/mcp-server/src/tools.ts` 的 `registerTool(...)` 为准，共 **12** 个：

```text
smartbuilding_alert_query
smartbuilding_plan_ctl
smartbuilding_scene_query
smartbuilding_generate_report
smartbuilding_monitor_ctl
smartbuilding_monitors_compose
smartbuilding_video_db
smartbuilding_use_case_validate
smartbuilding_use_case_register
smartbuilding_prompt_lint
smartbuilding_video_summary_task
smartbuilding_rule_eval
```

> 变更记录：
> - `smartbuilding_state_query` 已移除（`monitor_state` 存储回退，见下方 §6）。
> - **待 review（jiaojiao 反馈）**：`smartbuilding_prompt_lint` / `smartbuilding_video_summary_task` /
>   `smartbuilding_use_case_register action=generate_prompt` 建议迁移为面向 multilevel-video-understanding
>   的 **skill**（agent + router 生成），而非 MCP tool；`smartbuilding_rule_eval` 保留为调试工具。

### Design Names Requiring Alignment

- `smartbuilding_daily_report` -> 建议改为 `smartbuilding_generate_report`。
- `smartbuilding_db_manager action=register_use_case` -> 建议改为 `smartbuilding_use_case_register action=register`。
- `smartbuilding_video_summary_task action=autogen` -> 建议改为 `smartbuilding_use_case_register action=generate_prompt`。

### Recommended Documentation Updates

- 将设计文档中的工具命名与当前 MCP 接口命名统一。
- 增补 `smartbuilding_use_case_register` action 说明（`register` / `unregister` / `generate_prompt`）。
- 增补 `smartbuilding_video_summary_task` action 说明（`list` / `get` / `delete`）。
- 明确 `parse_summary_path` 为 parser override 合同字段。

## 6. Outstanding Gaps

> 每项按 **问题 / 原代码位置 / 评审意见含义 / 架构建议** 四段展开。file:line 均指 smart-community 本仓。
> 面向评审的一页决策清单见 [adapter-review-checklist.md](./adapter-review-checklist.md)。

### 6.1 Design document alignment（设计文档命名对齐）

- **问题**：设计文档 `smartbuilding-video-design-2026.2.md` 用的工具名与实际 `tools.ts` 注册名不一致，
  照设计文档调工具会找不到。
- **原代码**：设计旧名 `smartbuilding_daily_report`（design:135/549/1021）、
  `smartbuilding_db_manager action=register_use_case`（design:356）、
  `smartbuilding_video_summary_task action=autogen`（design:359/789）；实际 `tools.ts` 为
  `smartbuilding_generate_report` / `smartbuilding_use_case_register action=register` /
  `... action=generate_prompt`。
- **评审意见**：与 review [8]「新增 tools 待 review」相关——命名不统一，review 对不上号。
- **架构建议**：**以代码为 single source of truth**，回填设计文档（代码已实现+已测，反改代码风险大）。纯文档、零风险。

### 6.2 Prompt tools（autogen / lint / video-summary-task）的层归属

- **问题**：`prompt-autogen`（用 LLM 生成 prompt）、`prompt-lint`（静态校验）、`video-summary-task`
  （VLM `/v1/tasks` 增删查）目前都是 MCP tool。autogen 把「调 LLM + 选模型」放进了确定性工具层。
- **原代码**：[prompt-autogen.ts](../../packages/tools/src/prompt-autogen.ts)（`generatePrompt` + `fetch(${vlmUrl}/chat/completions)`）、
  [prompt-lint.ts](../../packages/tools/src/prompt-lint.ts)（6 类静态检查）、
  [video-summary-task.ts](../../packages/tools/src/video-summary-task.ts)；注册在
  [tools.ts:407](../../packages/mcp-server/src/tools.ts#L407)（prompt_lint）/
  [:448](../../packages/mcp-server/src/tools.ts#L448)（video_summary_task）/
  [:321](../../packages/mcp-server/src/tools.ts#L321)（use_case_register 的 `generate_prompt` action）。
- **评审意见**：「能用 skill 解决尽量用 skill，最大化 agent harness + router」。含义：autogen 是创造性
  LLM 生成，放 skill 里可让 agent 推理 + router 自动选模型/回退；放 MCP tool 等于在确定性层重造 LLM 客户端。
- **架构建议（含修正）**：
  - 方向认同：本仓 **design §6 本就有 Skills Layer**（`smartbuilding-toolkit` / `video-understanding`，
    design:73/94；design:513 的 `tasks.mjs --autogen` 也在 skill 脚本里）。但 design §5.2 又把 autogen 写成
    tool（design:789）——**design 自身矛盾，评审意见等于替 design 消歧到 skill 层**。
  - **但归属要澄清**：smart-community **当前没有实现 skills/ 层**（真正的 skill 在 agent-ai.smarthome/
    `openclaw-skills/`）。所以本仓 in-scope 的动作**只有「删不删 autogen/lint tool」**；skill 本体在哪落地、
    谁写，是**跨仓**的事，不属于 smart-community 的编码任务。
  - **反驳（保留理由）**：本仓定位是 framework-agnostic（CLAUDE.md：「agents can autonomously create
    use cases without modifying core components」）。MCP-native 的 autogen 让**任何** MCP client 都能自助生成，
    不依赖消费方有 OpenClaw skill/router；且它调的是本仓**已依赖**的 VLM，不是新依赖类别。直接删会让本仓从
    「自足」退成「必须配特定 agent 框架才能生成」。
  - **推荐切法**：MCP 保留确定性原语（`use_case_register action=register` = POST /v1/tasks 落地）+ 可保留一个
    **薄的、模型可配**的 autogen；lint 降为纯函数（不注册成 tool）；真正「多轮/需 router 选型」的创造性编排交给
    skill 层。**锁步**：skill 落地后再删 tool，别在替代品到位前删。

### 6.3 `on_task_completed_path` / `parse_summary_path` / `rules`

- **问题**：`UseCaseConfig` 有 3 个 per-UC 字段。`rules` 是声明式规则配置（在用）；两个 `*_path` 是 Python
  override 钩子（当前零 UC 配置）。
- **原代码**：定义 [config.ts:48/55/62](../../packages/mcp-server/src/config.ts#L48)；消费
  [task-poller.ts:104-110](../../packages/mcp-server/src/video-worker/task-poller.ts#L104)（parse_summary）、
  [:170-172](../../packages/mcp-server/src/video-worker/task-poller.ts#L170)（on_task_completed）、
  [rule-engine/index.ts:116](../../packages/tools/src/rule-engine/index.ts#L116)（读 `payload.rules`）。
- **评审意见**：三者 out of design scope，待议。含义：不该在 MCP 配置层预埋 per-UC Python hook，增加 MCP 与
  use-case 实现的耦合面。
- **架构建议（拆开谈）**：
  - **`rules` 保留**：它是规则 DSL（severityThreshold/cooldownSeconds/requireEvent…），`defaultRuleEvaluator`
    直接消费，删了默认三 case 的规则全丢。in-scope。
  - **`parse_summary_path` + `on_task_completed_path` 建议移除**（连带 task-poller 的 `parseSummary` override
    分支 + `runOnTaskCompleted`）。理由：①零使用（YAGNI）；②把「任意 Python 子进程」引进 MCP 主链路是稳定性/
    攻击面（虽已加 10s timeout）；③**更优雅的替代恰是 subscription**——告警后处理副作用应由订阅方收到
    `resources/updated` 后自己做，而非 MCP 里 fork Python，这与评审的 subscription 方向一致。

### 6.4 Alerts cooldown 归属

- **问题**：潜在两层 cooldown，语义不同，易「双重抑制」或「都不抑制」。
- **原代码**：唯一实现在
  [task-poller.ts:145-153](../../packages/mcp-server/src/video-worker/task-poller.ts#L145)（`cooldownSec` 取自
  `rules.cooldownSeconds`，`db.latestAlertWithin` 命中就不写行）；通知侧
  [task-poller.ts:166 onAlert](../../packages/mcp-server/src/video-worker/task-poller.ts#L166) →
  [index.ts:111](../../packages/mcp-server/src/index.ts#L111) 对**每条** alert broadcast；
  [mcp-subscriber-registry.ts](../../packages/mcp-server/src/mcp-subscriber-registry.ts) **无去重**。
- **评审意见**：「cooldown 已在 subscription 阶段做，UC 后处理可不管」。**但实测 subscription 侧无去重代码**
  ——要么在插件侧、要么还没合入本仓。
- **架构建议**：**单一职责——cooldown 只该有一层**，放哪层取决于抑制对象：抑制 **DB 行**（现状，alerts 变
  「已去重事件」丢审计）还是抑制 **用户可见通知**（alerts 全量审计、用户不被刷屏，产品语义通常要这个）。
  **顺序不能反**：现在 subscription 无去重，先删 task-poller 会变 0 去重。推荐：①定 alerts 表语义（建议
  全量审计）→②通知层落地「每 (monitor,useCase) N 秒最多推一次」→③再移除 task-poller 行级 cooldown。

### 6.5 已回退（本轮，记录用）

- **问题（已解决）**：`type:"status"` webhook + `monitor_state` 存储是之前误加，本轮已回退。
- **原代码**：[events-endpoint.ts](../../packages/mcp-server/src/events-endpoint.ts)（只认 motion/static/recording）、
  [rtsp_monitor.py `_emit_status`](../../videostream-analytics/stream_monitor/rtsp_monitor.py)（no-op）、
  [database.ts](../../packages/db/src/database.ts)（无 monitor_state，保留 latestAlertWithin/queryTasks）。
- **评审意见**：本身即响应评审做的回退（3 类 clip 事件才对）。
- **架构建议**：已完成。未来「掉线感知」走 VSA `GET /sources/{id}/status` 拉取或独立通道，别混进 clip 事件 webhook。

### 6.6 Additional automation tests

- **问题**：`use_case_register` 的 register/unregister 全循环、`video_summary_task`、`generate_prompt` 契约
  缺自动化覆盖——而这些是改动最频繁的 adapter 核心。
- **原代码**：[tests/dev-mcp-server/](../../tests/dev-mcp-server/) 有 `test_db/schema/tools_mcp/events_webhook/
  rule_engine/use_cases/prompt_lint`；**无** `test_use_case_register`、**无** video_summary_task 测试。
- **架构建议**：加 `test_use_case_register.py`：`register → validate → unregister` 全循环 + `persist=true` 的
  yaml 写回/重启读回 + 幂等（重复 register）+ 负例（非法名 / 撞 builtin task / 缺 overwrite）。若 6.2 把 autogen
  迁 skill，`generate_prompt` 契约测试随之移到 skill 侧。

### 6.7 Broadcast E2E verification

- **问题**：`subscribe → alert → notifications/resources/updated` 这条 subscription 核心链无 e2e 测试。
- **原代码**：[mcp-subscriber-registry.ts](../../packages/mcp-server/src/mcp-subscriber-registry.ts) +
  [resources.ts](../../packages/mcp-server/src/resources.ts) +
  [index.ts:111 onAlert](../../packages/mcp-server/src/index.ts#L111)；测试里只有
  `tests/framework-adapter-sdk/` 的 mock，无真实 subscribe→notify e2e。
- **架构建议**：加 e2e——起 MCP(http) → 客户端 `resources/subscribe` monitor alerts → 触发 alert（rule_eval
  或手塞）→ 断言收到 `resources/updated`。与 6.4 强耦合：若通知层加 cooldown，此 e2e 要覆盖「重复 alert 只推一次」。

## 7. Verification Summary

Current Assessment:
- Zero TypeScript Changes: Supported
- Zero Manual API Registration: Supported
- Zero Manual YAML Editing: Supported
- Prompt Generation Assisted by LLM: Supported
- Prompt Static Lint Gate: Supported
- Python Override Optional for Advanced Logic: Supported

Conclusion:
The adapter framework satisfies the functional requirements defined in Design §5, with remaining work focused on documentation alignment, productization, and additional automated validation.

## References

- [use-case-adapter-validation.md](./use-case-adapter-validation.md)
- [use-case-register-verification.md](./use-case-register-verification.md)
- [use-case-adapter-gsg.md](../use-case-adapter-gsg.md)
- [smartbuilding-video-design-2026.2.md §5](../smartbuilding-video-design-2026.2.md#5-use-case-adapter)
- [use-case-adapter.md](../use-case-adapter.md)
