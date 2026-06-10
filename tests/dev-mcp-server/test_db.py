#!/usr/bin/env python3
"""Test Case 1: DB CRUD — Monitor/Alert/Task/State 增删改查。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conftest import get_temp_dir, cleanup_dir, init_test_db, TestResult


def main():
    print("\n=== Test: DB CRUD ===\n")
    t = TestResult("DB CRUD")

    tmp = get_temp_dir("db")
    db_path = str(tmp / "test.db")
    conn = init_test_db(db_path)

    # --- Monitor CRUD ---
    conn.execute(
        "INSERT INTO monitors (id, name, source_url, status, use_case_id) VALUES (?, ?, ?, ?, ?)",
        ("cam-01", "Front Door Camera", "rtsp://192.168.1.100/stream", "offline", "child_safety"),
    )
    conn.commit()

    row = conn.execute("SELECT * FROM monitors WHERE id = ?", ("cam-01",)).fetchone()
    t.check(row is not None, "createMonitor: row exists")
    t.check_equal(row[1], "Front Door Camera", "createMonitor: correct name")
    t.check(row[5] is not None, "createMonitor: created_at set")

    conn.execute("UPDATE monitors SET status = 'online' WHERE id = ?", ("cam-01",))
    conn.commit()
    status = conn.execute("SELECT status FROM monitors WHERE id = ?", ("cam-01",)).fetchone()[0]
    t.check_equal(status, "online", "updateMonitorStatus works")

    monitors = conn.execute("SELECT * FROM monitors").fetchall()
    t.check_equal(len(monitors), 1, "listMonitors returns 1 monitor")

    # --- Alert CRUD ---
    conn.execute(
        "INSERT INTO alerts (source_id, event, severity, description, acked) VALUES (?, ?, ?, ?, ?)",
        ("cam-01", "child_jumping", "high", "Child jumping from table", 0),
    )
    conn.commit()

    alert = conn.execute("SELECT * FROM alerts WHERE source_id = ?", ("cam-01",)).fetchone()
    t.check(alert[0] > 0, "createAlert: auto-increment id")
    t.check_equal(alert[2], "child_jumping", "createAlert: stores event")

    unacked = conn.execute("SELECT * FROM alerts WHERE source_id = ? AND acked = 0", ("cam-01",)).fetchall()
    t.check_equal(len(unacked), 1, "queryAlerts: 1 unacked alert")

    conn.execute("UPDATE alerts SET acked = 1 WHERE id = ?", (alert[0],))
    conn.commit()
    acked = conn.execute("SELECT * FROM alerts WHERE source_id = ? AND acked = 1", ("cam-01",)).fetchall()
    t.check_equal(len(acked), 1, "ackAlert: marks as acknowledged")

    unacked_after = conn.execute("SELECT * FROM alerts WHERE source_id = ? AND acked = 0", ("cam-01",)).fetchall()
    t.check_equal(len(unacked_after), 0, "ackAlert: no unacked remaining")

    # --- Task CRUD ---
    conn.execute(
        "INSERT INTO video_summary_tasks (monitor_id, video_path, status) VALUES (?, ?, ?)",
        ("cam-01", "segments/cam-01/clip-001.mp4", "pending"),
    )
    conn.commit()

    task = conn.execute("SELECT * FROM video_summary_tasks WHERE monitor_id = ?", ("cam-01",)).fetchone()
    t.check(task[0] > 0, "createTask: auto-increment id")

    pending = conn.execute(
        "SELECT * FROM video_summary_tasks WHERE monitor_id = ? AND status = 'pending'", ("cam-01",)
    ).fetchall()
    t.check_equal(len(pending), 1, "getPendingTasks: returns 1 pending")

    conn.execute("UPDATE video_summary_tasks SET status = 'processing' WHERE id = ?", (task[0],))
    conn.commit()
    pending_after = conn.execute(
        "SELECT * FROM video_summary_tasks WHERE monitor_id = ? AND status = 'pending'", ("cam-01",)
    ).fetchall()
    t.check_equal(len(pending_after), 0, "processing task: not in pending list")

    conn.execute(
        "UPDATE video_summary_tasks SET status = 'completed', summary = ?, completed_at = datetime('now') WHERE id = ?",
        ("Child jumped off chair", task[0]),
    )
    conn.commit()
    completed = conn.execute("SELECT status, summary, completed_at FROM video_summary_tasks WHERE id = ?", (task[0],)).fetchone()
    t.check_equal(completed[0], "completed", "task status = completed")
    t.check_equal(completed[1], "Child jumped off chair", "task summary stored")
    t.check(completed[2] is not None, "completedAt set on completion")

    # --- State ---
    state_data = json.dumps({"lastWakeTime": "07:30", "streak": 5})
    conn.execute(
        "INSERT INTO monitor_state (monitor_id, state_json, updated_at) VALUES (?, ?, datetime('now'))",
        ("cam-01", state_data),
    )
    conn.commit()
    state_row = conn.execute("SELECT state_json FROM monitor_state WHERE monitor_id = ?", ("cam-01",)).fetchone()
    state = json.loads(state_row[0])
    t.check_equal(state["lastWakeTime"], "07:30", "setState/getState: string value")
    t.check_equal(state["streak"], 5, "setState/getState: numeric value")

    empty_state = conn.execute("SELECT state_json FROM monitor_state WHERE monitor_id = ?", ("nonexistent",)).fetchone()
    t.check(empty_state is None, "getState: None for unknown monitor")

    # --- Stats ---
    today = conn.execute("SELECT date('now')").fetchone()[0]
    task_count = conn.execute(
        "SELECT COUNT(*) FROM video_summary_tasks WHERE monitor_id = ? AND created_at >= ?",
        ("cam-01", today),
    ).fetchone()[0]
    t.check(isinstance(task_count, int), "getStats: events count is int")

    # --- Raw query ---
    raw = conn.execute("SELECT COUNT(*) FROM monitors").fetchone()
    t.check(raw[0] >= 1, "rawQuery: returns data")

    # --- Delete (clean up FK deps first) ---
    conn.execute("DELETE FROM alerts WHERE source_id = ?", ("cam-01",))
    conn.execute("DELETE FROM video_summary_tasks WHERE monitor_id = ?", ("cam-01",))
    conn.execute("DELETE FROM monitor_state WHERE monitor_id = ?", ("cam-01",))
    conn.execute("DELETE FROM monitors WHERE id = ?", ("cam-01",))
    conn.commit()
    deleted = conn.execute("SELECT * FROM monitors WHERE id = ?", ("cam-01",)).fetchone()
    t.check(deleted is None, "deleteMonitor: removes monitor")

    conn.close()
    cleanup_dir(tmp)

    passed = t.summary()
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
