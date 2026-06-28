import type { ServerConfig } from "../config.js";
import type { SmartBuildingDB } from "@smartbuilding-video/db";
import type { VideoSummaryClient } from "./video-summary-client.js";
import type { VideoSummaryYield } from "./video-summary-yield.js";
import type { AlertCallback } from "./index.js";
import { evaluateWithOverride, parseSummaryFields } from "@smartbuilding-video/rule-engine";
import { logger } from "../logger.js";

export class TaskPoller {
  private intervals: Map<string, ReturnType<typeof setInterval>> = new Map();
  // Tracks the currently in-flight poll promise per monitor for graceful stop
  private activePoll: Map<string, Promise<void>> = new Map();
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

      // Schema-aware parse of VLM output: only fields declared in
      // config.schema.video_summary_tasks.extensions are extracted.
      const extensions = this.config.schema?.video_summary_tasks?.extensions ?? [];
      const parsed = parseSummaryFields(result.summary ?? "", extensions);
      if (parsed.missingRequired.length > 0) {
        logger.warn(`[task-poller] task ${task.id} (${monitorId}) missing required schema fields: ${parsed.missingRequired.join(", ")}`);
      }

      // Persist summary text + parsed extension fields in one UPDATE
      this.db.updateTaskStatus(task.id, "completed", result.summary, undefined, parsed.fields);

      // Evaluate rules via rule engine. Override path (Python script) is derived
      // from config.useCaseDict[monitor.useCase].evaluate_rules_path; absent → defaultRuleEvaluator.
      const monitor = this.db.getMonitor(monitorId);
      const useCase = monitor?.useCase ?? "";
      const overridePath = this.config.useCaseDict[useCase]?.evaluate_rules_path ?? null;
      const ruleCtx = {
        monitorId,
        useCase,
        taskId: task.id,
        summaryText: result.summary ?? "",
        payload: { fields: parsed.fields },
      };
      const ruleResult = await evaluateWithOverride(ruleCtx, overridePath);

      if (ruleResult.shouldAlert) {
        this.db.createAlert({
          monitorId,
          taskId: task.id,
          eventId: task.eventId,
          useCase: monitor?.useCase ?? "",
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
