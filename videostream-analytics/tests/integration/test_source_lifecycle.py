"""Integration tests: source registration, listing, stop, restart lifecycle."""

import time

import pytest
import httpx


@pytest.mark.integration
class TestSourceLifecycle:
    def test_register_source(self, http_client, analytics_url, rtsp_url):
        resp = http_client.post(f"{analytics_url}/register_source", json={
            "source_id": "test_child",
            "rtsp_url": rtsp_url,
            "use_case": "child_safety",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "started"
        assert data["source_id"] == "test_child"

    def test_list_sources_after_register(self, http_client, analytics_url, rtsp_url):
        # Register first
        http_client.post(f"{analytics_url}/register_source", json={
            "source_id": "test_child_list",
            "rtsp_url": rtsp_url,
            "use_case": "child_safety",
        })
        time.sleep(1)

        resp = http_client.get(f"{analytics_url}/sources")
        assert resp.status_code == 200
        sources = resp.json()["sources"]
        source_ids = [s["source_id"] for s in sources]
        assert "test_child_list" in source_ids

    def test_get_source_status(self, http_client, analytics_url, rtsp_url):
        http_client.post(f"{analytics_url}/register_source", json={
            "source_id": "test_child_status",
            "rtsp_url": rtsp_url,
            "use_case": "child_safety",
        })
        time.sleep(2)

        resp = http_client.get(f"{analytics_url}/sources/test_child_status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source_id"] == "test_child_status"
        assert data["running"] is True

    def test_stop_source(self, http_client, analytics_url, rtsp_url):
        http_client.post(f"{analytics_url}/register_source", json={
            "source_id": "test_child_stop",
            "rtsp_url": rtsp_url,
            "use_case": "child_safety",
        })
        time.sleep(1)

        resp = http_client.post(f"{analytics_url}/sources/test_child_stop/stop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "stopped"

    def test_stop_nonexistent_returns_404(self, http_client, analytics_url):
        resp = http_client.post(f"{analytics_url}/sources/nonexistent_cam/stop")
        assert resp.status_code == 404

    def test_register_duplicate_returns_already_running(self, http_client, analytics_url, rtsp_url):
        http_client.post(f"{analytics_url}/register_source", json={
            "source_id": "test_child_dup",
            "rtsp_url": rtsp_url,
            "use_case": "child_safety",
        })
        time.sleep(1)

        resp = http_client.post(f"{analytics_url}/register_source", json={
            "source_id": "test_child_dup",
            "rtsp_url": rtsp_url,
            "use_case": "child_safety",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "already_running"

    def test_unregister_source(self, http_client, analytics_url, rtsp_url):
        http_client.post(f"{analytics_url}/register_source", json={
            "source_id": "test_child_unreg",
            "rtsp_url": rtsp_url,
            "use_case": "child_safety",
        })
        time.sleep(1)

        resp = http_client.request("DELETE", f"{analytics_url}/unregister_source", json={
            "source_id": "test_child_unreg",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "stopped"
