# TOOLS.md - Local Environment Info

## Monitors

| source_id | Name | Location | Description |
|-----------|------|----------|-------------|
| `cam_fridge` | Fridge Camera | Kitchen fridge front | Main monitor, detects door open/close events |

## Service Ports

| Service | Address | Description |
|---------|---------|-------------|
| OpenClaw Gateway | http://localhost:18789 | API Gateway |
| Dashboard | http://localhost:18799 | Monitoring Dashboard UI |
| Video Summary Service | http://localhost:8192 | multilevel-video-understanding video summary |
| vllm-ipex-serving | http://localhost:41091 | vllm-based local model serving service for image analysis |
| File Server | http://172.18.0.1:8199 | Access local files from within Docker |
| RTSP Stream | rtsp://localhost:8554/live | Camera live stream |

## Data Paths

| Purpose | Path |
|---------|------|
| Database | `/home/edgeai/.openclaw/smarthome-demo/data/cam_fridge/pipeline.db` |
| Recordings | `/home/edgeai/.openclaw/smarthome-demo/data/cam_fridge/recordings/` |
| Motion clips | `/tmp/cam_fridge/motion_events/` |
| Demo videos | `/home/edgeai/Videos/` |
