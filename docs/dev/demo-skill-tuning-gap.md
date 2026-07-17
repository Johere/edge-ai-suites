# Demo Skill / Agent Tuning — 差距分析

> 记录把旧 smarthome demo（打包式 OpenClaw 插件 + Python 脚本）迁移到新架构
> （`smart-community` MCP server + framework adapter）过程中，**skill 与 agent 人设层**
> 已对齐的内容，以及对齐 smarthome 后**仍缺**的能力。范围仅限文档层；运行时接线（cron、
> server 端功能）另行处理。

## 背景

- 工具面：`smart-community` MCP server（OpenClaw 注册名，Streamable-HTTP `:3100/mcp`，
  `openclaw mcp probe smart-community` 可验证）暴露 `smartbuilding_*` 工具。运行时实测 12 个，
  其中**已 review 的 8 个**记录在 [docs/implements/tools_list.md](../implements/tools_list.md)：
  `alert_query` · `plan_ctl` · `scene_query` · `generate_report` · `monitor_ctl` ·
  `monitors_compose` · `video_db` · `use_case_validate`。
- 报表配置驱动：`generate_report` 的 `data_source` / `filter` / `default_type` 由
  `config.yaml` `use_case_dict.<uc>.reports` 派生，tool 参数可覆写
  （见 [packages/mcp-server/src/tools.ts](../../packages/mcp-server/src/tools.ts) 与
  [packages/tools/src/generate-report.ts](../../packages/tools/src/generate-report.ts)）。

## 已完成（本轮文档调优）

- **Layer-1 通用 skill**：新建 [skills/smartbuilding-toolkit/SKILL.md](../../skills/smartbuilding-toolkit/SKILL.md)
  —— 框架无关，只含 8 个 reviewed 工具、DB 模型、按 `use_case` 的 monitor 发现协议、报表两层
  范式、告警/破坏性操作约定。无人设的新 agent 读它即可上手。
- **Layer-2 三个 agent 人设**（`packages/framework-adapter-sdk/examples/openclaw/agents/*/workspace/`）：
  - 全量对齐 `smartbuilding_*`（删除已不存在的 `fridge_query`/`state_query`，未 review 的
    `rule_eval`/`prompt_lint`/`use_case_register`/`video_summary_task` 一律不写）。
  - 英文书写 + 「按用户语言回复」。
  - `monitor_id`：硬编码默认（`cam_fridge`/`cam_child`/`cam_elder_bedroom`）+ 按 `use_case`
    发现兜底（多个→问用户，为零→告知未注册）。
  - **Reports 段写出显式默认参数** + 覆写规则（跨度/过滤）。
  - `TOOLS.md` 去掉端口/内部路径，点明工具来自 `smart-community` MCP server。

## 仍缺（对齐 smarthome 的差距）

| # | 差距 | 说明 | 影响 |
|---|------|------|------|
| 1 | **调度 / 主动层** | 旧 demo 有 5 个 cron（22:00 冰箱/儿童日报、周日 22:00 老人周报、10:00 no_wakeup 兜底、00:00 reset）。新仓库无任何 cron/`jobs.json`。 | 定时日报、周报、no_wakeup 兜底、每日重置全部**未接线**，仅能被动应答。 |
| 2 | **润色版报表持久化** | `generate_report` 只落 raw 到 `reports` 表，**无 `report_text` 回存参**（旧 `daily_report` 有）。 | agent 润色后的报表只推送、不入库，无法二次检索/审计。 |
| 3 | **`pauseAfterTargetEvent`（老人起床后暂停管线）** | 已从 elder 人设移除；新 server/monitor 配置是否实现**未核实**。 | 若未实现，老人起床后管线不会暂停，与旧 demo 行为不一致。 |
| 4 | **告警的人设化渲染 / 主动推送** | 当前 adapter `deliver:false` 只把告警 FS-append 成 session 上下文，**不触发主动回复**（人设已据此修正）。旧 notifier 的 emoji + dashboard「立即查看」深链 + 指令 preamble 的 persona 渲染尚缺。 | 告警不会自动生成一条人设化的推送消息。 |
| 5 | **Dashboard 深链** | 旧有 `:18799` Alerts tab + `?source=&alert=` 深链；新架构以 MCP resource 取代。 | 告警文案里的「立即查看」类链接目标可能失效。 |
| 6 | **skill 框架接线** | `smartbuilding-toolkit` 已产出文件，但需被 OpenClaw 的 skills 加载路径实际加载。 | 未加载则新 agent 看不到该 skill。 |
| 7 | **`HEARTBEAT.md`（属 #1 的一部分）** | 两个 agent 的 `HEARTBEAT.md` 仍描述旧 cron + 旧插件架构（`daily_report`/`rule_eval`/`state_query`/`pauseAfterTargetEvent`/`~/.openclaw/cron`）。 | 保留为 gap，与 #1 一起重做；当前内容指向已不存在/未 review 的工具。 |
| 8 | fridge agent的daily report | srt如何组织？我看到filter只有motio_type表的motion字段。但是smarthome demo(/home/mytest/agent-ai.smarthome/agent-ai.smarthome-openclaw-runtime-workspace) 是会joint tasks表的summary_text字段的 | to check and align |


## 附带发现（参考文档 drift，未修改）

- [docs/implements/tools_list.md](../implements/tools_list.md) §4 `generate_report` 的
  `data_source` 枚举写作 `events | alerts | tasks`，实际代码为 `video_summary_tasks`。
- `packages/framework-adapter-sdk/examples/openclaw/README.md` 写 `smart-community: 8 tools`，
  运行时实测 12 tools。
