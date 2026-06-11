"""Manages registered video sources and their pipelines."""

from __future__ import annotations

import logging
from typing import Any

from .shared.config import AppConfig, SourceConfig
from .stream_monitor.rtsp_monitor import StreamPipeline
from .sinks import EventSink, WebhookSink

logger = logging.getLogger(__name__)


class SourceManager:
    def __init__(self, config: AppConfig):
        self.config = config
        self._default_sink: EventSink = WebhookSink(config.webhook)
        self._pipelines: dict[str, StreamPipeline] = {}

    def register_source(self, source: SourceConfig) -> dict[str, Any]:
        """Register and start a new video source pipeline."""
        if source.source_id in self._pipelines:
            existing = self._pipelines[source.source_id]
            if existing.is_running:
                return {
                    "status": "already_running",
                    "source_id": source.source_id,
                }
            # Re-register: stop old and create new
            existing.stop()

        pipeline = StreamPipeline(
            source=source,
            defaults=self.config.defaults,
            data_dir=self.config.data_dir,
            sink=self._default_sink,
        )
        self._pipelines[source.source_id] = pipeline
        pipeline.start()

        logger.info("Registered source: %s (%s)", source.source_id, source.rtsp_url)
        return {
            "status": "started",
            "source_id": source.source_id,
            "rtsp_url": source.rtsp_url,
        }

    def unregister_source(self, source_id: str) -> dict[str, Any]:
        """Stop and remove a source pipeline."""
        pipeline = self._pipelines.pop(source_id, None)
        if pipeline is None:
            return {"status": "not_found", "source_id": source_id}

        pipeline.stop()
        logger.info("Unregistered source: %s", source_id)
        return {"status": "stopped", "source_id": source_id}

    def get_sources(self) -> list[dict[str, Any]]:
        """List all registered sources with their status."""
        return [
            {
                "source_id": sid,
                "rtsp_url": p.rtsp_url,
                "use_case": p.source.use_case,
                "status": p.status,
                "running": p.is_running,
            }
            for sid, p in self._pipelines.items()
        ]

    def get_source_status(self, source_id: str) -> dict[str, Any] | None:
        """Get status of a specific source."""
        pipeline = self._pipelines.get(source_id)
        if not pipeline:
            return None
        return {
            "source_id": source_id,
            "rtsp_url": pipeline.rtsp_url,
            "use_case": pipeline.source.use_case,
            "status": pipeline.status,
            "running": pipeline.is_running,
        }

    def stop_all(self):
        """Stop all pipelines gracefully."""
        for pipeline in self._pipelines.values():
            pipeline.stop()
        self._pipelines.clear()
        self._default_sink.close()
        logger.info("All sources stopped")
