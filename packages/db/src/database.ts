import Database from "better-sqlite3";
import type { Monitor, Alert, VideoSummaryTask } from "./types.js";

const MIGRATIONS = `
CREATE TABLE IF NOT EXISTS monitors (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  source_url TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'offline',
  use_case_id TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT NOT NULL,
  event TEXT NOT NULL,
  severity TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  acked INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (source_id) REFERENCES monitors(id)
);

CREATE TABLE IF NOT EXISTS video_summary_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  monitor_id TEXT NOT NULL,
  video_path TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  summary TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  completed_at TEXT,
  FOREIGN KEY (monitor_id) REFERENCES monitors(id)
);

CREATE TABLE IF NOT EXISTS monitor_state (
  monitor_id TEXT PRIMARY KEY,
  state_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (monitor_id) REFERENCES monitors(id)
);
`;

export class SmartBuildingDB {
  private db: Database.Database;

  constructor(dbPath: string) {
    this.db = new Database(dbPath);
    this.db.pragma("journal_mode = WAL");
    this.db.pragma("foreign_keys = ON");
  }

  initialize(): void {
    this.db.exec(MIGRATIONS);
  }

  close(): void {
    this.db.close();
  }

  // --- Monitors ---

  createMonitor(monitor: Omit<Monitor, "createdAt">): Monitor {
    const stmt = this.db.prepare(`
      INSERT INTO monitors (id, name, source_url, status, use_case_id)
      VALUES (@id, @name, @sourceUrl, @status, @useCaseId)
    `);
    stmt.run({
      id: monitor.id,
      name: monitor.name,
      sourceUrl: monitor.sourceUrl,
      status: monitor.status,
      useCaseId: monitor.useCaseId,
    });
    return this.getMonitor(monitor.id)!;
  }

  getMonitor(id: string): Monitor | undefined {
    const row = this.db.prepare("SELECT * FROM monitors WHERE id = ?").get(id) as any;
    if (!row) return undefined;
    return {
      id: row.id,
      name: row.name,
      sourceUrl: row.source_url,
      status: row.status,
      useCaseId: row.use_case_id,
      createdAt: row.created_at,
    };
  }

  listMonitors(): Monitor[] {
    const rows = this.db.prepare("SELECT * FROM monitors").all() as any[];
    return rows.map((row) => ({
      id: row.id,
      name: row.name,
      sourceUrl: row.source_url,
      status: row.status,
      useCaseId: row.use_case_id,
      createdAt: row.created_at,
    }));
  }

  updateMonitorStatus(id: string, status: Monitor["status"]): void {
    this.db.prepare("UPDATE monitors SET status = ? WHERE id = ?").run(status, id);
  }

  deleteMonitor(id: string): void {
    this.db.prepare("DELETE FROM monitors WHERE id = ?").run(id);
  }

  // --- Alerts ---

  createAlert(alert: Omit<Alert, "id" | "createdAt">): Alert {
    const stmt = this.db.prepare(`
      INSERT INTO alerts (source_id, event, severity, description, acked)
      VALUES (@sourceId, @event, @severity, @description, @acked)
    `);
    const result = stmt.run({
      sourceId: alert.sourceId,
      event: alert.event,
      severity: alert.severity,
      description: alert.description,
      acked: alert.acked ? 1 : 0,
    });
    return this.getAlert(result.lastInsertRowid as number)!;
  }

  getAlert(id: number): Alert | undefined {
    const row = this.db.prepare("SELECT * FROM alerts WHERE id = ?").get(id) as any;
    if (!row) return undefined;
    return {
      id: row.id,
      sourceId: row.source_id,
      event: row.event,
      severity: row.severity,
      description: row.description,
      acked: Boolean(row.acked),
      createdAt: row.created_at,
    };
  }

  queryAlerts(options: { sourceId?: string; acked?: boolean; limit?: number }): Alert[] {
    let sql = "SELECT * FROM alerts WHERE 1=1";
    const params: any[] = [];

    if (options.sourceId) {
      sql += " AND source_id = ?";
      params.push(options.sourceId);
    }
    if (options.acked !== undefined) {
      sql += " AND acked = ?";
      params.push(options.acked ? 1 : 0);
    }
    sql += " ORDER BY created_at DESC";
    if (options.limit) {
      sql += " LIMIT ?";
      params.push(options.limit);
    }

    const rows = this.db.prepare(sql).all(...params) as any[];
    return rows.map((row) => ({
      id: row.id,
      sourceId: row.source_id,
      event: row.event,
      severity: row.severity,
      description: row.description,
      acked: Boolean(row.acked),
      createdAt: row.created_at,
    }));
  }

  ackAlert(id: number): void {
    this.db.prepare("UPDATE alerts SET acked = 1 WHERE id = ?").run(id);
  }

  // --- Video Summary Tasks ---

  createTask(task: Omit<VideoSummaryTask, "id" | "createdAt" | "completedAt">): VideoSummaryTask {
    const stmt = this.db.prepare(`
      INSERT INTO video_summary_tasks (monitor_id, video_path, status, summary)
      VALUES (@monitorId, @videoPath, @status, @summary)
    `);
    const result = stmt.run({
      monitorId: task.monitorId,
      videoPath: task.videoPath,
      status: task.status,
      summary: task.summary ?? null,
    });
    return this.getTask(result.lastInsertRowid as number)!;
  }

  getTask(id: number): VideoSummaryTask | undefined {
    const row = this.db.prepare("SELECT * FROM video_summary_tasks WHERE id = ?").get(id) as any;
    if (!row) return undefined;
    return {
      id: row.id,
      monitorId: row.monitor_id,
      videoPath: row.video_path,
      status: row.status,
      summary: row.summary,
      createdAt: row.created_at,
      completedAt: row.completed_at,
    };
  }

  getPendingTasks(monitorId: string, limit: number = 10): VideoSummaryTask[] {
    const rows = this.db.prepare(
      "SELECT * FROM video_summary_tasks WHERE monitor_id = ? AND status = 'pending' ORDER BY created_at ASC LIMIT ?"
    ).all(monitorId, limit) as any[];
    return rows.map((row) => ({
      id: row.id,
      monitorId: row.monitor_id,
      videoPath: row.video_path,
      status: row.status,
      summary: row.summary,
      createdAt: row.created_at,
      completedAt: row.completed_at,
    }));
  }

  updateTaskStatus(id: number, status: VideoSummaryTask["status"], summary?: string): void {
    if (status === "completed" || status === "failed") {
      this.db.prepare(
        "UPDATE video_summary_tasks SET status = ?, summary = ?, completed_at = datetime('now') WHERE id = ?"
      ).run(status, summary ?? null, id);
    } else {
      this.db.prepare("UPDATE video_summary_tasks SET status = ? WHERE id = ?").run(status, id);
    }
  }

  // --- Monitor State ---

  getState(monitorId: string): Record<string, unknown> {
    const row = this.db.prepare("SELECT state_json FROM monitor_state WHERE monitor_id = ?").get(monitorId) as any;
    if (!row) return {};
    return JSON.parse(row.state_json);
  }

  setState(monitorId: string, state: Record<string, unknown>): void {
    this.db.prepare(`
      INSERT INTO monitor_state (monitor_id, state_json, updated_at)
      VALUES (?, ?, datetime('now'))
      ON CONFLICT(monitor_id) DO UPDATE SET state_json = excluded.state_json, updated_at = excluded.updated_at
    `).run(monitorId, JSON.stringify(state));
  }

  // --- Stats ---

  getStats(monitorId: string): { events: number; alerts: number } {
    const today = new Date().toISOString().slice(0, 10);
    const tasks = this.db.prepare(
      "SELECT COUNT(*) as count FROM video_summary_tasks WHERE monitor_id = ? AND created_at >= ?"
    ).get(monitorId, today) as any;
    const alerts = this.db.prepare(
      "SELECT COUNT(*) as count FROM alerts WHERE source_id = ? AND created_at >= ?"
    ).get(monitorId, today) as any;
    return { events: tasks?.count ?? 0, alerts: alerts?.count ?? 0 };
  }

  // --- Raw query ---

  rawQuery(sql: string, params: unknown[] = []): unknown[] {
    const stmt = this.db.prepare(sql);
    if (sql.trim().toUpperCase().startsWith("SELECT")) {
      return stmt.all(...params);
    }
    const result = stmt.run(...params);
    return [{ changes: result.changes, lastInsertRowid: result.lastInsertRowid }];
  }
}
