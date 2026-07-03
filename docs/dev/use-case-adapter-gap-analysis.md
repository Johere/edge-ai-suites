# Use Case Adapter — Gap Analysis vs Design 2026.2

**首次分析**: 2026-07-01
**上次更新**: 2026-07-03
**基线**: [smartbuilding-video-design-2026.2.md](../smartbuilding-video-design-2026.2.md) §5 "Use Case Adapter"
**验证 log**: [use-case-adapter-validation.md](./use-case-adapter-validation.md)（HA + Parking 真实端到端）

---

## 0. 2026-07-03 更新一览

上一版（2026-07-01）以来完成的项：

| Gap | 原状态 | 现状态 |
|---|---|---|
| `parse_summary.py` override（Design §5.3 承诺）| ❌ 未实现 | ✅ **已实现**：`task-poller.parseSummary` L194-218，`use_case_dict.<uc>.parse_summary_path` 生效；stdout 返 `{fields, missingRequired}` 覆盖 built-in parser，broken script 自动 fallback |
| `smartbuilding_use_case_register` MCP tool（P2）| ❌ 未实现 | ✅ **已实现**：一次调用完成 schema ALTER + VLM `POST /v1/tasks`（409 auto-PATCH）+ 内存 `useCaseDict` 注入 + `useCaseValidate` 复核。用户指南 [use-case-adapter-gsg.md §10](../use-case-adapter-gsg.md#10-零重启动态注册新-use-case)、手动验证单 [use-case-register-verification.md](./use-case-register-verification.md) |
| use-case-adapter-gsg.md 里 "5 覆盖场景"里混着未实现视频/未部署 monitor | 内部矛盾 | ✅ **已重构**：§0-§8 基线（demo-videos 里真实存在的 4 monitor），§9 扩展验证（未实现 case 集中收纳），§10 零重启注册 |

### 2026-07-03 下午（集成测试跑通后）追加

| 项 | 状态 |
|---|---|
| Phase 2 U1-U10 基线（3 内置 UC + cooldown）| ✅ 全 pass |
| Phase 3 U11+U12 扩展 case（HA/Parking 自定义 UC）| ✅ 4/4 pass（rule_eval 手塞 task 路径；VSA→VLM 完整链路因短视频 loop 问题绕过）|
| Phase 4 §0-§6 零重启注册端到端 | ✅ 全 pass（含 pet_stuck rule_eval 手塞验证：alertMessage 里 zone=sofa 拼接生效）|
| Issue #1 上游 VLM `method` fallback bug（integration-status.md）| 记录，本仓 workaround（显式传 method）|
| Issue #2 段名正则 `[A-Z_]+` 不含数字 → LOCAL_PROMPT 吞 T_MINUS_1_PROMPT | ✅ 修（改 `[A-Z0-9_]+`）|
| Issue #3 `evaluateWithOverride` 无 execFile timeout → override 挂死 rule_eval | ✅ 修（`{ timeout: 10_000 }`）|
| Issue #4 VSA motion 对 5s loop 短视频不触发 | 记录（非 bug；生产用长视频）|
| Issue #5 elder_wakeup 天然不产 severity → warn 噪声 | ✅ 修（config schema severity: required→false）|
| events-endpoint 对 `type: "status"` 返 422（G-P5） | ✅ 修（KNOWN_TYPES 加 status，选项 A 静默吞 200）|

跨模块改动清单（我在 vsa + adapter 集成时改了 MCP owner 领地代码，需 review）见
[integration-status.md §A](./integration-status.md)。

### 2026-07-03 晚（Design §5.2 兑现，Plan §27 落地）

| 项 | 状态 |
|---|---|
| P1-A 默认 evaluator 反推：3 个 UC 从 Python override 迁回 `defaultRuleEvaluator + rules dict` | ✅ 完成 — `defaultRuleEvaluator` 加 `requireEvent` / `requireDirection` / `excludeZones` / `alertMessageExtraField` 4 个 keys；删 `child_safety` / `parking_safety` / `high_altitude_safety` 的 evaluate_rules.py；alertMessage 格式与旧 override 完全一致（`[uc] event: severity — desc (zone=X)`）；U1/U2/U11a/U11b/U12a/U12b 6 条 rule_eval 全 pass |
| P1-B `smartbuilding_use_case_register` 加 `persist: true` 选项 | ✅ 完成 — 用 yaml 库 `parseDocument` + `setIn`/`deleteIn` + `toString` comment-preserving 写回 `config.yaml.example`；`ServerConfig.configPath` 通过 `--config` CLI 参数带入；`UseCaseRegisterResult.steps.config_yaml: "written" \| "removed" \| "skipped"`；写盘失败降级为 warning 不阻断 |
| P2 `smartbuilding_video_summary_task` tool 家族（list / get / delete）| ✅ 完成 — 新 tool 挂在 `use_case_register` 后；`list` 返所有 tasks；`get` 返完整 body 含 4 常量 content；`delete` 处理 builtin 403（返 warning + `status: "builtin_immutable"`）+ 404（`status: "not_found"`） |

**"零代码"承诺兑现进度**（对照 §6 表）：

- ✅ 零 TypeScript 代码
- ✅ 零 curl 手工
- ✅ **零 YAML 手工**（P1-B 兑现；`persist: true` 让磁盘 config 与内存同步，重启不丢）
- ⚠️ 零 prompt 手工（未做，仍需 P3 LLM autogen）
- ✅ **零 Python 手工**（P1-A 兑现；3 个简单 UC 完全靠 rules dict 表达；只有 `elder_wakeup`（时间比较）+ `fridge`（stub invariant）保留 override）

---

## 1. Design §5 要求逐项对照（更新至 2026-07-03）

按设计文档 §5.1 / §5.2 / §5.3 三节的每条声明标注当前实现状态。

### §5.1 Adapter Wrapper

| # | Design 声明 | 现状 | Gap |
|---|-------------|------|-----|
| 1 | `use-cases/<name>/evaluate_rules.py` 用户可选 override | ✅ 已实现（`rule-engine/index.ts:111` `evaluateWithOverride`）| — |
| 2 | `use-cases/<name>/on_task_completed.py` 用户可选 callback | ✅ 已实现（`task-poller.ts:226` `runOnTaskCompleted`）| — |
| 3 | 内置默认 parser（按 schema 字段名 regex 提取）| ✅ [`parseSummaryFields`](../../packages/tools/src/rule-engine/summary-parser.ts) | — |
| 4 | 内置默认 rules（severity ≥ 阈值 + event 排除表）| ✅ [`defaultRuleEvaluator`](../../packages/tools/src/rule-engine/index.ts#L73) | — |
| 5 | `use-cases/README.md` callback override 编写指南 | ⚠️ README.md 简短。规范化开发者手册在 [use-case-adapter.md](../use-case-adapter.md) | 建议将两者互链或合并 |

### §5.2 Register New Use Case

Design 承诺"零代码 3 输入向导"。现状：**tool-level orchestration 已实现，交互式 wizard 未实现**。

| # | Design 声明 | 现状 | Gap |
|---|-------------|------|-----|
| 1 | Step 1: 交互式收集（name / description / event types）| ⚠️ 参数已被 `smartbuilding_use_case_register` 抽象成一次 MCP call；无 CLI wizard 层 | 向导化 UX 未做 |
| 2 | Step 2: 决定 DB schema（默认 or 自定义）| ✅ 通过 `schema_extensions` 参数一次传入；`SchemaManager.applySchema` 幂等 ALTER | — |
| 3 | Step 3: LLM 生成 VIDEO_SUMMARY prompt | ❌ 仍需用户自己写 `prompt.md` | 剩余最大 gap |
| 4 | Step 4: prompt ↔ schema 一致性校验 | ✅ `smartbuilding_use_case_validate`（`register` tool 内部 4th step 自动复核）| — |
| 5 | Step 5: 注册 VLM task | ✅ **已封装** — `use_case_register` 内部 POST /v1/tasks，409 自动 PATCH | — |
| 6 | Step 6: 创建 DB schema（ALTER TABLE）| ✅ SchemaManager 幂等；启动时 auto，运行时 register tool 也可触发 | — |
| 7 | Step 7: 注册 source（RTSP）| ✅ `smartbuilding_monitor_ctl register_source` | — |
| 8 | Step 8: 启动 WorkerService | ✅ 启动即启；`register_source` 之后自动接管 | — |
| 9 | 手动 CLI 模式的 `smartbuilding_db_manager action=register_use_case` | ❌ 该 tool **不存在**；已被 `smartbuilding_use_case_register` 替代 | Design 需 update |
| 10 | 手动 CLI 模式的 `smartbuilding_video_summary_task action=autogen` | ❌ 该 tool **不存在** | LLM autogen 未做，用户手写 prompt.md |

### §5.3 Post-processing Callback

| # | Design 声明 | 现状 | Gap |
|---|-------------|------|-----|
| 1 | 内置默认 parser（含 required field 校验）| ✅ | — |
| 2 | 内置默认 rules（含 cooldownSec）| ✅（cooldownSeconds 由 override / 内置 evaluator 都尊重；`task-poller.ts:145`）| ⚠️ 命名 `cooldownSec` vs 实现 `cooldownSeconds`，含义一致 |
| 3 | Python callback: `parse_summary.py` | ✅ **已实现**（`task-poller.parseSummary` L194-218；`use_case_dict.<uc>.parse_summary_path`）| — |
| 4 | Python callback: `evaluate_rules.py` | ✅（含 fallback 到 `defaultRuleEvaluator`）| — |
| 5 | Python callback: `on_task_completed.py` | ✅ 从 Phase 10 G2 完成 | — |
| 6 | Cooldown check → insert alert → MCP 广播 | ✅（`db.latestAlertWithin` SQL datetime 减法实现）| — |
| 7 | Rule 层 MCP broadcast（resources/updated）| ⚠️ 已有 alert 表订阅通道，但 `rule_eval` tool 触发 create_alert 是否自动 broadcast **仍未 E2E 测**  | 需一次 subscribe → rule_eval → 收到通知的端到端 |

### §5 结构性 gap

| # | 观察 | 影响 |
|---|------|------|
| S1 | `use-cases/<name>/prompt.md` 是设计中未提及的产物 — 已成为 use case 的 3-tuple 之一（config yaml + evaluate_rules.py + prompt.md）| 设计文档需 update |
| S2 | 设计声称"内置默认 rules 处理绝大多数场景"—— **✅ 已兑现**（2026-07-03 晚）：`defaultRuleEvaluator` 扩展了 `requireEvent` / `requireDirection` / `excludeZones` / `alertMessageExtraField` 4 个 keys，覆盖 child/parking/high_altitude 3 个 UC；仅 `elder_wakeup`（时间比较）+ `fridge`（stub）仍保留 Python override |
| S3 | 设计未提及 `payload.rules.<custom>` 机制 — 实现里 `rules` 是任意 YAML dict，通过 `RuleContext` 传给 override | 应写进设计，因为这是通用扩展点 |
| S4 | 设计未提及"运行时可变" — 但 `use_case_register` 让 `useCaseDict` 变成 mutable | 设计的 lifecycle 图需要补一条"动态注册"通道 |

---

## 2. 完成度打分（2026-07-03 晚，Plan §27 落地后）

| 维度 | 完成度 | 变化 | 备注 |
|------|--------|------|------|
| **Adapter 核心**（parser / rules / override 机制）| **100%** | 持平 | parse_summary override 已上线；三种 callback 全通 |
| **Use case 一次搭建**（真实 use case 端到端跑通）| **95%** | 90% → 95% | 5 个 UC 都跑通 + 3 个已简化到零 Python；wizard 自动化仍缺 |
| **零代码向导**（Design §5.2）| **80%** | 60% → 80% | tool-level 一站式 + persist 写回 + default evaluator 覆盖 3 UC；仅缺 LLM prompt autogen + CLI wizard |
| **动态注册**（Design 未直接声明，但零重启是新需求）| **100%** | 90% → 100% | `persist: true` 补齐，重启后 in-memory-only use case 不再丢失 |
| **文档 / 手册** | **95%** | 持平 | gsg 重构完成；缺一次 design doc 名字对齐 |
| **测试覆盖** | **85%** | 持平 | 有 rule-eval unit test + 2 UC e2e；`use_case_register` + `video_summary_task` 缺自动化测试 |

**综合评估**：Design §5.1 / §5.2 / §5.3 **全部兑现**（除 P3 LLM prompt autogen + CLI wizard 之外）。"零代码"承诺 5 个维度中 **4 个完全达成**，仅"零 prompt 手工"待 P3 阶段做。

---

## 3. Design 与实现之间的命名/API 对齐 gap

Design 里出现的 tool 名字与代码里的对齐情况：

| Design 提到的 tool | 代码里的对应 | 状态 |
|-------------------|-------------|-------|
| `smartbuilding_daily_report` | `smartbuilding_generate_report` | Design 名字错，代码正确 |
| `smartbuilding_db_manager action=register_use_case` | 被 `smartbuilding_use_case_register` 替代 | Design 需 update：删掉 `db_manager register_use_case` |
| `smartbuilding_video_summary_task action=autogen` | 未实现（仍是 curl POST /v1/tasks 由 register tool 内部完成，autogen 是 LLM 帮忙写 prompt）| 未实现 |
| `parseScript` (parse_summary.py) | ✅ 已实现 | Design 说法过时，实际叫 `parse_summary_path` |
| `smartbuilding_monitor_ctl unregister` | ✅ 存在 | — |
| `smartbuilding_use_case_validate` 支持 dynamic task | ✅ 支持（`useCaseValidate` 里 `GET /v1/tasks/<name>`，dynamic 和 builtin 一视同仁）| — |
| `smartbuilding_use_case_register`（本次新增）| ✅ 新增 | 需写进 Design |

**建议**：一次 Design doc 修订 → 名字对齐现实（10 分钟工作量），把上表 4 处"Design 说法过时"改掉。

---

## 4. 当前 MCP tool 全景（11 个）

对照 Design § "MCP tools" 章节，实际现存：

```
smartbuilding_alert_query
smartbuilding_plan_ctl
smartbuilding_scene_query
smartbuilding_generate_report
smartbuilding_monitor_ctl
smartbuilding_monitors_compose
smartbuilding_video_db
smartbuilding_use_case_validate
smartbuilding_use_case_register    ← 2026-07-03 新增
smartbuilding_video_summary_task   ← 2026-07-03 晚新增
smartbuilding_rule_eval
smartbuilding_state_query
```

（共 12 个 tool）

Design 里额外声称、但**代码里没有**的：

- `smartbuilding_daily_report`（名字错，实际 `smartbuilding_generate_report`）
- `smartbuilding_db_manager action=register_use_case`（被 `use_case_register` 替代）
- `smartbuilding_video_summary_task action=autogen`（未实现；`register` 已被 `use_case_register` 内嵌完成；`list`/`get`/`delete` **✅ 已实现**）

---

## 5. 优先级排序（给 owner 参考）

按当前状态刷新（原 P1/P2 大部分已完成）：

| 优先级 | Gap | 工作量估算 | 价值 |
|--------|-----|-----------|------|
| ~~P0~~ | ~~修 use_case_validate 支持 dynamic task~~ | ~~半天~~ | ✅ 已完成 |
| ~~P1~~ | ~~默认 evaluator 反推：child_safety / parking_safety / high_altitude_safety 迁回 default~~ | ~~1-2 天~~ | ✅ 已完成（Plan §27 Step 1）|
| ~~P1~~ | ~~`use_case_register` 加 `persist: true` — yaml Document API 写回~~ | ~~1 天~~ | ✅ 已完成（Plan §27 Step 2）|
| ~~P2~~ | ~~`smartbuilding_use_case_register`~~ | ~~2-3 天~~ | ✅ 已完成 |
| ~~P2~~ | ~~`parse_summary.py` override~~ | ~~1 天~~ | ✅ 已完成 |
| ~~P2~~ | ~~`smartbuilding_video_summary_task` MCP tool 家族：`list` / `get` / `delete`~~ | ~~半天~~ | ✅ 已完成（Plan §27 Step 3）|
| P2 | 一次 Design doc 修订：删过时 API 声明、加 `use_case_register` / `video_summary_task` / `parse_summary_path` 章节、加 S1/S3/S4 结构性说明 | 半天 | 减少 design vs 实现的漂移误导 |
| P3 | Prompt lint tool（静态检 `A|B|C` / code fence）| 半天 | 复用 use-case-adapter §Prompt writing conventions |
| P3 | Prompt LLM autogen（`smartbuilding_use_case_register` 传 `event_types + description` → 调 vLLM 帮忙生成 prompt.md 骨架，再 human-in-the-loop refine）| 3-5 天 | 兑现 Design §5.2 Step 3 |
| P3 | `smartbuilding_use_case_wizard` MCP tool（agent 交互式，串起 §5.2 全 8 步）| 1 周 | 完全兑现 §5.2 图 5-1 |
| P3 | `rule_eval create_alert=true` MCP resources/updated broadcast 端到端测试 | 半天 | 消除 §5.3 #7 的 "未测" |

---

## 6. 验证结论：Adapter 框架是否达到 Design §1.3 "零代码用例创建"？

**当前状态（2026-07-03 晚，Plan §27 落地后）**：

- ✅ **零 TypeScript 代码**：完全达成 —— 5 个 UC（含 2 个后加的自定义 UC）从添加到跑通都不需要改 TS
- ✅ **零 curl 手工**：完全达成 —— `use_case_register` 一次调用完成 schema + VLM task + config 注入
- ✅ **零 YAML 手工**：**完全达成**（Plan §27 Step 2 兑现）—— `use_case_register` `persist: true` 用 yaml Document API 写回 config.yaml.example，注释和字段顺序保留；重启后 in-memory use case 不再丢
- ⚠️ **零 prompt 手工**：**未达成**。用户仍需自己写 `prompt.md`（Design §5.2 Step 3 的 LLM autogen 未实现，P3 阶段做）
- ✅ **零 Python 手工**：**基本达成**（Plan §27 Step 1 兑现）—— `defaultRuleEvaluator` 已覆盖 3/5 UC（child/parking/high_altitude 完全用 rules dict）；仅 `elder_wakeup`（时间比较必须 Python）+ `fridge`（stub invariant）保留 override，符合 Design §5.2 "极少数需要 override" 承诺

**结论**：Design §1.3 "零代码"的 5 个维度里 **4 个完全达成**，仅"零 prompt 手工"待 P3 LLM autogen 完成。工程侧的所有核心机制都在位。

---

## 参考

- [use-case-adapter-validation.md](./use-case-adapter-validation.md) — 真实 UC 验证 log（HA + Parking）
- [use-case-register-verification.md](./use-case-register-verification.md) — 2026-07-03 新增的 `use_case_register` 手动验证单
- [use-case-adapter-gsg.md](../use-case-adapter-gsg.md) — 用户指南（基线 U1-U10 + 扩展 §9 + 零重启 §10）
- [smartbuilding-video-design-2026.2.md §5](../smartbuilding-video-design-2026.2.md#5-use-case-adapter) — 设计基线
- [use-case-adapter.md](../use-case-adapter.md) — 开发者手册
