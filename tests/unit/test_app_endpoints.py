"""Tests for FastAPI endpoints with mocked SourceManager."""

import json
from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from src.config import AppConfig, MotionConfig, SegmentConfig, PrefilterConfig, SourceConfig
from src.source_manager import SourceManager


class RegisterSourceRequest(BaseModel):
    source_id: str
    rtsp_url: str
    use_case: str = "default"
    motion: MotionConfig | None = None
    segment: SegmentConfig | None = None
    prefilter: PrefilterConfig | None = None


class UnregisterSourceRequest(BaseModel):
    source_id: str


@pytest.fixture
def mock_manager():
    mgr = MagicMock(spec=SourceManager)
    mgr.get_sources.return_value = []
    mgr.get_source_status.return_value = None
    mgr._pipelines = {}
    return mgr


@pytest.fixture
def app_and_client(mock_manager):
    """Create a fresh FastAPI app with properly-scoped models and mocked manager."""
    app = FastAPI()

    def get_mgr():
        return mock_manager

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "videostream-analytics"}

    @app.get("/sources")
    async def list_sources():
        return {"sources": get_mgr().get_sources()}

    @app.get("/sources/{source_id}")
    async def get_source(source_id: str):
        from fastapi import HTTPException
        status = get_mgr().get_source_status(source_id)
        if status is None:
            raise HTTPException(status_code=404, detail=f"Source not found: {source_id}")
        return status

    @app.post("/register_source")
    async def register_source(req: RegisterSourceRequest):
        source = SourceConfig(
            source_id=req.source_id,
            rtsp_url=req.rtsp_url,
            use_case=req.use_case,
            motion=req.motion,
            segment=req.segment,
            prefilter=req.prefilter,
        )
        return get_mgr().register_source(source)

    @app.delete("/unregister_source")
    async def unregister_source(req: UnregisterSourceRequest):
        from fastapi import HTTPException
        result = get_mgr().unregister_source(req.source_id)
        if result["status"] == "not_found":
            raise HTTPException(status_code=404, detail=f"Source not found: {req.source_id}")
        return result

    @app.post("/sources/{source_id}/stop")
    async def stop_source(source_id: str):
        from fastapi import HTTPException
        result = get_mgr().unregister_source(source_id)
        if result["status"] == "not_found":
            raise HTTPException(status_code=404, detail=f"Source not found: {source_id}")
        return result

    @app.post("/sources/{source_id}/restart")
    async def restart_source(source_id: str):
        from fastapi import HTTPException
        status = get_mgr().get_source_status(source_id)
        if status is None:
            raise HTTPException(status_code=404, detail=f"Source not found: {source_id}")
        pipeline = get_mgr()._pipelines.get(source_id)
        if pipeline:
            pipeline.stop()
            pipeline.start()
            return {"status": "restarted", "source_id": source_id}
        raise HTTPException(status_code=404, detail=f"Source not found: {source_id}")

    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc, mock_manager


@pytest.fixture
def client(app_and_client):
    return app_and_client[0]


@pytest.fixture
def mock_mgr(app_and_client):
    return app_and_client[1]


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "videostream-analytics"


class TestListSources:
    def test_empty_sources(self, client, mock_mgr):
        mock_mgr.get_sources.return_value = []
        resp = client.get("/sources")
        assert resp.status_code == 200
        assert resp.json()["sources"] == []

    def test_with_sources(self, client, mock_mgr):
        mock_mgr.get_sources.return_value = [
            {
                "source_id": "cam1",
                "rtsp_url": "rtsp://localhost:8554/live/cam1",
                "use_case": "child_safety",
                "status": "online",
                "running": True,
            }
        ]
        resp = client.get("/sources")
        assert resp.status_code == 200
        sources = resp.json()["sources"]
        assert len(sources) == 1
        assert sources[0]["source_id"] == "cam1"


class TestGetSource:
    def test_existing_source(self, client, mock_mgr):
        mock_mgr.get_source_status.return_value = {
            "source_id": "cam1",
            "rtsp_url": "rtsp://localhost:8554/live/cam1",
            "use_case": "child_safety",
            "status": "online",
            "running": True,
        }
        resp = client.get("/sources/cam1")
        assert resp.status_code == 200
        assert resp.json()["source_id"] == "cam1"

    def test_nonexistent_source(self, client, mock_mgr):
        mock_mgr.get_source_status.return_value = None
        resp = client.get("/sources/nonexistent")
        assert resp.status_code == 404


class TestRegisterSource:
    def test_register_success(self, client, mock_mgr):
        mock_mgr.register_source.return_value = {
            "status": "started",
            "source_id": "cam1",
            "rtsp_url": "rtsp://localhost:8554/live/cam1",
        }
        resp = client.post("/register_source", json={
            "source_id": "cam1",
            "rtsp_url": "rtsp://localhost:8554/live/cam1",
            "use_case": "child_safety",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "started"

    def test_register_already_running(self, client, mock_mgr):
        mock_mgr.register_source.return_value = {
            "status": "already_running",
            "source_id": "cam1",
        }
        resp = client.post("/register_source", json={
            "source_id": "cam1",
            "rtsp_url": "rtsp://localhost:8554/live/cam1",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "already_running"


class TestUnregisterSource:
    def test_unregister_success(self, client, mock_mgr):
        mock_mgr.unregister_source.return_value = {
            "status": "stopped",
            "source_id": "cam1",
        }
        resp = client.request("DELETE", "/unregister_source", json={
            "source_id": "cam1",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "stopped"

    def test_unregister_not_found(self, client, mock_mgr):
        mock_mgr.unregister_source.return_value = {
            "status": "not_found",
            "source_id": "nonexistent",
        }
        resp = client.request("DELETE", "/unregister_source", json={
            "source_id": "nonexistent",
        })
        assert resp.status_code == 404


class TestStopSource:
    def test_stop_success(self, client, mock_mgr):
        mock_mgr.unregister_source.return_value = {
            "status": "stopped",
            "source_id": "cam1",
        }
        resp = client.post("/sources/cam1/stop")
        assert resp.status_code == 200

    def test_stop_not_found(self, client, mock_mgr):
        mock_mgr.unregister_source.return_value = {
            "status": "not_found",
            "source_id": "cam1",
        }
        resp = client.post("/sources/cam1/stop")
        assert resp.status_code == 404


class TestRestartSource:
    def test_restart_success(self, client, mock_mgr):
        mock_pipeline = MagicMock()
        mock_mgr.get_source_status.return_value = {
            "source_id": "cam1",
            "status": "online",
            "running": True,
        }
        mock_mgr._pipelines = {"cam1": mock_pipeline}
        resp = client.post("/sources/cam1/restart")
        assert resp.status_code == 200
        assert resp.json()["status"] == "restarted"

    def test_restart_not_found(self, client, mock_mgr):
        mock_mgr.get_source_status.return_value = None
        resp = client.post("/sources/nonexistent/restart")
        assert resp.status_code == 404
