# TOOLS.md - Local Environment Info

## Monitors

| source_id | Name | Location | Description |
|---|---|---|---|
| `cam_elder_bedroom` | Elder Bedroom Camera | 老人卧室 | Watches bed for get_up vs in_bed_awake vs still_sleeping |

## Service Ports

| Service | Address | Description |
|---|---|---|
| OpenClaw Gateway | http://localhost:18789 | API gateway |
| Dashboard | http://localhost:18799 | Live stream + events + alerts UI |
| Video Summary Service | http://localhost:8192 | multilevel-video-understanding |
| vllm-ipex-serving | http://localhost:41091 | VLM backend |
| File Server | http://172.18.0.1:8199 | Access recordings from within Docker |
| RTSP Stream | rtsp://localhost:8554/live/elder | Elder bedroom live stream |

## Data Paths

| Purpose | Path |
|---|---|
| Database | `/home/edgeai/.openclaw/smarthome-demo/data/cam_elder_bedroom/pipeline.db` |
| Recordings | `/home/edgeai/.openclaw/smarthome-demo/data/cam_elder_bedroom/recordings/` |
| Motion clips | `/home/edgeai/.openclaw/smarthome-demo/data/cam_elder_bedroom/motion_events/` |
| Latest frame | `/home/edgeai/.openclaw/smarthome-demo/data/cam_elder_bedroom/latest.jpg` |
| Prefilter model | `/home/edgeai/models/openvino/shape_static_1280x704/yolo11s/FP16/yolo11s.xml` (NPU) |
| Demo video (RTSP source) | `/home/edgeai/Video/day1_elder_wakeup.mp4` |
| VLM task prompt | `/home/edgeai/.openclaw/smarthome-demo/prompts/tasks/elder_wakeup_monitor.py` |

## Pipeline Specifics

- **VLM task name**: `elder_wakeup_monitor` (dynamically registered at worker
  startup).
- **YOLO prefilter**: NPU, target_classes = ["person"], roi_crop disabled.
- **pauseAfterTargetEvent**: true — pipeline pauses for the day after the
  observed `get_up`; resumes at 00:00.
- **Default scene prompt**: "床上是否有人 (yes/no/unclear) + 一句姿态描述
  (1~2 句话)".
- **Rule engine** evaluates `late_wakeup` when observed HH:MM > expected +
  `graceMinutes`.
- **Cron `elder-wakeup-fallback-10`** (10:00 local) is the safety net for
  no_wakeup: the rule_eval tool chains through scene_query before emitting.
- **Target session**: `agent:elder-wakeup-agent:main`
  (`sessionTarget: session:elder-wakeup-alert-en`).
