# 命名体系 Gap 与统一方案（延后执行）

**状态日期**: 2026-07-17
**结论**: 现状命名与设计原则存在一处不一致；**本阶段不改**（改动面广、正处于集成期，
易与并行分支冲突），记录在此，待后续择机与其它重构一起做。

---

## 0. 设计原则（命名意图）

- **MCP server 本身 = "smart community"** —— 它是一把伞 / 一个平台入口。
- server 之下可以挂**多种工具集合**，每种工具集用**自己的前缀**区分。
- 目前**只有一种**工具集：`smartbuilding_*`（楼宇/视频监控方向）。
- 将来横向扩展时，再加**不同前缀**的新工具集（例如 `parking_*`、`energy_*` …），
  它们与 `smartbuilding_*` 并列，同挂在 smart-community server 下。

一句话：`smart-community` 是伞，`smartbuilding_*` 是伞下的**第一个**工具集，
不是伞本身。

---

## 1. 现状命名体系（实测）

| 层级 | 现状命名 | 位置 |
|---|---|---|
| 项目 / 仓库 / 平台 | `smart-community-ai-automation` | 根 [package.json](../../package.json)、[README.md](../../README.md) 标题 "Smart Community AI Automation" |
| **Host 侧 MCP 注册别名**（agent 实际寻址用的名字） | **`smart-community`** ✅ | OpenClaw `openclaw.json` `mcp.servers.smart-community`；`openclaw mcp probe smart-community`（见 [examples/openclaw/README.md:153](../../packages/framework-adapter-sdk/examples/openclaw/README.md) 及各 agent `TOOLS.md`） |
| **MCP SDK server 自报名**（`initialize` 响应里的 `implementation.name`） | **`smartbuilding-video`** ⚠️ | [packages/mcp-server/src/index.ts:39](../../packages/mcp-server/src/index.ts) |
| npm 包 scope | `@smartbuilding-video/*`（db / tools / mcp-server / framework-adapter-sdk） | 各 `packages/*/package.json` |
| 工具集前缀 | `smartbuilding_*`（实测 12 个工具） | [packages/mcp-server/src/tools.ts](../../packages/mcp-server/src/tools.ts) |
| 数据目录 | `~/.mcp-smartbuilding`（env `SMARTBUILDING_DATA_DIR`） | [packages/mcp-server/src/config.ts:150](../../packages/mcp-server/src/config.ts) |
| SQLite 文件 | `smartbuilding.db` | [packages/mcp-server/src/config.ts:170](../../packages/mcp-server/src/config.ts) |
| DB 类型名 | `SmartBuildingDB` | `@smartbuilding-video/db` |

12 个工具（全部 `smartbuilding_` 前缀）：`alert_query` · `plan_ctl` · `scene_query` ·
`generate_report` · `monitor_ctl` · `monitors_compose` · `video_db` · `use_case_validate` ·
`use_case_register` · `prompt_lint` · `video_summary_task` · `rule_eval`。

---

## 2. Gap 分析

### 2.1 符合原则的部分 ✅

- **工具集前缀 `smartbuilding_*`** 完全符合"伞下第一个工具集"的定位——将来加新前缀天然并列，无需动它。
- **Host 侧注册别名已经是 `smart-community`**：agent 端真正寻址 server 用的名字（`mcp.servers.smart-community`、`openclaw mcp probe smart-community`）就是伞名。**从 agent 视角看，设计原则其实已经成立。**
- 仓库 / 平台层也是 `smart-community`。

### 2.2 违背原则的部分 ⚠️

问题集中在**代码级产物**——它们把"伞"绑死成了"其中一个工具集"的名字 `smartbuilding`：

| # | 现状 | 为什么违背原则 | 应改为 |
|---|---|---|---|
| G1 | MCP SDK server 自报名 `smartbuilding-video`（index.ts:39） | server 是伞，不该以单一工具集命名。加第二个工具集后，`smartbuilding-video` 这个自报名会误导（server 里明明有 `parking_*` 却自称 building） | `smart-community` |
| G2 | npm scope `@smartbuilding-video/*` | 同上，monorepo 顶层 scope 应是伞名 | `@smart-community/*` |
| G3 | DB 类型名 `SmartBuildingDB` | DB 是 server（伞）级共享资源，非工具集私有 | `SmartCommunityDB`（或中性名） |
| G4 | 数据目录 `~/.mcp-smartbuilding` + env `SMARTBUILDING_DATA_DIR` | 伞级 runtime 目录 | `~/.mcp-smart-community` + `SMART_COMMUNITY_DATA_DIR` |
| G5 | DB 文件 `smartbuilding.db` | 伞级单库（多工具集共用同一库 + schema 定制） | `smart-community.db`（或中性） |

> 注意：**host 别名 `smart-community` 与 SDK 自报名 `smartbuilding-video` 是两个独立的名字**。
> 前者是 host 配置的 key（谁配谁定），后者是 server 自己在 MCP 握手里报出来的。二者不一致
> 目前不影响功能（host 用别名寻址），但语义上确实是"伞被叫成了工具集"，属于要收敛的 gap。

---

## 3. 统一方案（待执行）

**目标末态**：伞级一律 `smart-community`，工具集级保留 `smartbuilding_*`（作为"第一个工具集"）。

| 改动项 | From | To | 影响面 |
|---|---|---|---|
| server 自报名 | `smartbuilding-video` | `smart-community` | 1 处（index.ts:39）|
| npm scope | `@smartbuilding-video/*` | `@smart-community/*` | ~32 个文件、~60 处 import + 4 个 `package.json` name |
| DB 类型名 | `SmartBuildingDB` | `SmartCommunityDB` | 随 scope 一起（import 类型）|
| 数据目录 / env | `~/.mcp-smartbuilding` / `SMARTBUILDING_DATA_DIR` | `~/.mcp-smart-community` / `SMART_COMMUNITY_DATA_DIR` | config.ts + docs + scripts，~28 个文件引用；**需数据迁移**（mv 目录）|
| DB 文件名 | `smartbuilding.db` | `smart-community.db` | config.ts + 已有实例需 mv |
| **工具前缀 `smartbuilding_*`** | —— | **保持不变** | ~365 处引用（docs/src/examples/agent workspace）**均不动** |

**不动 `smartbuilding_` 前缀**是本方案的关键：它符合原则，且是引用量最大的一块（~365 处）。
统一只针对"伞级"5 类产物（G1–G5），实际代码改动集中在 `@smartbuilding-video/` scope 与
data-dir/env/db 常量，可用一次性替换 + 数据目录迁移完成。

---

## 4. 为什么本阶段不改

- **集成期**：MCP server / VSA / VLM / use-case adapter 正在多分支联调（见
  [dev_status.md](dev_status.md)、[integration-status.md](integration-status.md)），
  scope 重命名会触碰 ~32 个文件的 import，极易与并行分支产生大面积 merge 冲突。
- **需数据迁移**：`~/.mcp-smartbuilding` → `~/.mcp-smart-community` 及 `smartbuilding.db`
  改名涉及已有运行实例的数据搬迁，须与一次干净的停服窗口配合。
- **纯语义收敛，无功能收益**：host 别名已是 `smart-community`，agent 侧寻址不受影响，
  当前不改不会造成功能问题——属于"欠债可控"的技术债。

**触发时机**：等到（a）第二个工具集（非 `smartbuilding_*` 前缀）真正要落地，或
（b）有一次集中重构 / 停服窗口时，把 G1–G5 一起改掉。届时以本文档 §3 表为清单。

---

## 5. 执行清单（后续照做）

- [ ] G1 `index.ts:39` server name → `smart-community`
- [ ] G2 4 个 `package.json` name + 全仓 `@smartbuilding-video/` import → `@smart-community/`
- [ ] G3 `SmartBuildingDB` 类型名 → `SmartCommunityDB`（连同 import）
- [ ] G4 `config.ts` data-dir 默认值 + env 名 → `~/.mcp-smart-community` / `SMART_COMMUNITY_DATA_DIR`；迁移已有目录
- [ ] G5 `config.ts` db 文件名 → `smart-community.db`；迁移已有 `.db` / `-wal` / `-shm`
- [ ] 同步更新 docs 里对 data-dir / env / db / scope 的引用（~28 文件）
- [ ] **确认 `smartbuilding_*` 工具前缀全程未改**（回归检查）
- [ ] `npm install` 重链 workspace + 全量测试
- [ ] host 侧 `openclaw.json` `mcp.servers.smart-community` 别名保持不变（已符合末态）
