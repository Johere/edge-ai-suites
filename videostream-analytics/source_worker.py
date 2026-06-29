"""Manages registered video sources and their pipelines."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from shared.config import (
    AppConfig,
    SourceConfig,
    WebhookConfig,
    MotionConfig,
    SegmentConfig,
    PrefilterConfig,
    RecordingConfig,
    HealthConfig,
    expand_path,
)
from stream_monitor.rtsp_monitor import StreamPipeline
from stream_monitor.continuous_recorder import ContinuousRecorder
from sinks import EventSink, WebhookSink

logger = logging.getLogger(__name__)


@dataclass
class SourceBundle:
    """Per-source state: motion pipeline + optional continuous recorder + sink."""

    pipeline: StreamPipeline
    recorder: ContinuousRecorder | None
    sink: EventSink
    data_dir: str


class SourceManager:
    def __init__(self, config: AppConfig):
        self.config = config
        self._default_sink: EventSink = WebhookSink(config.webhook)
        self._bundles: dict[str, SourceBundle] = {}

    def _resolve_data_dir(self, source: SourceConfig) -> str:
        if source.data_dir:
            return expand_path(source.data_dir)
        return os.path.join(expand_path(self.config.data_dir), source.source_id)

    def _build_sink(self, source: SourceConfig) -> EventSink:
        if source.webhook_url:
            return WebhookSink(WebhookConfig(url=source.webhook_url))
        return self._default_sink

    def register_source(self, source: SourceConfig) -> dict[str, Any]:
        """Register and start a new video source pipeline."""
        existing = self._bundles.get(source.source_id)
        if existing is not None:
            if existing.pipeline.is_running:
                return {"status": "already_running", "source_id": source.source_id}
            # Re-register: tear down old bundle so resources are released.
            self._teardown_bundle(source.source_id, existing)

        sink = self._build_sink(source)
        data_dir = self._resolve_data_dir(source)
        os.makedirs(data_dir, exist_ok=True)

        pipeline = StreamPipeline(
            source=source,
            defaults=self.config.defaults,
            data_dir=data_dir,
            sink=sink,
            on_remove_callback=self._handle_source_removed,
        )

        recorder: ContinuousRecorder | None = None
        recording_cfg = source.recording or self.config.defaults.recording
        if recording_cfg.enabled:
            recorder = ContinuousRecorder(
                source=source,
                recording_cfg=recording_cfg,
                data_dir=data_dir,
                sink=sink,
            )

        bundle = SourceBundle(
            pipeline=pipeline, recorder=recorder, sink=sink, data_dir=data_dir
        )
        self._bundles[source.source_id] = bundle
        pipeline.start()
        if recorder is not None:
            recorder.start()

        logger.info(
            "Registered source: %s (%s) data_dir=%s recording=%s",
            source.source_id,
            source.source_url,
            data_dir,
            recording_cfg.enabled,
        )
        return {
            "status": "started",
            "source_id": source.source_id,
            "source_url": source.source_url,
            "data_dir": data_dir,
        }

    def _teardown_bundle(self, source_id: str, bundle: SourceBundle) -> None:
        """Stop pipeline + recorder, close per-source sink if not default."""
        bundle.pipeline.stop()
        if bundle.recorder is not None:
            bundle.recorder.stop()
        if bundle.sink is not self._default_sink:
            try:
                bundle.sink.close()
            except Exception as e:
                logger.warning("[%s] sink close error: %s", source_id, e)

    def unregister_source(self, source_id: str) -> dict[str, Any]:
        bundle = self._bundles.pop(source_id, None)
        if bundle is None:
            return {"status": "not_found", "source_id": source_id}
        self._teardown_bundle(source_id, bundle)
        logger.info("Unregistered source: %s", source_id)
        return {"status": "stopped", "source_id": source_id}

    def _handle_source_removed(self, source_id: str):
        """Callback: pipeline triggered 'remove' recovery strategy."""
        bundle = self._bundles.pop(source_id, None)
        if bundle is not None:
            # pipeline already self-stopped; clean up recorder + sink
            if bundle.recorder is not None:
                bundle.recorder.stop()
            if bundle.sink is not self._default_sink:
                try:
                    bundle.sink.close()
                except Exception:
                    pass
        logger.info("Source auto-removed by health policy: %s", source_id)

    def update_pipeline_config(
        self,
        source_id: str,
        motion: MotionConfig | None = None,
        segment: SegmentConfig | None = None,
        prefilter: PrefilterConfig | None = None,
        recording: RecordingConfig | None = None,
        health: HealthConfig | None = None,
    ) -> dict[str, Any]:
        """Hot-update pipeline config (stop + update + restart)."""
        bundle = self._bundles.get(source_id)
        if bundle is None:
            return {"status": "not_found", "source_id": source_id}

        bundle.pipeline.stop()
        bundle.pipeline.update_pipeline_config(
            motion=motion,
            segment=segment,
            prefilter=prefilter,
            health=health,
        )
        bundle.pipeline.start()

        if recording is not None:
            new_enabled = recording.enabled
            if bundle.recorder is not None:
                bundle.recorder.stop()
                if new_enabled:
                    bundle.recorder = ContinuousRecorder(
                        source=bundle.pipeline.source,
                        recording_cfg=recording,
                        data_dir=bundle.data_dir,
                        sink=bundle.sink,
                    )
                    bundle.recorder.start()
                else:
                    bundle.recorder = None
            elif new_enabled:
                bundle.recorder = ContinuousRecorder(
                    source=bundle.pipeline.source,
                    recording_cfg=recording,
                    data_dir=bundle.data_dir,
                    sink=bundle.sink,
                )
                bundle.recorder.start()

        logger.info("Pipeline config updated: %s", source_id)
        return {"status": "updated", "source_id": source_id}

    def pause_source(self, source_id: str) -> dict[str, Any]:
        bundle = self._bundles.get(source_id)
        if bundle is None:
            return {"status": "not_found", "source_id": source_id}
        if not bundle.pipeline.is_running:
            return {"status": "not_running", "source_id": source_id}
        bundle.pipeline.pause()
        if bundle.recorder is not None:
            bundle.recorder.pause()
        return {"status": "paused", "source_id": source_id}

    def resume_source(self, source_id: str) -> dict[str, Any]:
        bundle = self._bundles.get(source_id)
        if bundle is None:
            return {"status": "not_found", "source_id": source_id}
        if not bundle.pipeline.is_running:
            return {"status": "not_running", "source_id": source_id}
        bundle.pipeline.resume()
        if bundle.recorder is not None:
            bundle.recorder.resume()
        return {"status": "online", "source_id": source_id}

    def get_sources(self) -> list[dict[str, Any]]:
        """List all registered sources with their status."""
        return [
            self._describe_bundle(sid, b) for sid, b in self._bundles.items()
        ]

    def get_source_status(self, source_id: str) -> dict[str, Any] | None:
        bundle = self._bundles.get(source_id)
        if bundle is None:
            return None
        return self._describe_bundle(source_id, bundle)

    def _describe_bundle(self, source_id: str, bundle: SourceBundle) -> dict[str, Any]:
        pipe = bundle.pipeline
        return {
            "source_id": source_id,
            "source_url": pipe.source.source_url,
            "data_dir": bundle.data_dir,
            "status": pipe.status,
            "running": pipe.is_running,
            "recording_enabled": bundle.recorder is not None,
            "health": pipe.health_info,
        }

    def stop_all(self):
        for source_id, bundle in self._bundles.items():
            self._teardown_bundle(source_id, bundle)
        self._bundles.clear()
        self._default_sink.close()
        logger.info("All sources stopped")

    @property
    def _pipelines(self) -> dict[str, StreamPipeline]:
        """Backwards-compat shim — some tests/refs still use _pipelines."""
        return {sid: b.pipeline for sid, b in self._bundles.items()}
