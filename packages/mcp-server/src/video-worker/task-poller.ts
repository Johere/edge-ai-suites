import type { ServerConfig } from "../config.js";

/**
 * Polls the DB at intervals for pending video summary tasks.
 */
export class TaskPoller {
  private intervals: Map<string, ReturnType<typeof setInterval>> = new Map();
  private pollIntervalMs = 5000;
  private config: ServerConfig;

  constructor(config: ServerConfig) {
    this.config = config;
  }

  startPolling(monitorId: string): void {
    if (this.intervals.has(monitorId)) return;

    const interval = setInterval(() => {
      this.poll(monitorId);
    }, this.pollIntervalMs);

    this.intervals.set(monitorId, interval);
  }

  stopPolling(monitorId: string): void {
    const interval = this.intervals.get(monitorId);
    if (interval) {
      clearInterval(interval);
      this.intervals.delete(monitorId);
    }
  }

  private async poll(monitorId: string): Promise<void> {
    // TODO: query DB for pending tasks where monitor_id = monitorId
    // TODO: for each pending task, call VLM client and update DB
  }
}
