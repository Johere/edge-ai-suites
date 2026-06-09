"""Tests for SourceManager with mocked StreamPipeline."""

from unittest.mock import patch, MagicMock, PropertyMock

import pytest

from src.config import AppConfig, SourceConfig
from src.source_manager import SourceManager


@pytest.fixture
def config():
    return AppConfig()


@pytest.fixture
def mock_pipeline_class():
    with patch("src.source_manager.StreamPipeline") as mock_cls:
        instance = MagicMock()
        instance.is_running = True
        instance.status = "online"
        instance.rtsp_url = "rtsp://localhost:8554/live/test"
        instance.source = SourceConfig(
            source_id="test_cam", rtsp_url="rtsp://localhost:8554/live/test"
        )
        mock_cls.return_value = instance
        yield mock_cls, instance


@pytest.fixture
def manager(config, mock_pipeline_class):
    with patch("src.source_manager.WebhookClient"):
        mgr = SourceManager(config)
    return mgr


class TestSourceManagerRegister:
    def test_register_source_creates_and_starts_pipeline(self, manager, mock_pipeline_class):
        _, instance = mock_pipeline_class
        source = SourceConfig(
            source_id="cam1", rtsp_url="rtsp://localhost:8554/live/cam1"
        )
        result = manager.register_source(source)
        assert result["status"] == "started"
        assert result["source_id"] == "cam1"
        instance.start.assert_called_once()

    def test_register_duplicate_running_returns_already_running(self, manager, mock_pipeline_class):
        _, instance = mock_pipeline_class
        source = SourceConfig(
            source_id="cam1", rtsp_url="rtsp://localhost:8554/live/cam1"
        )
        manager.register_source(source)
        result = manager.register_source(source)
        assert result["status"] == "already_running"

    def test_register_duplicate_stopped_restarts(self, manager, mock_pipeline_class):
        mock_cls, instance = mock_pipeline_class
        source = SourceConfig(
            source_id="cam1", rtsp_url="rtsp://localhost:8554/live/cam1"
        )
        manager.register_source(source)
        # Simulate pipeline stopped
        instance.is_running = False
        result = manager.register_source(source)
        assert result["status"] == "started"
        instance.stop.assert_called()


class TestSourceManagerUnregister:
    def test_unregister_existing_stops_pipeline(self, manager, mock_pipeline_class):
        _, instance = mock_pipeline_class
        source = SourceConfig(
            source_id="cam1", rtsp_url="rtsp://localhost:8554/live/cam1"
        )
        manager.register_source(source)
        result = manager.unregister_source("cam1")
        assert result["status"] == "stopped"
        instance.stop.assert_called()

    def test_unregister_nonexistent_returns_not_found(self, manager):
        result = manager.unregister_source("nonexistent")
        assert result["status"] == "not_found"


class TestSourceManagerQuery:
    def test_get_sources_empty(self, manager):
        sources = manager.get_sources()
        assert sources == []

    def test_get_sources_after_register(self, manager, mock_pipeline_class):
        source = SourceConfig(
            source_id="cam1", rtsp_url="rtsp://localhost:8554/live/cam1"
        )
        manager.register_source(source)
        sources = manager.get_sources()
        assert len(sources) == 1
        assert sources[0]["source_id"] == "cam1"
        assert sources[0]["running"] is True

    def test_get_source_status_existing(self, manager, mock_pipeline_class):
        source = SourceConfig(
            source_id="cam1", rtsp_url="rtsp://localhost:8554/live/cam1"
        )
        manager.register_source(source)
        status = manager.get_source_status("cam1")
        assert status is not None
        assert status["source_id"] == "cam1"
        assert status["running"] is True

    def test_get_source_status_nonexistent(self, manager):
        assert manager.get_source_status("nope") is None


class TestSourceManagerStopAll:
    def test_stop_all_clears_pipelines(self, manager, mock_pipeline_class):
        _, instance = mock_pipeline_class
        source = SourceConfig(
            source_id="cam1", rtsp_url="rtsp://localhost:8554/live/cam1"
        )
        manager.register_source(source)
        manager.stop_all()
        assert manager.get_sources() == []
        instance.stop.assert_called()
