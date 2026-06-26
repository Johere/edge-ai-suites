import { createServer, type Server } from "node:http";
import type { SmartBuildingDB } from "@smartbuilding-video/db";
import { logger } from "./logger.js";

export interface VideoEvent {
  sourceId: string;
  type: "motion" | "static" | "recording";
  timestamp: string;
  payload: Record<string, unknown>;
}

export type EventCallback = (event: VideoEvent) => void;

/**
 * HTTP webhook receiver for events from videostream-analytics.
 * Listens on a dedicated port for POST /events.
 *
 * Webhook protocol (analytics → MCP server):
 *   motion:    writes events (motion_type=motion) + video_summary_tasks
 *   static:    writes events (motion_type=static) only
 *   recording: writes recordings only
 */
export class EventsEndpoint {
  private server: Server | null = null;
  private db: SmartBuildingDB;
  private onEvent?: EventCallback;

  /**
   * @param db DB the handler writes events / video_summary_tasks / recordings into.
   * @param onEvent Optional hook fired after every successfully handled webhook.
   *   Reserved as an extension point — currently no production caller passes one
   *   (alert subscription pushes happen in the task-poller alert path, not here).
   */
  constructor(db: SmartBuildingDB, onEvent?: EventCallback) {
    this.db = db;
    this.onEvent = onEvent;
  }

  /**
   * Bind the webhook HTTP server.
   *
   * Resolves once the listener is ready or the port was already in use (in which case
   * a warning is logged and the endpoint silently runs in disabled state — analytics
   * won't be able to push events but the rest of MCP server keeps working).
   * Rejects only on non-EADDRINUSE errors (permission denied, invalid host, etc.).
   *
   * Exposes:
   *   POST /events  → handleEvent
   *   GET  /health  → 200 OK
   *   *             → 404
   */
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

  /**
   * Close the HTTP listener. Existing in-flight requests finish on their own;
   * this does not await them. Safe to call multiple times.
   */
  stop(): void {
    this.server?.close();
    this.server = null;
  }

  /**
   * Dispatch a parsed VideoEvent into DB writes based on `event.type`.
   *
   * Per-type contract — payload fields the analytics service must send:
   *   motion    → event_file_path, summary_clip_input, start_time, duration_seconds
   *               (prefilter_* optional; if prefilter_passed=0 the created task is
   *                marked `ignored` so video-worker skips the VLM call)
   *   static    → start_time, duration_seconds
   *   recording → recording_path, recording_start, recording_end
   *
   * Missing required fields → log a warning and skip this event (no DB writes),
   * but always returns 200 to the analytics caller so a single bad payload won't
   * back-pressure the upstream pipeline.
   *
   * `onEvent` (if provided to the constructor) is invoked after a successful dispatch
   * regardless of type — reserved extension point, no production caller wires it today.
   */
  private handleEvent(event: VideoEvent): void {
    const p = event.payload;
    const monitorId = event.sourceId;

    switch (event.type) {
      case "motion": {
        // Required: event_file_path (original), summary_clip_input (crop/prepared for summary), start_time, duration_seconds
        if (!p.event_file_path || !p.summary_clip_input || !p.start_time || !p.duration_seconds) {
          logger.warn(`[events-endpoint] motion event from ${monitorId} missing required fields (event_file_path, summary_clip_input, start_time, duration_seconds) — skipping`);
          break;
        }
        // Write events table
        const ev = this.db.createEvent({
          monitorId,
          motionType: "motion",
          startTime: String(p.start_time),
          endTime: p.end_time ? String(p.end_time) : undefined,
          durationSeconds: Number(p.duration_seconds),
          eventFilePath: String(p.event_file_path),
          prefilterPassed: p.prefilter_passed !== undefined ? Number(p.prefilter_passed) : undefined,
          prefilterClasses: p.prefilter_classes ? String(p.prefilter_classes) : undefined,
          prefilterConfidence: p.prefilter_confidence !== undefined ? Number(p.prefilter_confidence) : undefined,
          trajectoryRegion: p.trajectory_region ? String(p.trajectory_region) : undefined,
        });
        // Determine task status based on prefilter result
        let taskStatus: "pending" | "ignored" = "pending";
        if (p.prefilter_passed !== undefined && Number(p.prefilter_passed) === 0) {
          taskStatus = "ignored";
        }
        // Write video_summary_tasks table
        this.db.createTask({
          monitorId,
          eventId: ev.id,
          summaryClipInput: String(p.summary_clip_input),
          status: taskStatus,
        });
        break;
      }

      case "static": {
        // Required: start_time, duration_seconds
        if (!p.start_time || !p.duration_seconds) {
          logger.warn(`[events-endpoint] static event from ${monitorId} missing required fields (start_time, duration_seconds) — skipping`);
          break;
        }
        this.db.createEvent({
          monitorId,
          motionType: "static",
          startTime: String(p.start_time),
          endTime: p.end_time ? String(p.end_time) : undefined,
          durationSeconds: Number(p.duration_seconds),
        });
        break;
      }

      case "recording": {
        // Required: recording_path, recording_start, recording_end
        if (!p.recording_path || !p.recording_start || !p.recording_end) {
          logger.warn(`[events-endpoint] recording event from ${monitorId} missing required fields (recording_path, recording_start, recording_end) — skipping`);
          break;
        }
        this.db.createRecording({
          monitorId,
          filePath: String(p.recording_path),
          startTime: String(p.recording_start),
          endTime: String(p.recording_end),
          durationSeconds: p.duration_seconds !== undefined ? Number(p.duration_seconds) : undefined,
          fileSizeBytes: p.file_size_bytes !== undefined ? Number(p.file_size_bytes) : undefined,
        });
        break;
      }

      default:
        logger.warn(`[events-endpoint] unknown event type "${(event as any).type}" from ${monitorId} — ignored`);
    }

    if (this.onEvent) {
      this.onEvent(event);
    }
  }
}
