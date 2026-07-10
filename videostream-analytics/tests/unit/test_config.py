"""Tests for configuration loading and validation."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from shared.config import (
    AppConfig,
    MotionConfig,
    SegmentConfig,
    WebhookConfig,
    SourceConfig,
    expand_path,
    load_config,
)

from tests.conftest import FIXTURES_DIR


class TestExpandPath:
    def test_expand_tilde(self):
        result = expand_path("~/foo/bar")
        assert result == os.path.expanduser("~/foo/bar")
        assert "~" not in result

    def test_expand_env_var(self):
        with patch.dict(os.environ, {"MY_TEST_DIR": "/opt/test"}):
            result = expand_path("$MY_TEST_DIR/data")
            assert result == "/opt/test/data"

    def test_expand_home_env(self):
        result = expand_path("$HOME/videos")
        assert result == os.environ["HOME"] + "/videos"


class TestLoadConfig:
    def test_load_from_valid_yaml(self):
        config = load_config(str(FIXTURES_DIR / "test_config.yaml"))
        assert config.server.host == "127.0.0.1"
        assert config.server.port == 8999
        assert config.webhook.url == "http://localhost:9999/events"
        assert config.webhook.timeout == 5
        assert config.webhook.retry_attempts == 2
        assert config.defaults.motion.diff_threshold == 25

    def test_load_nonexistent_returns_defaults(self):
        config = load_config("/nonexistent/path/config.yaml")
        assert config.server.port == 8999
        assert config.server.host == "0.0.0.0"
        assert config.webhook.url == "http://localhost:18800/events"

    def test_load_from_env_var(self, tmp_path):
        cfg_file = tmp_path / "env_config.yaml"
        cfg_file.write_text("server:\n  port: 7777\n")
        with patch.dict(os.environ, {"VIDEOSTREAM_CONFIG": str(cfg_file)}):
            config = load_config(None)
            assert config.server.port == 7777

    def test_data_dir_expanded(self):
        config = load_config(str(FIXTURES_DIR / "test_config.yaml"))
        assert "~" not in config.data_dir
        assert config.data_dir == "/tmp/videostream-test-data"


class TestConfigModels:
    def test_motion_config_defaults(self):
        cfg = MotionConfig()
        assert cfg.diff_threshold == 25
        assert cfg.area_ratio == 0.015
        assert cfg.stable_frames == 30

    def test_segment_config_defaults(self):
        cfg = SegmentConfig()
        assert cfg.max_duration == 10.0
        assert cfg.min_duration == 1.0

    def test_webhook_config_custom(self):
        cfg = WebhookConfig(url="http://example.com/events", timeout=30, retry_attempts=5)
        assert cfg.url == "http://example.com/events"
        assert cfg.timeout == 30
        assert cfg.retry_attempts == 5

    def test_source_config_requires_fields(self):
        src = SourceConfig(source_id="cam1", source_url="rtsp://localhost:8554/live/test")
        assert src.source_id == "cam1"
        assert src.source_url == "rtsp://localhost:8554/live/test"
        # Phase 7: source_url surfaces via legacy rtsp_url property too.
        assert src.rtsp_url == src.source_url
        assert src.motion is None
        assert src.data_dir is None
