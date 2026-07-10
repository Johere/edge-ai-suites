# TOOLS.md - Local Environment Info

## Monitors

| source_id | Name | Location | Description |
|---|---|---|---|
| `cam_child` | Child Safety Camera | 客厅 / living room | Main monitor for 小卫; motion + YOLO prefilter + VLM pipeline |

## Service Ports

| Service | Address | Description |
|---|---|---|
| OpenClaw Gateway | http://localhost:18789 | API gateway; auth token in openclaw.json |
| Dashboard | http://localhost:18799 | Live stream + events + alerts UI |
| Video Summary Service | http://localhost:8192 | multilevel-video-understanding; /v1/health, /v1/summary, /v1/tasks |
| vllm-ipex-serving | http://localhost:41091 | VLM backend (shared with fridge) |
| File Server | http://172.18.0.1:8199 | Access recordings from within Docker |
| RTSP Stream | rtsp://localhost:8554/live/child | Child camera live stream |

## Data Paths

| Purpose | Path |
|---|---|
| Database | `/home/edgeai/.openclaw/smarthome-demo/data/cam_child/pipeline.db` |
| Recordings | `/home/edgeai/.openclaw/smarthome-demo/data/cam_child/recordings/` |
| Motion clips | `/home/edgeai/.openclaw/smarthome-demo/data/cam_child/motion_events/` |
| Latest frame | `/home/edgeai/.openclaw/smarthome-demo/data/cam_child/latest.jpg` |
| Prefilter model | `/home/edgeai/models/openvino/shape_static_1280x704/yolo11s/FP16/yolo11s.xml` (NPU) |
| Demo video (RTSP source) | `/home/edgeai/Video/child_safety_demo.mp4` |
| VLM task prompt | `/home/edgeai/.openclaw/smarthome-demo/prompts/tasks/child_safety_monitor.py` |

## Pipeline Specifics

- **VLM task name**: `child_safety_monitor` (dynamically registered at worker
  startup; see `summary_service.task_register` in `config_child.yaml`).
- **YOLO prefilter**: NPU (static FP16 1280×704) — must be ready before
  stream_monitor starts processing motion.
- **Rule engine**: runs in the plugin TS on `task_done` webhook arrival.
- **Target session**: `agent:child-safety-agent:main` (controlUI by default;
  may be extended to Feishu via sessionKey scheme).
