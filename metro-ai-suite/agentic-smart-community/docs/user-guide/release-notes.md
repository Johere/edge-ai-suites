# Release Notes: Agentic Smart Community

## Unreleased

**New**:

- **Per-monitor prefilter models**: each monitor selects its own OpenVINO™ detection model, so cameras with different jobs can run different detectors — and different inference devices — side by side. Models are declared in a `prefilter_models` registry in the `videostream-analytics` configuration and selected by name through `pipeline_config.prefilter.model`. See [Configure the Prefilter Model for a Monitor](./how-to-guides/configure-prefilter-model.md).
- **Prefilter model discovery**: `smart_community_monitor_ctl action=prefilter_options` (and `GET /capabilities/prefilter`) now lists every selectable model with its classes, label provenance, and input shape, plus a `rejected` list explaining why a registered model is unusable. Pass `model=<name>` for a single model's detail. Agents use this to help a user choose a model and its target classes in conversation.
- **Model validation on registration**: a registered model becomes selectable only after its `kind`, `backend`, containment under `model_dir`, IR pair on disk, readability, and detection-shaped output all check out. A model whose output is not a detection tensor is refused at load instead of producing meaningless detections, and a dynamically-shaped model pinned to the NPU is flagged with the fix.
- **Standalone `videostream-analytics` setup**: `videostream-analytics/setup_vsa.sh` prepares the prefilter model, seeds the service configuration, and can drive `docker compose` (`bash setup_vsa.sh up`), so VSA deploys without the rest of the smart-community stack. `setup_docker.sh` sources it, so the full-stack flow is unchanged.
- **User-owned VSA configuration**: the live `videostream-analytics` configuration now lives at `${VIDEOSTREAM_CACHE_HOST}/config.yaml` (default `~/.cache/.videostream-analytics/config.yaml`), seeded once from the template and never overwritten by re-running setup — custom `prefilter_models` entries and tuned `defaults`/`security`/`webhook` blocks survive reinstalls. `videostream-analytics/config/config.yaml` in the repo is a symlink to it, so the familiar path keeps working. Configuration keys added in future releases fall back to code defaults in already-seeded files.

**Changed (breaking)**:

- `pipeline.prefilter.model_path` is no longer accepted in `register_source` / `PUT /sources/{id}/pipeline` requests; selecting a model by name via `pipeline.prefilter.model` replaces it, and a request carrying a path is rejected with HTTP 422. Deployments that relied on the deployment default are unaffected.
- `security.allowed_model_roots` is removed from the `videostream-analytics` configuration. It confined request-supplied model paths, which no longer exist; `model_dir` is now the single root models must live under.
- The tracked `videostream-analytics/config/config.yaml` is renamed to `config/config.yaml.example` and is no longer the live configuration — it only seeds your copy. Move any edits you made there to `${VIDEOSTREAM_CACHE_HOST}/config.yaml`.
- `MODEL_DIR` now defaults to `~/models/openvino` (was `~/models`), so the VSA container's read-only model mount no longer includes the Hugging Face weights cache. The bundled YOLO11s path is unchanged; custom models must live under `MODEL_DIR` — move them or export `MODEL_DIR` pointing at their root.

## Version 2026.2.0

**Release Date**: September 10, 2026

This initial release introduces an AI agent-native video analysis platform designed for MCP (Model Context Protocol) integration.

**New**:

- **Containerized services**: deploys the `smart-community-mcp-server` and `videostream-analytics` services as containers for a consistent smart-community video-analysis runtime.
- **MCP tools for agent conversations**: exposes 10 built-in MCP tools, including scene queries, alert retrieval, report generation, and monitor management, so any MCP-compatible agent framework can answer video-related questions and carry out monitoring workflows through conversation.
- **Conversational use-case customization**: lets users describe a monitoring need to an agent, which can create and configure a tailored use case through the platform.
- **Bundled use cases**: includes Fridge, Child Safety, and Elder Wakeup use cases for immediate evaluation and customization.
- **Operations dashboard**: provides a dashboard for viewing currently online monitors, detected events, and summarized activity.
