import type { ServerConfig } from "../config.js";
import type { SmartBuildingDB } from "@smartbuilding-video/db";
import type { VideoSummaryClient } from "./video-summary-client.js";
import type { VideoSummaryYield } from "./video-summary-yield.js";
import type { AlertCallback } from "./index.js";
import { defaultRuleEvaluator, type RuleEvaluator } from "@smartbuilding-video/rule-engine";

export class TaskPoller {
  private intervals: Map<string, ReturnType<typeof setInterval>> = new Map();
  // Tracks the currently in-flight poll promise per monitor for graceful stop
  private activePoll: Map<string, Promise<void>> = new Map();
  private config: ServerConfig;
  private db: SmartBuildingDB;
  private videoSummaryClient: VideoSummaryClient;
  private yieldManager: VideoSummaryYield;
  private onAlert?: AlertCallback;
  private ruleEvaluator: RuleEvaluator;

  constructor(
    config: ServerConfig,
    db: SmartBuildingDB,
    videoSummaryClient: VideoSummaryClient,
    yieldManager: VideoSummaryYield,
    onAlert?: AlertCallback,
    ruleEvaluator?: RuleEvaluator,
  ) {
    this.config = config;
    this.db = db;
    this.videoSummaryClient = videoSummaryClient;
    this.yieldManager = yieldManager;
    this.onAlert = onAlert;
    this.ruleEvaluator = ruleEvaluator ?? defaultRuleEvaluator;
  }

  startPolling(monitorId: string): void {
    if (this.intervals.has(monitorId)) return;

    const interval = setInterval(() => {
      const promise = this.poll(monitorId).then(() => {
        this.activePoll.delete(monitorId);
      });
      this.activePoll.set(monitorId, promise);
    }, this.config.pollIntervalMs);

    this.intervals.set(monitorId, interval);
  }

  async stopPolling(monitorId: string): Promise<void> {
    const interval = this.intervals.get(monitorId);
    if (interval) {
      clearInterval(interval);
      this.intervals.delete(monitorId);
    }
    // Wait for any in-flight poll to finish before returning
    const inflight = this.activePoll.get(monitorId);
    if (inflight) {
      await inflight;
      this.activePoll.delete(monitorId);
    }
  }

  private async poll(monitorId: string): Promise<void> {
    const tasks = this.db.getPendingTasks(monitorId, 1);
    if (tasks.length === 0) return;

    const task = tasks[0];

    try {
      await this.yieldManager.acquire();
      this.db.updateTaskStatus(task.id, "processing");

      const videoPath = task.summaryClipInput ?? "";
      const result = await this.videoSummaryClient.summarize({ videoUrl: videoPath, taskId: String(task.id) });

      this.db.updateTaskStatus(task.id, "completed", result.summary);

      // Evaluate rules via rule engine (defaultRuleEvaluator or injected override)
      const monitor = this.db.getMonitor(monitorId);
      const ruleCtx = {
        monitorId,
        useCase: monitor?.useCase ?? "",
        taskId: task.id,
        summaryText: result.summary ?? "",
        payload: {},
      };
      const ruleResult = await this.ruleEvaluator(ruleCtx);

      if (ruleResult.shouldAlert) {
        this.db.createAlert({
          monitorId,
          taskId: task.id,
          eventId: task.eventId,
          useCase: monitor?.useCase ?? "",
          alertType: ruleResult.alertType ?? "alert",
          description: ruleResult.alertMessage,
        });
        if (this.onAlert) {
          this.onAlert(monitorId);
        }
      }
    } catch (err: any) {
      this.db.updateTaskStatus(task.id, "failed", err.message);
    } finally {
      this.yieldManager.release();
    }
  }
}
