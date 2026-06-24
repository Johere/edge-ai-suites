import type { ServerConfig } from "../config.js";
import type { SmartBuildingDB } from "@smartbuilding-video/db";
import type { VideoSummaryClient } from "./video-summary-client.js";
import type { VideoSummaryYield } from "./video-summary-yield.js";
import type { AlertCallback } from "./index.js";

export class TaskPoller {
  private intervals: Map<string, ReturnType<typeof setInterval>> = new Map();
  private config: ServerConfig;
  private db: SmartBuildingDB;
  private videoSummaryClient: VideoSummaryClient;
  private yieldManager: VideoSummaryYield;
  private onAlert?: AlertCallback;

  constructor(
    config: ServerConfig,
    db: SmartBuildingDB,
    videoSummaryClient: VideoSummaryClient,
    yieldManager: VideoSummaryYield,
    onAlert?: AlertCallback,
  ) {
    this.config = config;
    this.db = db;
    this.videoSummaryClient = videoSummaryClient;
    this.yieldManager = yieldManager;
    this.onAlert = onAlert;
  }

  startPolling(monitorId: string): void {
    if (this.intervals.has(monitorId)) return;

    const interval = setInterval(() => {
      this.poll(monitorId);
    }, this.config.pollIntervalMs);

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
    const tasks = this.db.getPendingTasks(monitorId, 1);
    if (tasks.length === 0) return;

    const task = tasks[0];

    try {
      await this.yieldManager.acquire();
      this.db.updateTaskStatus(task.id, "processing");

      const videoPath = `${this.config.segmentsDir}/${task.videoPath}`;
      const result = await this.videoSummaryClient.summarize({ videoUrl: videoPath, taskId: String(task.id) });

      this.db.updateTaskStatus(task.id, "completed", result.summary);

      if (result.events) {
        for (const event of result.events) {
          const severity = String(event.severity ?? "medium");
          const eventName = String(event.event ?? "unknown");
          const desc = String(event.desc ?? "");

          this.db.createAlert({
            monitorId,
            taskId: task.id,
            useCase: "",
            alertType: eventName,
            description: desc,
          });

          if (this.onAlert) {
            this.onAlert(monitorId, eventName, severity, desc);
          }
        }
      }
    } catch (err: any) {
      this.db.updateTaskStatus(task.id, "failed", err.message);
    } finally {
      this.yieldManager.release();
    }
  }
}
