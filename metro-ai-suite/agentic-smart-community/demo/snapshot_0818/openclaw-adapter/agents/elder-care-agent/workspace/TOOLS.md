# TOOLS.md — Environment Info

## Monitor

| monitor_id | use_case | RTSP | What it watches |
|---|---|---|---|
| `cam_elder_care` | `elder_care` | `rtsp://localhost:8557/live/eldercare` | 单人老年护理卧室：卧床 / 坐起 / 离床 / 在室活动 / 回床 / 躁动 / 夜间离室 / 工作人员到访 / 房间空置 / 不确定 |

`cam_elder_care` is your default. To see what's actually registered right now, call `smart_community_monitor_ctl action=list` and filter by `use_case: elder_care`.

All camera access, VLM calls, database reads, and report generation go through the `smart_community_*` MCP tools, provided by the **`smart-community`** MCP server (registered in OpenClaw as `mcp.servers.smart-community`; verify with `openclaw mcp probe smart-community`). See the **smart-community-toolkit** skill for the tool reference. You don't address services, ports, or file paths directly.

## Alert routing

This agent receives pushed alerts from `smart-community-alerts` via session `agent:elder-care-agent:cam_elder_care`. **Only `restlessness` and `night_out_of_room`** events are routed here as warn alerts (per `elder_care` rule path). All other events are info-level timeline rows and are **not** pushed — query them via the daily report or `video_db` SQL.

## Pipeline config (cam_elder_care)

- prefilter: NPU yolo11s, target_classes = `person`
- motion: enabled (diff_threshold=20, area_ratio=0.004, stable_frames=20) — sensitive enough for bed-area changes, false positives absorbed by the VLM as `room_empty` / `in_bed`
- roi: explicitly disabled (full-frame context needed for door / chair / tv)

Note: `monitors.yaml` currently does not contain the `motion` block (persist quirk on rebind); runtime still has it.