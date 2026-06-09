"""Integration tests: full pipeline — RTSP → motion detect → webhook events."""

import time

import pytest
import httpx

from .conftest import wait_for_events


@pytest.mark.integration
class TestMotionToWebhook:
    @pytest.fixture(autouse=True)
    def register_source(self, http_client, analytics_url, rtsp_url):
        """Register a test source before each test, unregister after."""
        http_client.post(f"{analytics_url}/register_source", json={
            "source_id": "test_motion",
            "rtsp_url": rtsp_url,
            "use_case": "child_safety",
        })
        time.sleep(2)
        yield
        try:
            http_client.post(f"{analytics_url}/sources/test_motion/stop")
        except httpx.HTTPError:
            pass

    def test_status_online_event_received(self, http_client, webhook_url):
        """After registering, a status='online' event should be posted to webhook."""
        events = wait_for_events(
            http_client, webhook_url, event_type="status", min_count=1, timeout=15
        )
        assert len(events) >= 1
        online_events = [e for e in events if e.get("status") == "online"]
        assert len(online_events) >= 1
        assert online_events[0]["source_id"] == "test_motion"

    def test_motion_events_received(self, http_client, webhook_url):
        """After pipeline runs, motion events should arrive (video has motion after ~40s)."""
        events = wait_for_events(
            http_client, webhook_url, event_type="motion", min_count=1, timeout=60
        )
        assert len(events) >= 1, "No motion events received within 60s"

    def test_motion_event_payload_complete(self, http_client, webhook_url):
        """Motion event payload should have all required fields."""
        events = wait_for_events(
            http_client, webhook_url, event_type="motion", min_count=1, timeout=60
        )
        assert len(events) >= 1
        event = events[0]
        assert event["source_id"] == "test_motion"
        assert event["event_type"] == "motion"
        assert "start_time" in event
        assert "end_time" in event
        assert "duration_seconds" in event
        assert "clip_path" in event
        assert event["duration_seconds"] > 0
        assert event["clip_path"].endswith(".mp4")

    def test_motion_event_duration_within_range(self, http_client, webhook_url):
        """Motion event duration should be within configured segment interval."""
        events = wait_for_events(
            http_client, webhook_url, event_type="motion", min_count=1, timeout=60
        )
        assert len(events) >= 1
        for event in events:
            duration = event["duration_seconds"]
            # Default segment interval is 10s, min_duration 1s
            assert 1.0 <= duration <= 11.0, f"Duration {duration}s out of range"

    def test_multiple_motion_events_over_time(self, http_client, webhook_url):
        """Running long enough should produce multiple motion events."""
        events = wait_for_events(
            http_client, webhook_url, event_type="motion", min_count=2, timeout=90
        )
        assert len(events) >= 2, f"Expected >=2 motion events, got {len(events)}"
