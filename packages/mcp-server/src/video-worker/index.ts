import type { ServerConfig } from "../config.js";
import type { SmartBuildingDB } from "@smartbuilding-video/db";
import { TaskPoller } from "./task-poller.js";
import { VlmClient } from "./vlm-client.js";
import { VllmYield } from "./vllm-yield.js";

export interface MonitorWorker {
  monitorId: string;
  running: boolean;
}

export type AlertCallback = (monitorId: string, event: string, severity: string, description: string) => void;

export class WorkerService {
  private workers: Map<string, MonitorWorker> = new Map();
  private poller: TaskPoller;
  private onAlert?: AlertCallback;

  constructor(config: ServerConfig, db: SmartBuildingDB, onAlert?: AlertCallback) {
    const vlmClient = new VlmClient(config.summaryService.url);
    const yieldManager = new VllmYield(config.vlmMaxConcurrent);
    this.poller = new TaskPoller(config, db, vlmClient, yieldManager, onAlert);
    this.onAlert = onAlert;
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

  stopAll(): void {
    for (const id of this.workers.keys()) {
      this.stop(id);
    }
  }
}
