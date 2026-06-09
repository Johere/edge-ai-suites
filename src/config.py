"""Configuration models for videostream-analytics."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class MotionConfig(BaseModel):
    diff_threshold: int = 25
    area_ratio: float = 0.015
    stable_frames: int = 30


class SegmentConfig(BaseModel):
    interval: float = 10.0
    min_duration: float = 1.0


class RecordingConfig(BaseModel):
    interval: int = 60
    fps: int = 15
    retention_days: int = 5


class PrefilterConfig(BaseModel):
    enabled: bool = False
    model_path: str = ""
    target_classes: list[str] = Field(default_factory=lambda: ["person"])
    min_confidence: float = 0.4
    min_frames_hit: int = 2
    detect_fps: float = 2.0
    device: str = "CPU"


class WebhookConfig(BaseModel):
    url: str = "http://localhost:18800/events"
    timeout: int = 10
    retry_attempts: int = 3
    retry_delay: float = 2.0


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8999


class DefaultsConfig(BaseModel):
    motion: MotionConfig = Field(default_factory=MotionConfig)
    segment: SegmentConfig = Field(default_factory=SegmentConfig)
    recording: RecordingConfig = Field(default_factory=RecordingConfig)
    prefilter: PrefilterConfig = Field(default_factory=PrefilterConfig)


class SourceConfig(BaseModel):
    """Per-source configuration provided at registration time."""

    source_id: str
    rtsp_url: str
    use_case: str = "default"
    motion: Optional[MotionConfig] = None
    segment: Optional[SegmentConfig] = None
    recording: Optional[RecordingConfig] = None
    prefilter: Optional[PrefilterConfig] = None


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)
    data_dir: str = "~/.smartbuilding/data"
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    logging: dict = Field(default_factory=lambda: {"level": "INFO"})


def expand_path(p: str) -> str:
    p = os.path.expanduser(p)
    p = os.path.expandvars(p)
    return p


def load_config(config_path: str | None = None) -> AppConfig:
    path = config_path or os.environ.get(
        "VIDEOSTREAM_CONFIG", str(Path("config/config.yaml"))
    )
    if os.path.exists(path):
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
        config = AppConfig(**raw)
    else:
        config = AppConfig()

    config.data_dir = expand_path(config.data_dir)

    # Environment variable overrides
    if webhook_url := os.environ.get("WEBHOOK_URL"):
        config.webhook.url = webhook_url
    if data_dir := os.environ.get("RECORDINGS_DIR"):
        config.data_dir = expand_path(data_dir)

    return config
