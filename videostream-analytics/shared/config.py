"""Configuration models for videostream-analytics."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field


class MotionConfig(BaseModel):
    enabled: bool = True
    diff_threshold: int = 25
    area_ratio: float = 0.015
    stable_frames: int = 30


class SegmentConfig(BaseModel):
    """Segment cut-over rule.

    `max_duration` — hard ceiling on segment length in seconds; when a running
    segment reaches this, it is closed and a new one starts.
    """

    model_config = ConfigDict(extra="forbid")

    max_duration: float = 10.0
    min_duration: float = 1.0


class RecordingConfig(BaseModel):
    """Fixed-duration continuous recording config.

    `interval_seconds` is the canonical field MCP sends. `interval` is kept as
    a legacy alias accepted on input but written as `interval_seconds`.
    """

    model_config = ConfigDict(populate_by_name=True)

    enabled: bool = True
    interval_seconds: int = Field(default=60, alias="interval")
    fps: int = 15
    retention_days: int = 5


class RoiConfig(BaseModel):
    """ROI crop configuration (Phase 9, child_safety).

    Top-level pipeline block, at the same nesting depth as `prefilter`.
    When enabled and prefilter accumulates a `trajectory_region_xyxy`, the
    pipeline writes a `<clip>_input.mp4` next to the original segment and
    points `summary_clip_input` there. `auto_split_area` triggers early
    segment cuts when the union bbox grows beyond the fraction (avoids one
    over-large crop on long fast-moving events).
    """

    enabled: bool = False
    mode: str = "crop"  # crop | highlight | crop_and_concat
    expand: float = 0.25
    auto_split_area: float = 0.0  # 0 disables early-split


class PrefilterConfig(BaseModel):
    enabled: bool = False
    model_path: str = ""
    target_classes: list[str] = Field(default_factory=lambda: ["person"])
    min_confidence: float = 0.4
    min_frames_hit: int = 2
    detect_fps: float = 2.0
    device: str = "CPU"
    # Long-side resize target for pre-inference frame downscaling (0 disables).
    # Consumed by prefilter_yolo._resize_long_side when > 0.
    long_side: int = 0


class HealthConfig(BaseModel):
    """Per-source health monitoring configuration."""
    max_failures: int = 30
    recovery_strategy: str = "retry"  # "retry" | "pause" | "remove"
    backoff_base: float = 2.0
    backoff_max: float = 120.0


class KeepaliveConfig(BaseModel):
    """Keepalive protocol configuration (Phase 8).

    When `enabled`, the source must receive `POST /sources/{id}/keepalive`
    within `timeout_seconds` or the watchdog auto-pauses it. Default OFF so
    existing integration scripts that don't send keepalive aren't disturbed.
    """

    enabled: bool = False
    timeout_seconds: float = 90.0
    check_interval_seconds: float = 10.0


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
    roi: RoiConfig = Field(default_factory=RoiConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    keepalive: KeepaliveConfig = Field(default_factory=KeepaliveConfig)


class SourceConfig(BaseModel):
    """Per-source configuration provided at registration time.

    Renamed `rtsp_url` → `source_url` and dropped `use_case` as part of the
    Phase 7 hard cutover to match MCP's `analyticsRegister` body.
    """

    source_id: str
    source_url: str
    webhook_url: Optional[str] = None
    data_dir: Optional[str] = None
    motion: Optional[MotionConfig] = None
    segment: Optional[SegmentConfig] = None
    recording: Optional[RecordingConfig] = None
    prefilter: Optional[PrefilterConfig] = None
    roi: Optional[RoiConfig] = None
    health: Optional[HealthConfig] = None
    keepalive: Optional[KeepaliveConfig] = None

    @property
    def rtsp_url(self) -> str:
        """Backwards-compatible accessor — internals still call this."""
        return self.source_url


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
