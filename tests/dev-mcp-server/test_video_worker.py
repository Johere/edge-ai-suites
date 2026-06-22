#!/usr/bin/env python3
"""Test Case 5: Video Worker 链路 — task-poller → VLM mock → DB update + alert creation.

Spawns a mock VLM service and a Node.js video-worker script to test the full pipeline.
"""

import json
import sys
import time
import sqlite3
import subprocess
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conftest import get_temp_dir, cleanup_dir, init_test_db, TestResult, REPO_ROOT

MOCK_VLM_PORT = 18292
vlm_call_count = 0


class MockVLMHandler(BaseHTTPRequestHandler):
    """Mock VLM service that returns a fixed summary response."""

    def do_POST(self):
        global vlm_call_count
        if self.path == "/v1/summary":
            vlm_call_count += 1
            content_length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(content_length)

            response = {
                "summary": "Child was observed jumping off a chair onto the floor.",
                "events": [
                    {"event": "child_jumping", "severity": "high", "desc": "Child jumped from chair"}
                ],
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        if self.path == "/v1/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress logs


def start_mock_vlm() -> HTTPServer:
    """Start mock VLM service in a background thread."""
    server = HTTPServer(("127.0.0.1", MOCK_VLM_PORT), MockVLMHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def start_worker_script(db_path: str, vlm_url: str) -> subprocess.Popen:
    """Start a Node.js script that mimics video-worker: poll DB → call VLM → update DB."""
    script = f"""
const Database = require("better-sqlite3");
const db = new Database("{db_path}");
db.pragma("journal_mode = WAL");
db.pragma("foreign_keys = ON");

async function poll() {{
  const task = db.prepare(
    "SELECT * FROM video_summary_tasks WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1"
  ).get();
  if (!task) return;

  db.prepare("UPDATE video_summary_tasks SET status = 'processing' WHERE id = ?").run(task.id);

  try {{
    const res = await fetch("{vlm_url}/v1/summary", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ videoUrl: task.video_path, taskId: String(task.id) }}),
    }});
    const data = await res.json();

    db.prepare(
      "UPDATE video_summary_tasks SET status = 'completed', summary = ?, completed_at = datetime('now') WHERE id = ?"
    ).run(data.summary, task.id);

    if (data.events) {{
      for (const evt of data.events) {{
        db.prepare(
          "INSERT INTO alerts (source_id, event, severity, description, acked) VALUES (?, ?, ?, ?, 0)"
        ).run(task.monitor_id, evt.event, evt.severity, evt.desc || "");
      }}
    }}
    console.log("DONE:" + task.id);
  }} catch (err) {{
    db.prepare(
      "UPDATE video_summary_tasks SET status = 'failed', summary = ?, completed_at = datetime('now') WHERE id = ?"
    ).run(err.message, task.id);
    console.log("FAIL:" + task.id);
  }}
}}

const interval = setInterval(poll, 500);
setTimeout(() => {{
  clearInterval(interval);
  db.close();
  process.exit(0);
}}, 4000);
"""
    proc = subprocess.Popen(
        ["node", "-e", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(REPO_ROOT),
    )
    return proc


def main():
    global vlm_call_count
    print("\n=== Test: Video Worker ===\n")
    t = TestResult("Video Worker")

    tmp = get_temp_dir("worker")
    db_path = str(tmp / "test.db")
    conn = init_test_db(db_path)

    # Setup: register monitor and create pending task
    conn.execute(
        "INSERT INTO monitors (id, name, source_url, status, use_case_id) VALUES (?, ?, ?, ?, ?)",
        ("cam-01", "Test Camera", "rtsp://test/stream", "online", "child_safety"),
    )
    conn.execute(
        "INSERT INTO video_summary_tasks (monitor_id, video_path, status) VALUES (?, ?, ?)",
        ("cam-01", "segments/cam-01/clip-001.mp4", "pending"),
    )
    conn.commit()
    conn.close()

    # Start mock VLM
    vlm_server = start_mock_vlm()
    vlm_url = f"http://127.0.0.1:{MOCK_VLM_PORT}"

    # Start worker
    proc = start_worker_script(db_path, vlm_url)

    # Wait for worker to finish (max 5s)
    try:
        proc.wait(timeout=6)
    except subprocess.TimeoutExpired:
        proc.terminate()

    # Verify results
    conn = sqlite3.connect(db_path)

    t.check(vlm_call_count >= 1, f"VLM service was called (count: {vlm_call_count})")

    task = conn.execute("SELECT status, summary, completed_at FROM video_summary_tasks WHERE id = 1").fetchone()
    t.check_equal(task[0], "completed", "Task status = completed")
    t.check("jumping" in (task[1] or ""), "Task summary contains VLM response")
    t.check(task[2] is not None, "completedAt is set")

    alerts = conn.execute("SELECT * FROM alerts WHERE source_id = ?", ("cam-01",)).fetchall()
    t.check(len(alerts) >= 1, f"Alert created in DB (count: {len(alerts)})")
    t.check_equal(alerts[0][2], "child_jumping", "Alert event = child_jumping")
    t.check_equal(alerts[0][3], "high", "Alert severity = high")

    pending = conn.execute(
        "SELECT * FROM video_summary_tasks WHERE monitor_id = ? AND status = 'pending'", ("cam-01",)
    ).fetchall()
    t.check_equal(len(pending), 0, "No pending tasks remaining")

    conn.close()
    vlm_server.shutdown()
    cleanup_dir(tmp)

    passed = t.summary()
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
