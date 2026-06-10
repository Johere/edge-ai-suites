import { readFileSync } from "node:fs";
import { resolve } from "node:path";

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
}

const DEFAULT_CONFIG: ServerConfig = {
  db: { path: "./data/smartbuilding.db" },
  summaryService: { url: "http://localhost:8192" },
  videostreamAnalytics: { url: "http://localhost:8080" },
  segmentsDir: "./segments",
};

export function loadConfig(configPath?: string): ServerConfig {
  if (!configPath) {
    return DEFAULT_CONFIG;
  }

  const resolved = resolve(configPath);
  const raw = readFileSync(resolved, "utf-8");

  // Simple YAML-like parsing for now; replace with proper yaml lib later
  // For skeleton, just return defaults
  console.error(`[config] Loaded config from ${resolved} (parsing not yet implemented, using defaults)`);
  return DEFAULT_CONFIG;
}
