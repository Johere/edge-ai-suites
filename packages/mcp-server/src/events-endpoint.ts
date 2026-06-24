import { createServer, type Server } from "node:http";
import type { ServerConfig } from "./config.js";
import type { SmartBuildingDB } from "@smartbuilding-video/db";
import { logger } from "./logger.js";

export interface VideoEvent {
  sourceId: string;
  type: "motion" | "static" | "summary_completed";
  timestamp: string;
  payload: Record<string, unknown>;
}

export type EventCallback = (event: VideoEvent) => void;

/**
 * HTTP webhook receiver for events from videostream-analytics.
 * Listens on a dedicated port for POST /events.
 */
export class EventsEndpoint {
  private server: Server | null = null;
  private config: ServerConfig;
  private db: SmartBuildingDB;
  private onEvent?: EventCallback;

  constructor(config: ServerConfig, db: SmartBuildingDB, onEvent?: EventCallback) {
    this.config = config;
    this.db = db;
    this.onEvent = onEvent;
  }

  start(port: number = 3101): Promise<void> {
    return new Promise((resolve, reject) => {
      this.server = createServer((req, res) => {
        if (req.method === "POST" && req.url === "/events") {
          let body = "";
          req.on("data", (chunk) => { body += chunk; });
          req.on("end", () => {
            try {
              const event = JSON.parse(body) as VideoEvent;
              this.handleEvent(event);
              res.writeHead(200, { "Content-Type": "application/json" });
              res.end(JSON.stringify({ status: "ok" }));
            } catch (err: any) {
              res.writeHead(400, { "Content-Type": "application/json" });
              res.end(JSON.stringify({ error: err.message }));
            }
          });
        } else if (req.method === "GET" && req.url === "/health") {
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ status: "healthy" }));
        } else {
          res.writeHead(404);
          res.end();
        }
      });

      this.server.on("error", (err: NodeJS.ErrnoException) => {
        if (err.code === "EADDRINUSE") {
          logger.warn(`[events-endpoint] Port ${port} in use, skipping events endpoint`);
          this.server = null;
          resolve();
        } else {
          reject(err);
        }
      });

      this.server.listen(port, () => {
        logger.info(`[events-endpoint] Listening on port ${port}`);
        resolve();
      });
    });
  }

  stop(): void {
    this.server?.close();
    this.server = null;
  }

  private handleEvent(event: VideoEvent): void {
    if (event.type === "motion" || event.type === "summary_completed") {
      const videoPath = event.payload.video_path as string | undefined;
      if (videoPath && event.sourceId) {
        this.db.createTask({
          monitorId: event.sourceId,
          clipFilePath: videoPath,
          status: "pending",
        });
      }
    }

    if (this.onEvent) {
      this.onEvent(event);
    }
  }
}
