# Schema Migration Plan — Aligning with db-schema-design.md

## Current vs. Target Schema Gap Analysis

### Gap 1: Missing `events` Table

**Current:** ❌ No events table  
**Target:** ✅ `events` table (motion/static events from videostream-analytics)

**Impact:** Cannot trace alerts back to original motion events, cannot query "which motions didn't trigger alerts?"

### Gap 2: Missing `recordings` Table

**Current:** ❌ No recordings table  
**Target:** ✅ `recordings` table (segment file metadata)

**Impact:** Cannot manage recording lifecycle, cannot query storage usage.

### Gap 3: `video_summary_tasks` Missing Columns

**Current:**
```sql
CREATE TABLE video_summary_tasks (
  id, monitor_id, video_path, status, summary, created_at, completed_at
);
```

**Target:**
```sql
CREATE TABLE video_summary_tasks (
  id, monitor_id, 
  event_id,              -- ❌ MISSING: FK to events
  clip_start_time,       -- ❌ MISSING: precise time range
  clip_end_time,         -- ❌ MISSING
  clip_duration,         -- ❌ MISSING
  clip_file_path,        -- ✅ EXISTS as video_path
  summary_text,          -- ✅ EXISTS as summary
  status, error_message, -- ✅ EXISTS / ❌ MISSING error_message
  latency_seconds,       -- ❌ MISSING
  prompt_tokens,         -- ❌ MISSING
  image_tokens,          -- ❌ MISSING
  completion_tokens,     -- ❌ MISSING
  started_at,            -- ❌ MISSING
  completed_at,          -- ✅ EXISTS
  created_at             -- ✅ EXISTS
  -- + schema extensions (event, severity, desc)
);
```

### Gap 4: `alerts` Missing Critical Columns

**Current:**
```sql
CREATE TABLE alerts (
  id, source_id, event, severity, description, acked, created_at
);
```

**Target:**
```sql
CREATE TABLE alerts (
  id, monitor_id,        -- ✅ EXISTS as source_id
  task_id,               -- ❌ MISSING: FK to video_summary_tasks
  event_id,              -- ❌ MISSING: FK to events
  use_case,              -- ❌ MISSING: business context
  alert_type,            -- ✅ EXISTS as event (but should rename)
  severity,              -- ✅ EXISTS
  description,           -- ✅ EXISTS
  created_at,            -- ✅ EXISTS
  ack_at,                -- ❌ MISSING: audit trail
  ack_by                 -- ❌ MISSING: who acknowledged
  -- + schema extensions
);
```

### Gap 5: Missing `reports` Table

**Current:** ❌ No reports table (daily_report tool returns JSON, doesn't persist)  
**Target:** ✅ `reports` table with `period_start`, `period_end` (supports daily/weekly/monthly)

**Impact:** Cannot query historical reports, cannot track report generation performance.

### Gap 6: `monitor_state` Missing `use_case` Column

**Current:**
```sql
CREATE TABLE monitor_state (
  monitor_id, state_json, updated_at
);
```

**Target:**
```sql
CREATE TABLE monitor_state (
  monitor_id, 
  use_case,       -- ❌ MISSING
  state_json, 
  updated_at
);
```

---

## Migration Strategy

### Phase 1: Create New Tables (Non-Breaking)

```sql
-- 1.1 events table
CREATE TABLE IF NOT EXISTS events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    monitor_id          TEXT NOT NULL,
    motion_type         TEXT NOT NULL,
    start_time          TEXT NOT NULL,
    end_time            TEXT,
    duration_seconds    REAL,
    prefilter_passed    INTEGER,
    prefilter_classes   TEXT,
    prefilter_confidence REAL,
    trajectory_region   TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_events_monitor_time ON events(monitor_id, start_time);

-- 1.2 recordings table
CREATE TABLE IF NOT EXISTS recordings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    monitor_id          TEXT NOT NULL,
    file_path           TEXT NOT NULL,
    start_time          TEXT NOT NULL,
    end_time            TEXT NOT NULL,
    duration_seconds    REAL,
    file_size_bytes     INTEGER,
    created_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_recordings_monitor_time ON recordings(monitor_id, start_time, end_time);

-- 1.3 reports table
CREATE TABLE IF NOT EXISTS reports (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    monitor_id          TEXT NOT NULL,
    use_case            TEXT NOT NULL,
    period_start        TEXT NOT NULL,
    period_end          TEXT NOT NULL,
    report_text         TEXT,
    event_count         INTEGER,
    motion_count        INTEGER,
    latency_seconds     REAL,
    prompt_tokens       INTEGER,
    image_tokens        INTEGER,
    completion_tokens   INTEGER,
    status              TEXT DEFAULT 'pending',
    report_type         TEXT DEFAULT 'raw',
    created_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_reports_monitor_period ON reports(monitor_id, period_start);
```

### Phase 2: Alter Existing Tables (Add Missing Columns)

```sql
-- 2.1 video_summary_tasks: add missing columns
ALTER TABLE video_summary_tasks ADD COLUMN event_id INTEGER REFERENCES events(id);
ALTER TABLE video_summary_tasks ADD COLUMN clip_start_time TEXT;
ALTER TABLE video_summary_tasks ADD COLUMN clip_end_time TEXT;
ALTER TABLE video_summary_tasks ADD COLUMN clip_duration REAL;
ALTER TABLE video_summary_tasks ADD COLUMN error_message TEXT;
ALTER TABLE video_summary_tasks ADD COLUMN latency_seconds REAL;
ALTER TABLE video_summary_tasks ADD COLUMN prompt_tokens INTEGER;
ALTER TABLE video_summary_tasks ADD COLUMN image_tokens INTEGER;
ALTER TABLE video_summary_tasks ADD COLUMN completion_tokens INTEGER;
ALTER TABLE video_summary_tasks ADD COLUMN started_at TEXT;

-- Rename video_path → clip_file_path, summary → summary_text
-- (SQLite doesn't support RENAME COLUMN before 3.25.0, use new columns + migrate)
ALTER TABLE video_summary_tasks ADD COLUMN clip_file_path TEXT;
ALTER TABLE video_summary_tasks ADD COLUMN summary_text TEXT;
-- Migration: UPDATE video_summary_tasks SET clip_file_path=video_path, summary_text=summary;

-- 2.2 alerts: add missing columns
ALTER TABLE alerts ADD COLUMN task_id INTEGER REFERENCES video_summary_tasks(id);
ALTER TABLE alerts ADD COLUMN event_id INTEGER REFERENCES events(id);
ALTER TABLE alerts ADD COLUMN use_case TEXT;
ALTER TABLE alerts ADD COLUMN ack_at TEXT;
ALTER TABLE alerts ADD COLUMN ack_by TEXT;

-- Rename source_id → monitor_id, event → alert_type
ALTER TABLE alerts ADD COLUMN monitor_id TEXT;
ALTER TABLE alerts ADD COLUMN alert_type TEXT;
-- Migration: UPDATE alerts SET monitor_id=source_id, alert_type=event;

-- 2.3 monitor_state: add use_case column
ALTER TABLE monitor_state ADD COLUMN use_case TEXT;

-- 2.4 Create indexes for new FKs
CREATE INDEX IF NOT EXISTS idx_vst_event ON video_summary_tasks(event_id);
CREATE INDEX IF NOT EXISTS idx_alerts_task ON alerts(task_id);
CREATE INDEX IF NOT EXISTS idx_alerts_event ON alerts(event_id);
CREATE INDEX IF NOT EXISTS idx_alerts_monitor_time ON alerts(monitor_id, created_at);
CREATE INDEX IF NOT EXISTS idx_alerts_ack ON alerts(ack_at);
```

### Phase 3: Schema Extensions Support

```sql
-- Default schema extensions (from config.yaml.example)
ALTER TABLE video_summary_tasks ADD COLUMN event TEXT;
ALTER TABLE video_summary_tasks ADD COLUMN severity TEXT;
ALTER TABLE video_summary_tasks ADD COLUMN desc TEXT;
```

---

## Code Changes Required

### 1. Database Layer (`packages/db/src/database.ts`)

**Add new table methods:**
```typescript
// Events CRUD
createEvent(event: Omit<Event, "id" | "createdAt">): Event;
getEvent(id: number): Event | undefined;
getEventsByTimeRange(monitorId: string, start: string, end: string): Event[];

// Recordings CRUD
createRecording(rec: Omit<Recording, "id" | "createdAt">): Recording;
listRecordings(monitorId: string, options?: { since?: string; limit?: number }): Recording[];

// Reports CRUD
createReport(report: Omit<Report, "id" | "createdAt">): Report;
getReportsByPeriod(monitorId: string, periodStart: string, periodEnd: string): Report[];

// Enhanced queryAlerts (DB-layer date filtering)
queryAlertsByDateRange(options: {
  monitorId?: string;
  startDate: string;
  endDate: string;
  severity?: string;
  acked?: boolean;
  limit?: number;
}): Alert[];

// Alert stats (avoid pulling full list)
getAlertStats(monitorId: string, startDate: string, endDate: string): {
  total: number;
  bySeverity: { critical: number; warn: number; info: number };
  byType: Record<string, number>;
  unacked: number;
};
```

### 2. Tools Layer (`packages/mcp-server/src/tools.ts`)

**Enhanced `smartbuilding_alert_query`:**
```typescript
server.registerTool("smartbuilding_alert_query", {
  description: "Query or acknowledge alerts, with stats support",
  inputSchema: {
    monitor_id: z.string().optional(),
    status: z.enum(["unacked", "acked", "all"]).optional(),
    
    // ✅ NEW: date range filtering
    start_date: z.string().optional().describe("Start date (YYYY-MM-DD, inclusive)"),
    end_date: z.string().optional().describe("End date (YYYY-MM-DD, exclusive)"),
    
    // ✅ NEW: severity filtering
    severity: z.enum(["critical", "warn", "info"]).optional(),
    
    limit: z.number().optional(),
    ack_id: z.number().optional(),
    
    // ✅ NEW: stats mode
    stats_only: z.boolean().optional().describe("Return summary stats instead of alert list"),
  },
}, async (params) => {
  // ACK mode (unchanged)
  if (params.ack_id !== undefined) {
    db.ackAlert(params.ack_id, params.ack_by ?? "agent");
    return { content: [{ type: "text", text: `Alert ${params.ack_id} acknowledged.` }] };
  }
  
  // Stats mode (NEW)
  if (params.stats_only) {
    const startDate = params.start_date ?? new Date().toISOString().slice(0, 10);
    const endDate = params.end_date ?? new Date(Date.now() + 86400000).toISOString().slice(0, 10);
    const stats = db.getAlertStats(params.monitor_id!, startDate, endDate);
    return { content: [{ type: "text", text: JSON.stringify(stats, null, 2) }] };
  }
  
  // Query mode (ENHANCED: DB-layer date filtering)
  const startDate = params.start_date ?? "1970-01-01";
  const endDate = params.end_date ?? "2099-12-31";
  const acked = params.status === "acked" ? true : params.status === "unacked" ? false : undefined;
  
  const alerts = db.queryAlertsByDateRange({
    monitorId: params.monitor_id,
    startDate,
    endDate,
    severity: params.severity,
    acked,
    limit: params.limit ?? 50,
  });
  
  return { content: [{ type: "text", text: JSON.stringify(alerts, null, 2) }] };
});
```

**Enhanced `smartbuilding_daily_report`:**
```typescript
server.registerTool("smartbuilding_daily_report", {
  description: "Generate daily/weekly/monthly report for a monitor",
  inputSchema: {
    monitor_id: z.string(),
    
    // ✅ CHANGED: period_start + period_end (replaces single date)
    period_start: z.string().describe("Period start (YYYY-MM-DD HH:MM:SS or YYYY-MM-DD)"),
    period_end: z.string().optional().describe("Period end (defaults to period_start + 1 day)"),
    
    // ✅ NEW: report type (distinguish use cases)
    report_type: z.enum(["events", "alerts"]).optional().describe(
      "events: motion-based (fridge), alerts: alert-based (child_safety, elder_wakeup)"
    ),
    
    report_text: z.string().optional().describe("Override report text (skip VLM generation)"),
  },
}, async (params) => {
  const periodStart = params.period_start.length === 10 
    ? `${params.period_start}T00:00:00` 
    : params.period_start;
  const periodEnd = params.period_end ?? 
    new Date(new Date(periodStart).getTime() + 86400000).toISOString().slice(0, 19).replace("T", " ");
  
  const monitor = db.getMonitor(params.monitor_id);
  if (!monitor) {
    return { content: [{ type: "text", text: `Monitor ${params.monitor_id} not found.` }], isError: true };
  }
  
  // Determine report type based on use_case
  const useCase = monitor.useCaseId;
  const reportType = params.report_type ?? (useCase === "fridge" ? "events" : "alerts");
  
  if (params.report_text) {
    // Save mode: persist provided report
    const reportId = db.createReport({
      monitorId: params.monitor_id,
      useCase,
      periodStart,
      periodEnd,
      reportText: params.report_text,
      status: "completed",
      reportType: "polished",
    });
    return { content: [{ type: "text", text: `Report ${reportId} saved.` }] };
  }
  
  // Generate mode: dispatch by report type
  if (reportType === "events") {
    // Fridge use case: query events table (motion events)
    const events = db.getEventsByTimeRange(params.monitor_id, periodStart, periodEnd);
    const tasks = db.getCompletedTasksByTimeRange(params.monitor_id, periodStart, periodEnd);
    
    if (events.length === 0 && tasks.length === 0) {
      return { content: [{ type: "text", text: `No events or tasks for ${params.monitor_id} in period.` }] };
    }
    
    // TODO: Call VLM service to generate narrative report from events
    const report = {
      monitorId: params.monitor_id,
      periodStart,
      periodEnd,
      totalEvents: events.length,
      totalMotionEvents: events.filter(e => e.motionType === "motion").length,
      totalTasks: tasks.length,
      // ... generate VLM report
    };
    
    return { content: [{ type: "text", text: JSON.stringify(report, null, 2) }] };
  } else {
    // Child safety / Elder wakeup: query alerts table
    const stats = db.getAlertStats(params.monitor_id, periodStart.slice(0, 10), periodEnd.slice(0, 10));
    const alerts = db.queryAlertsByDateRange({
      monitorId: params.monitor_id,
      startDate: periodStart.slice(0, 10),
      endDate: periodEnd.slice(0, 10),
      limit: 100,
    });
    
    if (stats.total === 0) {
      const emptyReport = `No ${useCase} alerts in period ${periodStart} ~ ${periodEnd}.`;
      db.createReport({
        monitorId: params.monitor_id,
        useCase,
        periodStart,
        periodEnd,
        reportText: emptyReport,
        eventCount: 0,
        status: "completed",
        reportType: "raw",
      });
      return { content: [{ type: "text", text: emptyReport }] };
    }
    
    // Generate detailed alert-based report
    const report = {
      monitorId: params.monitor_id,
      useCase,
      periodStart,
      periodEnd,
      totalAlerts: stats.total,
      severityBreakdown: stats.bySeverity,
      alertTypeBreakdown: stats.byType,
      unackedAlerts: stats.unacked,
      criticalAlerts: alerts.filter(a => a.severity === "critical"),
      // ... generate VLM narrative
    };
    
    return { content: [{ type: "text", text: JSON.stringify(report, null, 2) }] };
  }
});
```

---

## Addressing Specific Concerns

### Concern 1: `cam_fridge` queries `events`, `cam_child` queries `alerts`

**Solution:** Use `report_type` parameter + monitor's `use_case` to dispatch:

```typescript
// Auto-detect or explicit:
const reportType = params.report_type ?? (monitor.useCaseId === "fridge" ? "events" : "alerts");

if (reportType === "events") {
  // Fridge: motion events matter, alerts are rare/irrelevant
  const events = db.getEventsByTimeRange(...);
  const tasks = db.getCompletedTasksByTimeRange(...);
  // Generate report from motion patterns, food access frequency
} else {
  // Child safety / Elder wakeup: only alerts matter
  const stats = db.getAlertStats(...);
  const alerts = db.queryAlertsByDateRange(...);
  // Generate report from danger events, wakeup anomalies
}
```

**Why this works:**
- Fridge use case: every motion event is interesting (food access), alerts are edge cases (expired food)
- Child safety: normal play is noise, only alerts (danger events) matter
- Elder wakeup: routine in-bed movements are noise, only alerts (late wakeup, no movement) matter

### Concern 2: Performance — avoid JS-layer filtering

**Solution:** All date/severity filtering happens in SQL:

```typescript
// ❌ OLD (BAD): pull all alerts, filter in JS
const alerts = db.queryAlerts({ sourceId: "cam_child" });  // 10000 rows
const todayAlerts = alerts.filter(a => a.createdAt.startsWith("2026-06-23"));  // slow

// ✅ NEW (GOOD): DB-layer filtering
const alerts = db.queryAlertsByDateRange({
  monitorId: "cam_child",
  startDate: "2026-06-23",
  endDate: "2026-06-24",
  severity: "critical",
  limit: 50
});  // only 5 rows returned, indexed query
```

**Database implementation:**
```typescript
queryAlertsByDateRange(options): Alert[] {
  let sql = `
    SELECT * FROM alerts 
    WHERE monitor_id = ?
      AND created_at >= ?
      AND created_at < ?
  `;
  const params: any[] = [options.monitorId, options.startDate, options.endDate];
  
  if (options.severity) {
    sql += " AND severity = ?";
    params.push(options.severity);
  }
  if (options.acked !== undefined) {
    sql += " AND (ack_at IS " + (options.acked ? "NOT NULL)" : "NULL)");
  }
  sql += " ORDER BY created_at DESC LIMIT ?";
  params.push(options.limit ?? 100);
  
  return this.db.prepare(sql).all(...params) as Alert[];
}
```

### Concern 3: Severity stats for `daily_report`

**Solution:** DB-layer aggregate query (no N+1):

```typescript
getAlertStats(monitorId, startDate, endDate): AlertStats {
  const sql = `
    SELECT 
      COUNT(*) as total,
      SUM(CASE WHEN severity = 'critical' THEN 1 ELSE 0 END) as critical,
      SUM(CASE WHEN severity = 'warn' THEN 1 ELSE 0 END) as warn,
      SUM(CASE WHEN severity = 'info' THEN 1 ELSE 0 END) as info,
      SUM(CASE WHEN ack_at IS NULL THEN 1 ELSE 0 END) as unacked
    FROM alerts
    WHERE monitor_id = ? 
      AND date(created_at) >= date(?)
      AND date(created_at) < date(?)
  `;
  const row = this.db.prepare(sql).get(monitorId, startDate, endDate) as any;
  
  // Type breakdown (second query to avoid complex GROUP BY)
  const typesSql = `
    SELECT alert_type, COUNT(*) as count
    FROM alerts
    WHERE monitor_id = ? 
      AND date(created_at) >= date(?)
      AND date(created_at) < date(?)
    GROUP BY alert_type
  `;
  const types = this.db.prepare(typesSql).all(monitorId, startDate, endDate) as any[];
  
  return {
    total: row.total,
    bySeverity: {
      critical: row.critical,
      warn: row.warn,
      info: row.info,
    },
    byType: types.reduce((acc, t) => ({ ...acc, [t.alert_type]: t.count }), {}),
    unacked: row.unacked,
  };
}
```

---

## Migration Execution Plan

### Step 1: Schema Migration Script

Create `packages/db/src/migrations/001_align_with_design.ts`:

```typescript
import Database from "better-sqlite3";

export function migrate001(db: Database.Database): void {
  console.log("[migration:001] Creating missing tables...");
  
  // Create events table
  db.exec(`
    CREATE TABLE IF NOT EXISTS events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      monitor_id TEXT NOT NULL,
      motion_type TEXT NOT NULL,
      start_time TEXT NOT NULL,
      end_time TEXT,
      duration_seconds REAL,
      prefilter_passed INTEGER,
      prefilter_classes TEXT,
      prefilter_confidence REAL,
      trajectory_region TEXT,
      created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_events_monitor_time ON events(monitor_id, start_time);
  `);
  
  // Create recordings table
  db.exec(`
    CREATE TABLE IF NOT EXISTS recordings (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      monitor_id TEXT NOT NULL,
      file_path TEXT NOT NULL,
      start_time TEXT NOT NULL,
      end_time TEXT NOT NULL,
      duration_seconds REAL,
      file_size_bytes INTEGER,
      created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_recordings_monitor_time ON recordings(monitor_id, start_time, end_time);
  `);
  
  // Create reports table
  db.exec(`
    CREATE TABLE IF NOT EXISTS reports (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      monitor_id TEXT NOT NULL,
      use_case TEXT NOT NULL,
      period_start TEXT NOT NULL,
      period_end TEXT NOT NULL,
      report_text TEXT,
      event_count INTEGER,
      motion_count INTEGER,
      latency_seconds REAL,
      prompt_tokens INTEGER,
      image_tokens INTEGER,
      completion_tokens INTEGER,
      status TEXT DEFAULT 'pending',
      report_type TEXT DEFAULT 'raw',
      created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_reports_monitor_period ON reports(monitor_id, period_start);
  `);
  
  console.log("[migration:001] Adding missing columns to existing tables...");
  
  // Alter video_summary_tasks
  const vstColumns = [
    "event_id INTEGER",
    "clip_start_time TEXT",
    "clip_end_time TEXT",
    "clip_duration REAL",
    "clip_file_path TEXT",
    "summary_text TEXT",
    "error_message TEXT",
    "latency_seconds REAL",
    "prompt_tokens INTEGER",
    "image_tokens INTEGER",
    "completion_tokens INTEGER",
    "started_at TEXT",
  ];
  
  vstColumns.forEach(col => {
    try {
      db.exec(`ALTER TABLE video_summary_tasks ADD COLUMN ${col}`);
    } catch (err: any) {
      if (!err.message.includes("duplicate column")) throw err;
    }
  });
  
  // Migrate old column names
  db.exec(`UPDATE video_summary_tasks SET clip_file_path = video_path WHERE clip_file_path IS NULL`);
  db.exec(`UPDATE video_summary_tasks SET summary_text = summary WHERE summary_text IS NULL`);
  
  // Alter alerts
  const alertColumns = [
    "task_id INTEGER",
    "event_id INTEGER",
    "use_case TEXT",
    "monitor_id TEXT",
    "alert_type TEXT",
    "ack_at TEXT",
    "ack_by TEXT",
  ];
  
  alertColumns.forEach(col => {
    try {
      db.exec(`ALTER TABLE alerts ADD COLUMN ${col}`);
    } catch (err: any) {
      if (!err.message.includes("duplicate column")) throw err;
    }
  });
  
  // Migrate old column names
  db.exec(`UPDATE alerts SET monitor_id = source_id WHERE monitor_id IS NULL`);
  db.exec(`UPDATE alerts SET alert_type = event WHERE alert_type IS NULL`);
  
  // Alter monitor_state
  try {
    db.exec(`ALTER TABLE monitor_state ADD COLUMN use_case TEXT`);
  } catch (err: any) {
    if (!err.message.includes("duplicate column")) throw err;
  }
  
  // Create indexes
  db.exec(`
    CREATE INDEX IF NOT EXISTS idx_vst_event ON video_summary_tasks(event_id);
    CREATE INDEX IF NOT EXISTS idx_alerts_task ON alerts(task_id);
    CREATE INDEX IF NOT EXISTS idx_alerts_event ON alerts(event_id);
    CREATE INDEX IF NOT EXISTS idx_alerts_monitor_time ON alerts(monitor_id, created_at);
    CREATE INDEX IF NOT EXISTS idx_alerts_ack ON alerts(ack_at);
  `);
  
  console.log("[migration:001] Migration complete.");
}
```

### Step 2: Run Migration on Server Start

```typescript
// packages/mcp-server/src/index.ts
import { migrate001 } from "./migrations/001_align_with_design.js";

async function main() {
  // ... load config ...
  
  const db = new SmartBuildingDB(config.db.path);
  db.initialize();
  
  // Run migrations
  migrate001((db as any).db);  // access internal better-sqlite3 instance
  
  // Apply schema customization
  if (config.schema) {
    const schemaManager = new SchemaManager((db as any).db);
    const result = schemaManager.applySchema(config.schema);
    // ...
  }
  
  // ... rest of startup ...
}
```

---

## Summary

**3 Key Improvements:**

1. **DB Schema Alignment** — Add `events`, `recordings`, `reports` tables + missing columns in `video_summary_tasks` and `alerts`

2. **Enhanced `alert_query` Tool** — DB-layer date filtering, severity filtering, stats mode for efficient aggregation

3. **Dual-Mode `daily_report`** — `events`-based for fridge, `alerts`-based for child_safety/elder_wakeup, with `period_start`/`period_end` for weekly/monthly reports

**Migration is backwards-compatible:** Existing data preserved, new columns nullable, old column names migrated automatically.
