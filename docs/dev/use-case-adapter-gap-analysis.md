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
smartbuilding_video_summary_task
smartbuilding_rule_eval
smartbuilding_state_query
```

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

- **Design document alignment**: 对齐设计文档中的过时命名与结构假设。
- **Prompt lint tool**: 将 prompt 预检规则抽为独立 MCP 工具。
- **Wizard UX**: 提供与 Design §5.2 流程对应的交互式向导能力。
- **Additional automation tests**: 扩展 register/unregister、task 管理、prompt 生成契约相关自动化覆盖。
- **Broadcast E2E verification**: 增加 subscribe -> rule_eval -> notification 的显式 E2E 验证与回归保障。

## 7. Verification Summary

Current Assessment:
- Zero TypeScript Changes: Supported
- Zero Manual API Registration: Supported
- Zero Manual YAML Editing: Supported
- Prompt Generation Assisted by LLM: Supported
- Python Override Optional for Advanced Logic: Supported

Conclusion:
The adapter framework satisfies the functional requirements defined in Design §5, with remaining work focused on documentation alignment, productization, and additional automated validation.

## References

- [use-case-adapter-validation.md](./use-case-adapter-validation.md)
- [use-case-register-verification.md](./use-case-register-verification.md)
- [use-case-adapter-gsg.md](../use-case-adapter-gsg.md)
- [smartbuilding-video-design-2026.2.md §5](../smartbuilding-video-design-2026.2.md#5-use-case-adapter)
- [use-case-adapter.md](../use-case-adapter.md)
