"""FastAPI application for videostream-analytics microservice."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from shared.config import AppConfig, SourceConfig, MotionConfig, SegmentConfig, PrefilterConfig, HealthConfig
from source_worker import SourceManager

logger = logging.getLogger(__name__)

_manager: SourceManager | None = None


# --- Request Models (module-level for FastAPI schema resolution) ---

class RegisterSourceRequest(BaseModel):
    source_id: str
    rtsp_url: str
    use_case: str = "default"
    webhook_url: str | None = None
    motion: MotionConfig | None = None
    segment: SegmentConfig | None = None
    prefilter: PrefilterConfig | None = None
    health: HealthConfig | None = None


class UnregisterSourceRequest(BaseModel):
    source_id: str


class UpdatePipelineRequest(BaseModel):
    motion: MotionConfig | None = None
    segment: SegmentConfig | None = None
    prefilter: PrefilterConfig | None = None
    health: HealthConfig | None = None


def get_manager() -> SourceManager:
    if _manager is None:
        raise RuntimeError("SourceManager not initialized")
    return _manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _manager
    config: AppConfig = app.state.config
    _manager = SourceManager(config)
    logger.info("videostream-analytics started on :%d", config.server.port)
    yield
    _manager.stop_all()
    logger.info("videostream-analytics shut down")


def create_app(config: AppConfig) -> FastAPI:
    app = FastAPI(
        title="videostream-analytics",
        version="0.1.0",
        description="Smart Building video stream analytics microservice",
        lifespan=lifespan,
    )
    app.state.config = config

    # --- Endpoints ---

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "videostream-analytics"}

    @app.get("/sources")
    async def list_sources() -> dict[str, Any]:
        mgr = get_manager()
        return {"sources": mgr.get_sources()}

    @app.get("/sources/{source_id}")
    async def get_source(source_id: str) -> dict[str, Any]:
        mgr = get_manager()
        status = mgr.get_source_status(source_id)
        if status is None:
            raise HTTPException(status_code=404, detail=f"Source not found: {source_id}")
        return status

    @app.post("/register_source")
    async def register_source(req: RegisterSourceRequest) -> dict[str, Any]:
        mgr = get_manager()
        source = SourceConfig(
            source_id=req.source_id,
            rtsp_url=req.rtsp_url,
            use_case=req.use_case,
            webhook_url=req.webhook_url,
            motion=req.motion,
            segment=req.segment,
            prefilter=req.prefilter,
            health=req.health,
        )
        result = mgr.register_source(source)
        return result

    @app.delete("/unregister_source")
    async def unregister_source(req: UnregisterSourceRequest) -> dict[str, Any]:
        mgr = get_manager()
        result = mgr.unregister_source(req.source_id)
        if result["status"] == "not_found":
            raise HTTPException(
                status_code=404, detail=f"Source not found: {req.source_id}"
            )
        return result

    @app.post("/sources/{source_id}/stop")
    async def stop_source(source_id: str) -> dict[str, Any]:
        mgr = get_manager()
        result = mgr.unregister_source(source_id)
        if result["status"] == "not_found":
            raise HTTPException(status_code=404, detail=f"Source not found: {source_id}")
        return result

    @app.post("/sources/{source_id}/restart")
    async def restart_source(source_id: str) -> dict[str, Any]:
        mgr = get_manager()
        status = mgr.get_source_status(source_id)
        if status is None:
            raise HTTPException(status_code=404, detail=f"Source not found: {source_id}")
        # Stop and re-register
        pipeline = mgr._pipelines.get(source_id)
        if pipeline:
            pipeline.stop()
            pipeline.start()
            return {"status": "restarted", "source_id": source_id}
        raise HTTPException(status_code=404, detail=f"Source not found: {source_id}")

    @app.post("/sources/{source_id}/pause")
    async def pause_source(source_id: str) -> dict[str, Any]:
        mgr = get_manager()
        result = mgr.pause_source(source_id)
        if result["status"] == "not_found":
            raise HTTPException(status_code=404, detail=f"Source not found: {source_id}")
        return result

    @app.post("/sources/{source_id}/resume")
    async def resume_source(source_id: str) -> dict[str, Any]:
        mgr = get_manager()
        result = mgr.resume_source(source_id)
        if result["status"] == "not_found":
            raise HTTPException(status_code=404, detail=f"Source not found: {source_id}")
        return result

    @app.put("/sources/{source_id}/pipeline")
    async def update_pipeline(source_id: str, req: UpdatePipelineRequest) -> dict[str, Any]:
        mgr = get_manager()
        result = mgr.update_pipeline_config(
            source_id=source_id,
            motion=req.motion,
            segment=req.segment,
            prefilter=req.prefilter,
            health=req.health,
        )
        if result["status"] == "not_found":
            raise HTTPException(status_code=404, detail=f"Source not found: {source_id}")
        return result

    @app.delete("/sources/{source_id}")
    async def delete_source(source_id: str) -> dict[str, Any]:
        mgr = get_manager()
        result = mgr.unregister_source(source_id)
        if result["status"] == "not_found":
            raise HTTPException(status_code=404, detail=f"Source not found: {source_id}")
        return result

    return app
