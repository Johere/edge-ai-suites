import type { ServerConfig } from "../config.js";
import { TaskPoller } from "./task-poller.js";
import { VlmClient } from "./vlm-client.js";

export interface MonitorWorker {
  monitorId: string;
  running: boolean;
}

/**
 * WorkerService — manages per-monitor async loops.
 * Polls DB for pending video summary tasks and dispatches to VLM service.
 */
export class WorkerService {
  private workers: Map<string, MonitorWorker> = new Map();
  private poller: TaskPoller;
  private vlmClient: VlmClient;

  constructor(config: ServerConfig) {
    this.vlmClient = new VlmClient(config.summaryService.url);
    this.poller = new TaskPoller(config);
  }

  start(monitorId: string): void {
    if (this.workers.has(monitorId)) return;
    this.workers.set(monitorId, { monitorId, running: true });
    this.poller.startPolling(monitorId);
  }

  stop(monitorId: string): void {
    const worker = this.workers.get(monitorId);
    if (worker) {
      worker.running = false;
      this.poller.stopPolling(monitorId);
      this.workers.delete(monitorId);
    }
  }

  listWorkers(): MonitorWorker[] {
    return [...this.workers.values()];
  }
}
