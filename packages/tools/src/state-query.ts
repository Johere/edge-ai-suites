import type { SmartBuildingDB } from "@smartbuilding-video/db";

export interface StateQueryParams {
  monitor_id: string;
  /** get: read one key (or all when `key` omitted). set: upsert. delete: remove one. */
  action: "get" | "set" | "delete";
  key?: string;
  /** Any JSON value. Required for `set`. */
  value?: unknown;
}

export type StateQueryResult =
  | { value: unknown | null; key: string }
  | { state: Record<string, unknown> }
  | { success: true; monitor_id: string; key: string; value: unknown }
  | { success: true; monitor_id: string; key: string; deleted: true };

/**
 * Per-monitor JSON key/value store surfaced as an MCP tool.
 *
 * Companion to `on_task_completed.py`: rule overrides that need to remember
 * cross-task state (e.g. `last_wakeup_time` for elder_wakeup) can persist it
 * here and read it back on the next task. Values are JSON-encoded on write
 * and parsed on read.
 */
export function stateQuery(db: SmartBuildingDB, params: StateQueryParams): StateQueryResult {
  const monitor = db.getMonitor(params.monitor_id);
  if (!monitor) throw new Error(`Monitor not found: ${params.monitor_id}`);

  switch (params.action) {
    case "get": {
      if (params.key === undefined) {
        return { state: db.listMonitorState(params.monitor_id) };
      }
      const value = db.getMonitorState(params.monitor_id, params.key);
      return { value: value === undefined ? null : value, key: params.key };
    }
    case "set": {
      if (params.key === undefined) throw new Error("`key` is required for action=set");
      if (params.value === undefined) throw new Error("`value` is required for action=set");
      db.setMonitorState(params.monitor_id, params.key, params.value);
      return {
        success: true,
        monitor_id: params.monitor_id,
        key: params.key,
        value: params.value,
      };
    }
    case "delete": {
      if (params.key === undefined) throw new Error("`key` is required for action=delete");
      db.deleteMonitorState(params.monitor_id, params.key);
      return {
        success: true,
        monitor_id: params.monitor_id,
        key: params.key,
        deleted: true,
      };
    }
    default: {
      const exhaust: never = params.action;
      throw new Error(`Unknown action: ${exhaust}`);
    }
  }
}
