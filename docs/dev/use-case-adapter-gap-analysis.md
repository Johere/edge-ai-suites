# Use Case Adapter — Gap Analysis vs Design 2026.2

**日期**: 2026-07-01
**基线**: [smartbuilding-video-design-2026.2.md](../smartbuilding-video-design-2026.2.md) §5 "Use Case Adapter"
**输入**: 两次真实 use case 验证 (high_altitude_safety, parking_safety) — 见
[use-case-adapter-validation.md](./use-case-adapter-validation.md)

---

## 1. Design §5 要求逐项对照

按设计文档 §5.1 / §5.2 / §5.3 三节的**每条声明**，标注当前实现状态。

### §5.1 Adapter Wrapper

| # | Design 声明 | 现状 | Gap |
|---|-------------|------|-----|
| 1 | `use-cases/<name>/evaluate_rules.py` 用户可选 override | ✅ 已实现 (rule-eval.ts 通过 execFile 调用) | — |
| 2 | `use-cases/<name>/on_task_completed.py` 用户可选 callback | ✅ 已实现 (workerService.onTaskCompleted 钩子) | — |
| 3 | 内置默认 parser (按 schema 字段名 regex 提取) | ✅ [parseSummaryFields](../../packages/rule-engine/src/summary-parser.ts) | — |
| 4 | 内置默认 rules (severity ≥ 阈值 + event 排除表) | ✅ [defaultRuleEvaluator](../../packages/rule-engine/src/index.ts) | — |
| 5 | `use-cases/README.md` callback override 编写指南 | ⚠️ 存在 README.md，但内容较简。规范化的开发者手册在 [docs/use-case-adapter.md](../use-case-adapter.md) | 建议将两者互链或合并 |

### §5.2 Register New Use Case — "零代码 3 输入向导"

| # | Design 声明 | 现状 | Gap |
|---|-------------|------|-----|
| 1 | Step 1: 交互式收集 (name / description / event types) | ❌ **未实现向导** | 需要 CLI/agent wizard |
| 2 | Step 2: 决定 DB schema (默认 or 自定义) | ⚠️ 半手工 (改 config.yaml.example schema.extensions) | 无向导 |
| 3 | Step 3: LLM 生成 VIDEO_SUMMARY prompt | ❌ **未实现** (只支持 `mode=full`/`autogen` 的 VLM 服务 API，MCP 侧无 tool 触发) | Blocker for 向导 |
| 4 | Step 4: prompt ↔ schema 一致性校验 | ✅ `smartbuilding_use_case_validate` (但对 dynamic task 有 gap，见下) | 部分 |
| 5 | Step 5: 注册 VLM task | ⚠️ **手工** curl POST /v1/tasks (见 vlm-integration-gsg.md) | 无 MCP tool 封装 |
| 6 | Step 6: 创建 DB schema (ALTER TABLE) | ✅ SchemaManager 启动时自动 diff+ALTER | — |
| 7 | Step 7: 注册 source (RTSP) | ✅ `smartbuilding_monitor_ctl register_source` | — |
| 8 | Step 8: 启动 WorkerService | ✅ 启动即启 | — |
| 9 | 手动 CLI 模式的 `smartbuilding_db_manager action=register_use_case` | ❌ 该 tool **不存在**；`db-manager.ts` 只支持 raw query | Design 的 API 与实现不对齐 |
| 10 | 手动 CLI 模式的 `smartbuilding_video_summary_task action=autogen` | ❌ 该 tool **不存在** | Design vs 实现 |

### §5.3 Post-processing Callback

| # | Design 声明 | 现状 | Gap |
|---|-------------|------|-----|
| 1 | 内置默认 parser (含 required field 校验) | ✅ | — |
| 2 | 内置默认 rules (含 cooldownSec) | ✅ (cooldownSeconds 由 override 声明；框架不强制) | ⚠️ 命名 `cooldownSec` vs 实现 `cooldownSeconds`，含义一致 |
| 3 | Python callback: `parse_summary.py` | ❌ **未实现**（当前只支持 rules override，不支持 parser override）| **Gap G1** |
| 4 | Python callback: `evaluate_rules.py` | ✅ (含 fallback 到 defaultRuleEvaluator) | — |
| 5 | Python callback: `on_task_completed.py` | ✅ 从 Phase 10 G2 完成 | — |
| 6 | Cooldown check → insert alert → MCP 广播 | ✅ (SQL datetime 减法实现) | — |
| 7 | Rule 层 MCP broadcast (resources/updated) | ⚠️ 已有 alert 表订阅通道，但 rule-eval tool 触发的 alert 是否自动 broadcast **未测**  | 需 E2E |

### §5 结构性 gap

| # | 观察 | 影响 |
|---|------|------|
| S1 | `use-cases/<name>/prompt.md` 是设计中**未提及**的产物 — 但实现里已成为 use case 的 3-tuple 之一（config yaml + evaluate_rules.py + prompt.md） | 设计需要 update |
| S2 | 设计声称"内置默认 rules 处理绝大多数场景，仅极少数需要 override" — 但当前 5 个已实现 use case **全部**都写了 override | 说明"默认"不够；应把 severity 阈值 + eventDenyList 逻辑做进 defaultRuleEvaluator 而不是每个 UC 复制 |
| S3 | 设计未提及 `payload.rules.<custom>` 机制 — 实现里 `rules` 是任意 YAML dict，通过 RuleContext 传给 override | 应写进设计，因为这是通用扩展点 |

---

## 2. 完成度打分

| 维度 | 完成度 | 备注 |
|------|--------|------|
| **Adapter 核心** (parser / rules / override 机制) | **80%** | 唯一缺 parse_summary override，其它齐全 |
| **Use case 一次搭建** (真实 use case 端到端跑通) | **90%** | 5 个 UC 都跑通；差 wizard/agentic 自动化 |
| **零代码向导** (Design §5.2 承诺) | **10%** | 只有 SchemaManager 自动 ALTER + monitor_ctl 是零代码；VLM prompt 生成 + 注册均需手工 |
| **文档 / 手册** | **90%** | use-case-adapter.md / use-case-adapter-gsg.md / vlm-integration-gsg.md 完整 |
| **测试覆盖** | **85%** | rule-eval tool 有 unit test；5 个 UC 中 2 个有 e2e 真实视频验证 |

**综合评估**：Adapter 框架**核心能力已到位**，Design §5.1 / §5.3 基本兑现；**§5.2 承诺的向导化"零代码 3 输入创建 UC"未实现**，需要额外一层 orchestration。

---

## 3. Design 与实现之间的命名/API 对齐 gap

Design 的 tool 名称与代码中的 tool 名称**不完全对齐**：

| Design 提到的 tool | 代码里的对应 |
|-------------------|-------------|
| `smartbuilding_daily_report` | `smartbuilding_generate_report` |
| `smartbuilding_db_manager action=register_use_case` | 不存在；手改 config.yaml 代替 |
| `smartbuilding_video_summary_task action=autogen` | 不存在；curl POST /v1/tasks 代替 |
| `parseScript` (parse_summary.py) | 未实现 |
| `smartbuilding_monitor_ctl unregister` | ✅ 存在 |
| `smartbuilding_use_case_validate` 支持 dynamic task | ⚠️ 校验流程未针对 dynamic-registered task 特化 |

**建议**：一次 Design doc 修订 → 名字对齐现实，删掉 `db_manager register_use_case` 这类**未实现**的 API 声明。

---

## 4. 优先级排序 (给 owner 参考)

| 优先级 | Gap | 工作量估算 | 价值 |
|--------|-----|-----------|------|
| P0 | 修 use_case_validate 支持 dynamic task | 半天 | 消掉两次验证 log 里都出现的 ⚠️ |
| P1 | 把 severity-threshold + event-deny-list 逻辑做进 defaultRuleEvaluator，让**简单 UC 真的零代码** | 1 天 | 兑现"零代码"承诺 |
| P1 | `smartbuilding_video_summary_task register/autogen/list` MCP tool 封装 | 1-2 天 | 消除 curl 手工步骤 |
| P2 | `smartbuilding_use_case_register` MCP tool: 一次调用完成 config.yaml patch + task 注册 + schema ALTER | 2-3 天 | 兑现"向导化" |
| P2 | 支持 `parse_summary.py` override (设计 §5.3 声称) | 1 天 | 极少场景用得到 (VLM 输出非标) |
| P3 | Prompt lint tool (静态检 `A|B|C` / code fence) | 半天 | 复用 use-case-adapter §Prompt writing conventions |
| P3 | `smartbuilding_use_case_wizard` MCP tool（agent 交互式） | 1 周 | 完全兑现 §5.2 图 5-1 |

---

## 5. 验证结论：Adapter 框架是否达到 Design §1.3 "零代码用例创建"？

**部分达到**：
- ✅ 用户在**不改 TypeScript 代码**的前提下，用 3 个文件 (evaluate_rules.py + prompt.md + config.yaml 补丁) 加了 2 个新 UC (high_altitude / parking)，全端跑通
- ❌ 但设计 §5.2 承诺的**"3 个输入 + 向导"** 未实现 — 用户仍需手工写 3 个文件、curl 注册 VLM task、编辑 YAML

**结论**：**"零 TS 代码"已达成，"零 YAML/prompt 手工"未达成**。

## 参考

- [use-case-adapter-validation.md](./use-case-adapter-validation.md) — 真实 UC 验证 log (HA + Parking)
- [smartbuilding-video-design-2026.2.md §5](../smartbuilding-video-design-2026.2.md#5-use-case-adapter) — 设计基线
- [use-case-adapter.md](../use-case-adapter.md) — 开发者手册
