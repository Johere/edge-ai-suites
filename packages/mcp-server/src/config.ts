import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { parse as parseYaml } from "yaml";
import type { SchemaDefinition } from "@smartbuilding-video/db";

export interface ServerConfig {
  db: {
    path: string;
  };
  summaryService: {
    url: string;
  };
  videostreamAnalytics: {
    url: string;
  };
  segmentsDir: string;
  schema?: SchemaDefinition;
  pollIntervalMs: number;
  videoSummaryMaxConcurrent: number;
}

const DEFAULT_CONFIG: ServerConfig = {
  db: { path: "./data/smartbuilding.db" },
  summaryService: { url: "http://localhost:8192" },
  videostreamAnalytics: { url: "http://localhost:8999" },
  segmentsDir: "./segments",
  pollIntervalMs: 5000,
  videoSummaryMaxConcurrent: 2,
};

export function loadConfig(configPath?: string): ServerConfig {
  if (!configPath) {
    return DEFAULT_CONFIG;
  }

  const resolved = resolve(configPath);
  const raw = readFileSync(resolved, "utf-8");
  const parsed = parseYaml(raw);

  return {
    db: { path: parsed?.db?.path ?? DEFAULT_CONFIG.db.path },
    summaryService: { url: parsed?.summary_service?.url ?? DEFAULT_CONFIG.summaryService.url },
    videostreamAnalytics: { url: parsed?.videostream_analytics?.url ?? DEFAULT_CONFIG.videostreamAnalytics.url },
    segmentsDir: parsed?.segments_dir ?? DEFAULT_CONFIG.segmentsDir,
    pollIntervalMs: parsed?.poll_interval_ms ?? DEFAULT_CONFIG.pollIntervalMs,
    videoSummaryMaxConcurrent: parsed?.video_summary_max_concurrent ?? DEFAULT_CONFIG.videoSummaryMaxConcurrent,
    schema: parsed?.schema,
  };
}
