"""Webhook client for posting events to the MCP Server."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from .config import WebhookConfig

logger = logging.getLogger(__name__)


class WebhookClient:
    def __init__(self, config: WebhookConfig):
        self.url = config.url
        self.timeout = config.timeout
        self.retry_attempts = config.retry_attempts
        self.retry_delay = config.retry_delay
        self._client = httpx.Client(timeout=self.timeout)

    def close(self):
        self._client.close()

    def send_event(self, payload: dict[str, Any]) -> bool:
        for attempt in range(self.retry_attempts):
            try:
                resp = self._client.post(self.url, json=payload)
                if resp.status_code < 400:
                    return True
                logger.warning(
                    "Webhook returned %d: %s", resp.status_code, resp.text[:200]
                )
            except httpx.HTTPError as e:
                logger.warning(
                    "Webhook attempt %d/%d failed: %s",
                    attempt + 1,
                    self.retry_attempts,
                    e,
                )
            if attempt < self.retry_attempts - 1:
                time.sleep(self.retry_delay)
        return False

    def send_motion_event(
        self,
        source_id: str,
        start_time: str,
        end_time: str,
        duration_seconds: float,
        clip_path: str,
        clip_size_bytes: int = 0,
        trajectory_region_xyxy: list[float] | None = None,
    ) -> bool:
        payload: dict[str, Any] = {
            "source_id": source_id,
            "event_type": "motion",
            "start_time": start_time,
            "end_time": end_time,
            "duration_seconds": duration_seconds,
            "clip_path": clip_path,
            "clip_size_bytes": clip_size_bytes,
        }
        if trajectory_region_xyxy:
            payload["trajectory_region_xyxy"] = trajectory_region_xyxy
        return self.send_event(payload)

    def send_recording_event(
        self,
        source_id: str,
        file_path: str,
        start_time: str,
        end_time: str,
        duration_seconds: float,
        file_size_bytes: int = 0,
    ) -> bool:
        return self.send_event(
            {
                "source_id": source_id,
                "event_type": "recording",
                "file_path": file_path,
                "start_time": start_time,
                "end_time": end_time,
                "duration_seconds": duration_seconds,
                "file_size_bytes": file_size_bytes,
            }
        )

    def send_static_event(
        self,
        source_id: str,
        start_time: str,
        end_time: str,
        duration_seconds: float,
    ) -> bool:
        return self.send_event(
            {
                "source_id": source_id,
                "event_type": "static",
                "start_time": start_time,
                "end_time": end_time,
                "duration_seconds": duration_seconds,
            }
        )

    def send_status_event(self, source_id: str, status: str) -> bool:
        return self.send_event(
            {
                "source_id": source_id,
                "event_type": "status",
                "status": status,
            }
        )
