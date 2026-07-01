import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { promisify } from "node:util";
import type { ServerConfig } from "../config.js";
import type { SmartBuildingDB } from "@smartbuilding-video/db";
import type { VideoSummaryClient } from "@smartbuilding-video/tools";
import type { VideoSummaryYield } from "./video-summary-yield.js";
import type { AlertCallback } from "./index.js";
import type { RuleContext, RuleResult } from "@smartbuilding-video/rule-engine";
import { evaluateWithOverride, parseSummaryFields } from "@smartbuilding-video/rule-engine";
import { logger } from "../logger.js";

const execFileAsync = promisify(execFile);

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
    const monitor = this.db.getMonitor(monitorId);
    const useCase = monitor?.useCase ?? "";
    const useCaseCfg = this.config.useCaseDict[useCase];
    const summaryTaskName = monitor?.videoSummaryTask ?? "";

    try {
      await this.yieldManager.acquire();
      this.db.updateTaskStatus(task.id, "processing");

      const videoPath = task.summaryClipInput ?? "";
      const t0 = Date.now();
      // Per-clip summarize tuning is configurable via use_case_dict.<useCase>.summarize.
      // Defaults below match the legacy smarthome stream_monitor config: LOCAL_PROMPT
      // only (levels=1), no T-1 dependency (method=SIMPLE), 2 fps sampling.
      const summarizeCfg = useCaseCfg?.summarize ?? {};
      const result = await this.videoSummaryClient.summarize({
        video: videoPath,
        task: summaryTaskName,
        method: summarizeCfg.method ?? "SIMPLE",
        processor_kwargs: {
          levels: summarizeCfg.processor_kwargs?.levels ?? 1,
          level_sizes: summarizeCfg.processor_kwargs?.level_sizes ?? [-1],
          process_fps: summarizeCfg.processor_kwargs?.process_fps ?? 2,
          ...(summarizeCfg.processor_kwargs?.chunking_method
            ? { chunking_method: summarizeCfg.processor_kwargs.chunking_method }
            : {}),
        },
      });
      const latencySeconds = (Date.now() - t0) / 1000;

      // VLM output parser. When `parse_summary_path` is set, run the Python
      // override; otherwise fall back to the schema-aware built-in parser.
      const extensions = this.config.schema?.video_summary_tasks?.extensions ?? [];
      const parsed = await this.parseSummary(
        result.summary ?? "",
        extensions,
        useCaseCfg?.parse_summary_path,
      );
      if (parsed.missingRequired.length > 0) {
        logger.warn(`[task-poller] task ${task.id} (${monitorId}) missing required schema fields: ${parsed.missingRequired.join(", ")}`);
      }

      // Persist summary text + extension fields + service usage in one UPDATE.
      this.db.updateTaskStatus(task.id, "completed", result.summary ?? "", {
        latencySeconds,
        promptTokens: result.usage?.prompt_tokens,
        imageTokens: result.usage?.image_tokens,
        completionTokens: result.usage?.completion_tokens,
      }, parsed.fields);

      // Evaluate rules via rule engine. Override path (Python script) is derived
      // from config.useCaseDict[monitor.useCase].evaluate_rules_path; absent → defaultRuleEvaluator.
      const overridePath = useCaseCfg?.evaluate_rules_path ?? null;
      const ruleCtx = {
        monitorId,
        useCase,
        taskId: task.id,
        summaryText: result.summary ?? "",
        payload: {
          fields: parsed.fields,
          rules: useCaseCfg?.rules ?? {},
        },
      };
      const ruleResult = await evaluateWithOverride(ruleCtx, overridePath);

      if (ruleResult.shouldAlert) {
        // Cooldown check: suppress if another alert for the same monitor +
        // use case is still within the configured window. `rules.cooldownSeconds`
        // is honoured for the built-in evaluator and — by convention — read by
        // Python overrides that want the same behaviour. A missing / zero /
        // negative value disables cooldown.
        const cooldownSec = Number((useCaseCfg?.rules as any)?.cooldownSeconds ?? 0);
        let suppressed = false;
        if (cooldownSec > 0) {
          const recent = this.db.latestAlertWithin(monitorId, useCase, cooldownSec);
          if (recent) {
            suppressed = true;
            logger.debug(
              `[task-poller] cooldown suppressed alert for ${monitorId}/${useCase} ` +
              `(previous alert id=${recent.id} at ${recent.createdAt}, cooldown=${cooldownSec}s)`,
            );
          }
        }

        if (!suppressed) {
          const alert = this.db.createAlert({
            monitorId,
            taskId: task.id,
            eventId: task.eventId,
            useCase,
            description: ruleResult.alertMessage,
          });
          if (this.onAlert) {
            this.onAlert(monitorId);
          }
          // Optional post-processing callback (see design §5.3).
          const onTaskPath = useCaseCfg?.on_task_completed_path;
          if (onTaskPath) {
            void this.runOnTaskCompleted(onTaskPath, ruleCtx, ruleResult, alert.id);
          }
        }
      }
    } catch (err: any) {
      logger.error(`[task-poller] task ${task.id} (${monitorId}) failed: ${err.message}`);
      this.db.updateTaskStatus(task.id, "failed", undefined, { errorMessage: err.message });
    } finally {
      this.yieldManager.release();
    }
  }

  /**
   * Parse VLM `summary_text` into schema fields. When `overridePath` is
   * supplied and exists, invoke the Python override:
   *
   *   argv[1] = {"summary": <text>, "extensions": [<SchemaExtension>...]}
   *   stdout  = {"fields": {<name>: <value>}, "missingRequired": [<name>]}
   *
   * Any failure (missing script, non-zero exit, bad JSON) falls back to the
   * schema-aware built-in parser so a broken override cannot stall the poller.
   */
  private async parseSummary(
    summary: string,
    extensions: any[],
    overridePath?: string,
  ): Promise<{ fields: Record<string, string>; missingRequired: string[] }> {
    if (overridePath && existsSync(overridePath)) {
      try {
        const { stdout } = await execFileAsync("python3", [
          overridePath,
          JSON.stringify({ summary, extensions }),
        ], { timeout: 10_000 });
        const parsed = JSON.parse(stdout.trim());
        return {
          fields: (parsed.fields ?? {}) as Record<string, string>,
          missingRequired: Array.isArray(parsed.missingRequired) ? parsed.missingRequired : [],
        };
      } catch (err: any) {
        logger.warn(
          `[task-poller] parse_summary override failed (${overridePath}), ` +
            `falling back to built-in parser: ${err.message}`,
        );
      }
    }
    return parseSummaryFields(summary, extensions);
  }

  /**
   * Fire-and-forget post-alert callback (design §5.3 on_task_completed).
   * Receives JSON on argv[1] with the same shape as the rule-engine context
   * plus the newly-created `alertId`. Never rejects — failures log a warning
   * and are otherwise dropped so a broken callback cannot stall the poller.
   */
  private async runOnTaskCompleted(
    scriptPath: string,
    ruleCtx: RuleContext,
    ruleResult: RuleResult,
    alertId: number,
  ): Promise<void> {
    if (!existsSync(scriptPath)) {
      logger.warn(`[task-poller] on_task_completed script missing: ${scriptPath}`);
      return;
    }
    const payload = {
      ...ruleCtx,
      alertId,
      alertMessage: ruleResult.alertMessage ?? "",
    };
    try {
      await execFileAsync("python3", [scriptPath, JSON.stringify(payload)], {
        timeout: 10_000,
      });
    } catch (err: any) {
      logger.warn(
        `[task-poller] on_task_completed failed for ${ruleCtx.useCase} ` +
          `(task=${ruleCtx.taskId}): ${err.message}`,
      );
    }
  }
}
