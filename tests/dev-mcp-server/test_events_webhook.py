#!/usr/bin/env python3
"""Test Case 4: Events Webhook — POST /events 创建 pending task, GET /health。

启动 MCP Server 的 events-endpoint 子进程 (Node.js)，通过 HTTP 验证。
"""

import json
import sys
import time
import sqlite3
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conftest import get_temp_dir, cleanup_dir, init_test_db, TestResult, REPO_ROOT

EVENTS_PORT = 13201


def start_mock_events_server(db_path: str, port: int) -> subprocess.Popen:
    """Start a minimal Node.js events endpoint for testing."""
    script = f"""
const {{ createServer }} = require("node:http");
const Database = require("better-sqlite3");

const db = new Database("{db_path}");
db.pragma("journal_mode = WAL");
db.pragma("foreign_keys = ON");

const server = createServer((req, res) => {{
  if (req.method === "POST" && req.url === "/events") {{
    let body = "";
    req.on("data", (chunk) => {{ body += chunk; }});
    req.on("end", () => {{
      try {{
        const event = JSON.parse(body);
        if ((event.type === "motion" || event.type === "summary_completed") && event.payload.video_path) {{
          db.prepare("INSERT INTO video_summary_tasks (monitor_id, video_path, status) VALUES (?, ?, 'pending')")
            .run(event.sourceId, event.payload.video_path);
        }}
        res.writeHead(200, {{ "Content-Type": "application/json" }});
        res.end(JSON.stringify({{ status: "ok" }}));
      }} catch (err) {{
        res.writeHead(400, {{ "Content-Type": "application/json" }});
        res.end(JSON.stringify({{ error: err.message }}));
      }}
    }});
  }} else if (req.method === "GET" && req.url === "/health") {{
    res.writeHead(200, {{ "Content-Type": "application/json" }});
    res.end(JSON.stringify({{ status: "healthy" }}));
  }} else {{
    res.writeHead(404);
    res.end();
  }}
}});

server.listen({port}, () => {{
  console.log("READY");
}});
"""
    proc = subprocess.Popen(
        ["node", "-e", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(REPO_ROOT),
    )
    # Wait for server to be ready
    for line in proc.stdout:
        if b"READY" in line:
            break
    return proc


def http_request(url: str, method: str = "GET", data: dict | None = None) -> tuple[int, dict | str]:
    """Simple HTTP request helper."""
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            content = resp.read().decode()
            try:
                return resp.status, json.loads(content)
            except json.JSONDecodeError:
                return resp.status, content
    except urllib.error.HTTPError as e:
        content = e.read().decode()
        try:
            return e.code, json.loads(content)
        except json.JSONDecodeError:
            return e.code, content


def main():
    print("\n=== Test: Events Webhook ===\n")
    t = TestResult("Events Webhook")

    tmp = get_temp_dir("events")
    db_path = str(tmp / "test.db")
    conn = init_test_db(db_path)

    # Register a monitor
    conn.execute(
        "INSERT INTO monitors (id, name, source_url, status, use_case_id) VALUES (?, ?, ?, ?, ?)",
        ("cam-01", "Test Camera", "rtsp://test/stream", "online", "child_safety"),
    )
    conn.commit()
    conn.close()

    # Start events server
    proc = start_mock_events_server(db_path, EVENTS_PORT)
    base_url = f"http://localhost:{EVENTS_PORT}"

    try:
        time.sleep(0.3)

        # --- GET /health ---
        status, body = http_request(f"{base_url}/health")
        t.check_equal(status, 200, "GET /health returns 200")
        t.check_equal(body["status"], "healthy", "Health response body correct")

        # --- POST /events with motion event ---
        motion_event = {
            "sourceId": "cam-01",
            "type": "motion",
            "timestamp": "2026-06-10T10:00:00Z",
            "payload": {"video_path": "segments/cam-01/clip-001.mp4"},
        }
        status, body = http_request(f"{base_url}/events", method="POST", data=motion_event)
        t.check_equal(status, 200, "POST /events returns 200")

        # Verify task created in DB
        conn2 = sqlite3.connect(db_path)
        tasks = conn2.execute(
            "SELECT * FROM video_summary_tasks WHERE monitor_id = ? AND status = 'pending'", ("cam-01",)
        ).fetchall()
        t.check_equal(len(tasks), 1, "Motion event created 1 pending task")
        t.check_equal(tasks[0][2], "segments/cam-01/clip-001.mp4", "Task has correct video path")
        t.check_equal(tasks[0][1], "cam-01", "Task has correct monitor ID")

        # --- POST /events with static event (no video_path) ---
        static_event = {
            "sourceId": "cam-01",
            "type": "static",
            "timestamp": "2026-06-10T10:01:00Z",
            "payload": {},
        }
        http_request(f"{base_url}/events", method="POST", data=static_event)
        tasks_after = conn2.execute(
            "SELECT * FROM video_summary_tasks WHERE monitor_id = ? AND status = 'pending'", ("cam-01",)
        ).fetchall()
        t.check_equal(len(tasks_after), 1, "Static event without video_path does not create task")

        # --- POST /events with invalid JSON ---
        req = urllib.request.Request(
            f"{base_url}/events",
            data=b"not json",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req)
            t.check(False, "Invalid JSON should return error")
        except urllib.error.HTTPError as e:
            t.check_equal(e.code, 400, "Invalid JSON returns 400")

        # --- 404 for unknown path ---
        try:
            urllib.request.urlopen(f"{base_url}/unknown")
            t.check(False, "Unknown path should return 404")
        except urllib.error.HTTPError as e:
            t.check_equal(e.code, 404, "Unknown path returns 404")

        conn2.close()

    finally:
        proc.terminate()
        proc.wait(timeout=5)

    cleanup_dir(tmp)
    passed = t.summary()
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
