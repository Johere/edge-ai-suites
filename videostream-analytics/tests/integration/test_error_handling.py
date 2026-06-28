"""Integration tests: error handling scenarios."""

import time

import pytest
import httpx

from .conftest import wait_for_events


@pytest.mark.integration
class TestErrorHandling:
    def test_invalid_rtsp_url_pipeline_reconnects(self, http_client, analytics_url):
        """Registering with an invalid RTSP URL should not crash the service."""
        resp = http_client.post(f"{analytics_url}/register_source", json={
            "source_id": "bad_cam",
            "rtsp_url": "rtsp://nonexistent-host:8554/invalid",
            "use_case": "test",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "started"

        # Wait for pipeline to attempt connection
        time.sleep(5)

        # Service should still be healthy
        health = http_client.get(f"{analytics_url}/health")
        assert health.status_code == 200

        # Source should show reconnecting or error status
        status = http_client.get(f"{analytics_url}/sources/bad_cam")
        assert status.status_code == 200
        assert status.json()["source_id"] == "bad_cam"

        # Cleanup
        http_client.post(f"{analytics_url}/sources/bad_cam/stop")

    def test_register_duplicate_while_running(self, http_client, analytics_url, rtsp_url):
        """Re-registering a running source should return already_running."""
        http_client.post(f"{analytics_url}/register_source", json={
            "source_id": "dup_cam",
            "rtsp_url": rtsp_url,
            "use_case": "test",
        })
        time.sleep(2)

        resp = http_client.post(f"{analytics_url}/register_source", json={
            "source_id": "dup_cam",
            "rtsp_url": rtsp_url,
            "use_case": "test",
        })
        assert resp.json()["status"] == "already_running"

        # Cleanup
        http_client.post(f"{analytics_url}/sources/dup_cam/stop")

    def test_unregister_nonexistent_returns_404(self, http_client, analytics_url):
        """Unregistering a source that doesn't exist should return 404."""
        resp = http_client.request("DELETE", f"{analytics_url}/unregister_source", json={
            "source_id": "ghost_cam",
        })
        assert resp.status_code == 404

    def test_service_healthy_after_errors(self, http_client, analytics_url, rtsp_url):
        """After error scenarios, service should still function normally."""
        # Register a bad source
        http_client.post(f"{analytics_url}/register_source", json={
            "source_id": "error_cam",
            "rtsp_url": "rtsp://127.0.0.1:9999/nonexistent",
            "use_case": "test",
        })
        time.sleep(3)

        # Service should still accept new valid sources
        resp = http_client.post(f"{analytics_url}/register_source", json={
            "source_id": "good_cam",
            "rtsp_url": rtsp_url,
            "use_case": "test",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "started"

        # Cleanup
        http_client.post(f"{analytics_url}/sources/error_cam/stop")
        http_client.post(f"{analytics_url}/sources/good_cam/stop")
