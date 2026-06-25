#!/usr/bin/env python3
"""Test: Events Webhook — POST /events protocol validation.

Tests the MCP server events-endpoint against the new webhook protocol:
  motion   → writes events + video_summary_tasks (status conditioned on prefilter)
  static   → writes events only
  recording → writes recordings only
  invalid payload (missing required fields) → returns 200 with warn, no DB write

Uses a minimal inline Node.js server that replicates the events-endpoint logic
(same SQL as the actual implementation) so we can test the protocol without
running the full MCP server stack.
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
from conftest import get_temp_dir, cleanup_dir, TestResult, REPO_ROOT

EVENTS_PORT = 13201

# Minimal Node.js events server implementing the new protocol
NODE_SCRIPT = """
const {{ createServer }} = require("node:http");
const Database = require("better-sqlite3");

const db = new Database("{db_path}");
db.pragma("journal_mode = WAL");
db.pragma("foreign_keys = ON");

db.exec(`
  CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    monitor_id TEXT NOT NULL, motion_type TEXT NOT NULL,
    start_time TEXT NOT NULL, end_time TEXT, duration_seconds REAL,
    event_file_path TEXT,
    prefilter_passed INTEGER, prefilter_classes TEXT,
    prefilter_confidence REAL, trajectory_region TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
  );
  CREATE TABLE IF NOT EXISTS recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    monitor_id TEXT NOT NULL, file_path TEXT NOT NULL,
    start_time TEXT NOT NULL, end_time TEXT NOT NULL,
    duration_seconds REAL, file_size_bytes INTEGER,
    created_at TEXT DEFAULT (datetime('now','localtime'))
  );
  CREATE TABLE IF NOT EXISTS video_summary_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    monitor_id TEXT NOT NULL, event_id INTEGER,
    summary_clip_input TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now','localtime'))
  );
`);

function handleEvent(event) {{
  const p = event.payload || {{}};
  const id = event.sourceId;
  if (event.type === "motion") {{
    if (!p.event_file_path || !p.summary_clip_input || !p.start_time || !p.duration_seconds) return;
    const ev = db.prepare(
      "INSERT INTO events (monitor_id,motion_type,start_time,end_time,duration_seconds,event_file_path,prefilter_passed,prefilter_classes,prefilter_confidence,trajectory_region) VALUES (?,?,?,?,?,?,?,?,?,?)"
    ).run(id,"motion",String(p.start_time),p.end_time||null,Number(p.duration_seconds),
         String(p.event_file_path),
         p.prefilter_passed!==undefined?Number(p.prefilter_passed):null,
         p.prefilter_classes?String(p.prefilter_classes):null,
         p.prefilter_confidence!==undefined?Number(p.prefilter_confidence):null,
         p.trajectory_region?String(p.trajectory_region):null);
    const status = p.prefilter_passed!==undefined && Number(p.prefilter_passed)===0 ? "ignored" : "pending";
    db.prepare("INSERT INTO video_summary_tasks (monitor_id,event_id,summary_clip_input,status) VALUES (?,?,?,?)")
      .run(id,ev.lastInsertRowid,String(p.summary_clip_input),status);
  }} else if (event.type === "static") {{
    if (!p.start_time || !p.duration_seconds) return;
    db.prepare("INSERT INTO events (monitor_id,motion_type,start_time,end_time,duration_seconds) VALUES (?,?,?,?,?)")
      .run(id,"static",String(p.start_time),p.end_time||null,Number(p.duration_seconds));
  }} else if (event.type === "recording") {{
    if (!p.recording_path || !p.recording_start || !p.recording_end) return;
    db.prepare("INSERT INTO recordings (monitor_id,file_path,start_time,end_time,duration_seconds,file_size_bytes) VALUES (?,?,?,?,?,?)")
      .run(id,String(p.recording_path),String(p.recording_start),String(p.recording_end),
           p.duration_seconds?Number(p.duration_seconds):null,
           p.file_size_bytes?Number(p.file_size_bytes):null);
  }}
}}

const server = createServer((req, res) => {{
  if (req.method === "POST" && req.url === "/events") {{
    let body = "";
    req.on("data", c => {{ body += c; }});
    req.on("end", () => {{
      try {{
        const event = JSON.parse(body);
        handleEvent(event);
        res.writeHead(200, {{"Content-Type":"application/json"}});
        res.end(JSON.stringify({{status:"ok"}}));
      }} catch(err) {{
        res.writeHead(400, {{"Content-Type":"application/json"}});
        res.end(JSON.stringify({{error:err.message}}));
      }}
    }});
  }} else if (req.method === "GET" && req.url === "/health") {{
    res.writeHead(200, {{"Content-Type":"application/json"}});
    res.end(JSON.stringify({{status:"healthy"}}));
  }} else {{
    res.writeHead(404); res.end();
  }}
}});

server.listen({port}, () => {{ console.log("READY"); }});
"""


def start_server(db_path: str, port: int) -> subprocess.Popen:
    script = NODE_SCRIPT.format(db_path=db_path.replace("\\", "/"), port=port)
    proc = subprocess.Popen(
        ["node", "-e", script],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=str(REPO_ROOT),
    )
    for line in proc.stdout:
        if b"READY" in line:
            break
    return proc


def http_request(url, method="GET", data=None):
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            content = resp.read().decode()
            return resp.status, json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        content = e.read().decode()
        try:
            return e.code, json.loads(content)
        except Exception:
            return e.code, content


def main():
    print("\n=== Test: Events Webhook (new protocol) ===\n")
    t = TestResult("Events Webhook")

    tmp = get_temp_dir("events")
    db_path = str(tmp / "test.db")

    proc = start_server(db_path, EVENTS_PORT)
    base = f"http://localhost:{EVENTS_PORT}"

    try:
        time.sleep(0.3)

        # --- GET /health ---
        status, body = http_request(f"{base}/health")
        t.check_equal(status, 200, "GET /health returns 200")
        t.check_equal(body.get("status"), "healthy", "Health body correct")

        conn = sqlite3.connect(db_path)

        # --- motion event: prefilter passed=1 → status=pending ---
        status, _ = http_request(f"{base}/events", "POST", {
            "sourceId": "cam_child", "type": "motion", "timestamp": "2026-06-25T10:00:00Z",
            "payload": {
                "event_file_path": "/data/seg_001.mp4",
                "summary_clip_input": "/data/seg_001_input.mp4",
                "start_time": "2026-06-25T10:00:00Z", "end_time": "2026-06-25T10:00:15Z",
                "duration_seconds": 15.0,
                "prefilter_passed": 1, "prefilter_classes": '["person"]', "prefilter_confidence": 0.9,
            },
        })
        t.check_equal(status, 200, "motion event returns 200")
        events = conn.execute("SELECT * FROM events WHERE monitor_id='cam_child'").fetchall()
        tasks  = conn.execute("SELECT * FROM video_summary_tasks WHERE monitor_id='cam_child'").fetchall()
        t.check_equal(len(events), 1, "motion event writes events table")
        t.check_equal(len(tasks), 1, "motion event writes video_summary_tasks")
        t.check_equal(tasks[0][4], "pending", "prefilter_passed=1 → status=pending")
        t.check_equal(events[0][6], "/data/seg_001.mp4", "event_file_path stored correctly")
        t.check_equal(tasks[0][3], "/data/seg_001_input.mp4", "summary_clip_input stored correctly")

        # --- motion event: prefilter passed=0 → status=ignored ---
        http_request(f"{base}/events", "POST", {
            "sourceId": "cam_child", "type": "motion", "timestamp": "2026-06-25T10:01:00Z",
            "payload": {
                "event_file_path": "/data/seg_002.mp4",
                "summary_clip_input": "/data/seg_002_input.mp4",
                "start_time": "2026-06-25T10:01:00Z",
                "duration_seconds": 10.0,
                "prefilter_passed": 0,
            },
        })
        tasks2 = conn.execute(
            "SELECT status FROM video_summary_tasks WHERE monitor_id='cam_child' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        t.check_equal(tasks2[0], "ignored", "prefilter_passed=0 → status=ignored")

        # --- motion event: no prefilter → status=pending ---
        http_request(f"{base}/events", "POST", {
            "sourceId": "cam_fridge", "type": "motion", "timestamp": "2026-06-25T10:02:00Z",
            "payload": {
                "event_file_path": "/data/fridge_001.mp4",
                "summary_clip_input": "/data/fridge_001.mp4",
                "start_time": "2026-06-25T10:02:00Z",
                "duration_seconds": 20.0,
            },
        })
        fridge_task = conn.execute(
            "SELECT status FROM video_summary_tasks WHERE monitor_id='cam_fridge'"
        ).fetchone()
        t.check_equal(fridge_task[0], "pending", "no prefilter → status=pending")

        # --- static event → events only, no task ---
        tasks_before = conn.execute(
            "SELECT COUNT(*) FROM video_summary_tasks WHERE monitor_id='cam_child'"
        ).fetchone()[0]
        http_request(f"{base}/events", "POST", {
            "sourceId": "cam_child", "type": "static", "timestamp": "2026-06-25T10:03:00Z",
            "payload": {"start_time": "2026-06-25T10:03:00Z", "duration_seconds": 30.0},
        })
        events_after = conn.execute("SELECT * FROM events WHERE monitor_id='cam_child'").fetchall()
        tasks_after  = conn.execute(
            "SELECT COUNT(*) FROM video_summary_tasks WHERE monitor_id='cam_child'"
        ).fetchone()[0]
        static_ev = [e for e in events_after if e[2] == "static"]
        t.check_equal(len(static_ev), 1, "static event writes events table (motion_type=static)")
        t.check_equal(tasks_after, tasks_before, "static event does not create task")

        # --- recording event → recordings only ---
        http_request(f"{base}/events", "POST", {
            "sourceId": "cam_child", "type": "recording", "timestamp": "2026-06-25T10:04:00Z",
            "payload": {
                "recording_path": "/data/rec_001.mp4",
                "recording_start": "2026-06-25T10:00:00Z",
                "recording_end": "2026-06-25T10:01:00Z",
                "duration_seconds": 60.0, "file_size_bytes": 8192000,
            },
        })
        recs = conn.execute("SELECT * FROM recordings WHERE monitor_id='cam_child'").fetchall()
        t.check_equal(len(recs), 1, "recording event writes recordings table")
        t.check_equal(recs[0][2], "/data/rec_001.mp4", "recording file_path stored correctly")

        # --- motion event missing required field → 200 (warn + skip) ---
        status, _ = http_request(f"{base}/events", "POST", {
            "sourceId": "cam_child", "type": "motion", "timestamp": "2026-06-25T10:05:00Z",
            "payload": {"event_file_path": "/data/seg_003.mp4"},  # missing summary_clip_input
        })
        t.check_equal(status, 200, "motion event missing required field returns 200 (not 500)")
        tasks_no_change = conn.execute(
            "SELECT COUNT(*) FROM video_summary_tasks WHERE monitor_id='cam_child'"
        ).fetchone()[0]
        t.check_equal(tasks_no_change, 2, "missing required field: no new task created")

        # --- invalid JSON → 400 ---
        req = urllib.request.Request(
            f"{base}/events", data=b"not json", method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req)
            t.check(False, "Invalid JSON should return 400")
        except urllib.error.HTTPError as e:
            t.check_equal(e.code, 400, "Invalid JSON returns 400")

        # --- 404 for unknown path ---
        try:
            urllib.request.urlopen(f"{base}/unknown")
            t.check(False, "Unknown path should return 404")
        except urllib.error.HTTPError as e:
            t.check_equal(e.code, 404, "Unknown path returns 404")

        conn.close()

    finally:
        proc.terminate()
        proc.wait(timeout=5)

    cleanup_dir(tmp)
    passed = t.summary()
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
