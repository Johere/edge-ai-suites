"""Integration test fixtures — assumes services are running on host."""

import time

import httpx
import pytest

ANALYTICS_URL = "http://localhost:8999"
WEBHOOK_URL = "http://localhost:9999"
RTSP_URL = "rtsp://localhost:8554/live/child"


@pytest.fixture(scope="session")
def analytics_url():
    return ANALYTICS_URL


@pytest.fixture(scope="session")
def webhook_url():
    return WEBHOOK_URL


@pytest.fixture(scope="session")
def rtsp_url():
    return RTSP_URL


@pytest.fixture(scope="session")
def http_client():
    client = httpx.Client(timeout=10)
    yield client
    client.close()


@pytest.fixture(autouse=True)
def clear_webhook_events(http_client, webhook_url):
    """Clear recorded events before each test."""
    try:
        http_client.delete(f"{webhook_url}/recorded_events")
    except httpx.HTTPError:
        pass
    yield


def wait_for_events(
    http_client: httpx.Client,
    webhook_url: str,
    event_type: str | None = None,
    min_count: int = 1,
    timeout: float = 30.0,
    poll_interval: float = 1.0,
) -> list[dict]:
    """Poll the mock webhook server until min_count events arrive or timeout."""
    endpoint = f"{webhook_url}/recorded_events"
    if event_type:
        endpoint = f"{webhook_url}/recorded_events/{event_type}"

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = http_client.get(endpoint)
            if resp.status_code == 200:
                data = resp.json()
                if data["count"] >= min_count:
                    return data["events"]
        except httpx.HTTPError:
            pass
        time.sleep(poll_interval)

    # Final attempt
    resp = http_client.get(endpoint)
    return resp.json().get("events", [])
