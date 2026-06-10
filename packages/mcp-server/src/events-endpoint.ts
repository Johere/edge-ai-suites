import type { ServerConfig } from "./config.js";

export interface VideoEvent {
  sourceId: string;
  type: "motion" | "static" | "summary_completed";
  timestamp: string;
  payload: Record<string, unknown>;
}

/**
 * Webhook receiver for events from videostream-analytics.
 * Writes events to DB and triggers resource subscription notifications.
 */
export class EventsEndpoint {
  private config: ServerConfig;

  constructor(config: ServerConfig) {
    this.config = config;
  }

  async handleEvent(event: VideoEvent): Promise<void> {
    // TODO: write event to DB
    // TODO: trigger MCP resource subscription notification
  }
}
