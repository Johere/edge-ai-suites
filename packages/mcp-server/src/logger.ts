// MCP server uses stderr for all logging — stdout is reserved for JSON-RPC.
// Set LOG_LEVEL=debug to enable debug output (default: info).

type Level = "debug" | "info" | "warn" | "error";

const LEVELS: Record<Level, number> = { debug: 0, info: 1, warn: 2, error: 3 };

const configured = (process.env.LOG_LEVEL ?? "info").toLowerCase() as Level;
const minLevel = LEVELS[configured] ?? LEVELS.info;

function log(level: Level, msg: string): void {
  if (LEVELS[level] >= minLevel) {
    const tag = level.toUpperCase().padEnd(5);
    console.error(`[${tag}] ${msg}`);
  }
}

export const logger = {
  debug: (msg: string) => log("debug", msg),
  info:  (msg: string) => log("info",  msg),
  warn:  (msg: string) => log("warn",  msg),
  error: (msg: string) => log("error", msg),
};
