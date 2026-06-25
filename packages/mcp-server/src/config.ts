import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { parse as parseYaml } from "yaml";
import type { SchemaDefinition } from "@smartbuilding-video/db";

export interface ServerConfig {
  // Derived from SMARTBUILDING_DATA_DIR — not settable in config.yaml
  dataDir: string;        // root: ~/.mcp-smartbuilding (or $SMARTBUILDING_DATA_DIR)
  dbPath: string;         // dataDir/smartbuilding.db
  segmentsDir: string;    // dataDir/segments/<monitor_id>/  (latest.jpg, queries/)
  logsDir: string;        // dataDir/logs/reports/  (SRT debug artifacts)

  summaryService: {
    url: string;
  };
  vlmService: {
    url: string;
    model: string;
    maxEdgePx: number;
  };
  videostreamAnalytics: {
    url: string;
  };
  schema?: SchemaDefinition;
  pollIntervalMs: number;
  videoSummaryMaxConcurrent: number;
  mcp?: {
    port?: number;
  };
  eventsWebhook?: {
    port?: number;
  };
}

function resolveDataDir(): string {
  const env = process.env.SMARTBUILDING_DATA_DIR;
  if (env) return resolve(env);
  return join(homedir(), ".mcp-smartbuilding");
}

export function loadConfig(configPath?: string): ServerConfig {
  const dataDir = resolveDataDir();

  const parsed = configPath
    ? parseYaml(readFileSync(resolve(configPath), "utf-8"))
    : {};

  return {
    dataDir,
    dbPath: join(dataDir, "smartbuilding.db"),
    segmentsDir: join(dataDir, "segments"),
    logsDir: join(dataDir, "logs", "reports"),

    summaryService: { url: parsed?.summary_service?.url ?? "http://localhost:8192" },
    vlmService: {
      url: parsed?.vlm_service?.url ?? "http://localhost:41091/v1",
      model: parsed?.vlm_service?.model ?? "default",
      maxEdgePx: parsed?.vlm_service?.max_edge_px ?? 720,
    },
    videostreamAnalytics: { url: parsed?.videostream_analytics?.url ?? "http://localhost:8999" },
    pollIntervalMs: parsed?.poll_interval_ms ?? 5000,
    videoSummaryMaxConcurrent: parsed?.video_summary_max_concurrent ?? 2,
    schema: parsed?.schema,
    mcp: { port: parsed?.mcp?.port ?? 3100 },
    eventsWebhook: { port: parsed?.events_webhook?.port ?? 3101 },
  };
}
