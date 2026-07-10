import type { AlertSink, AlertPayload, Logger } from "@smartbuilding-video/framework-adapter-sdk";
import type { PluginConfig } from "./config.js";
import { formatAlert, formatSeparator } from "./format.js";
import { appendAlertTurns } from "./session-append.js";

/**
 * Subset of OpenClaw's `api.runtime.subagent` that we use. Runs an ephemeral subagent whose reply
 * is delivered to `sessionKey` (used only for the `deliver:true` / channel-bound path).
 */
export interface SubagentLike {
  run(params: {
    sessionKey: string;
    message: string;
    deliver?: boolean;
    extraSystemPrompt?: string;
    lane?: string;
    idempotencyKey?: string;
  }): Promise<{ runId: string }>;
}

// For channel-bound targets we still pay one LLM hop (the channel adapter runs an LLM), but pin it
// to a verbatim relay so the raw alert passes through unrewritten. Drops away once OpenClaw exposes
// a raw channel-send API.
const RELAY_PROMPT =
  "You are a message relay. Output the user's message verbatim — no rewriting, no additions, no questions.";

/**
 * OpenClaw AlertSink: routes each alert to the configured targets for its monitor.
 * - `deliver:false` (agent main session) → raw FS-append, zero LLM.
 * - `deliver:true`  (channel-bound session, e.g. Feishu) → subagent.run with a verbatim relay prompt.
 *
 * Idempotent per `alert.id` (the SDK guarantees at-least-once): the FS-append is naturally
 * idempotent-enough for a demo feed, and the `deliver:true` path passes an idempotencyKey so the
 * gateway suppresses a duplicate run.
 */
export function createOpenClawSink(deps: {
  config: PluginConfig;
  logger: Logger;
  subagent?: SubagentLike;
}): AlertSink {
  const { config, logger, subagent } = deps;

  return {
    async push({ monitorId, alert }: AlertPayload): Promise<void> {
      const targets = config.monitors[monitorId]?.alerts ?? [];
      if (targets.length === 0) {
        logger.warn(`[sb-alerts] no alert route configured for monitor=${monitorId} (alert id=${alert.id})`);
        return;
      }

      const separator = formatSeparator(alert);
      const body = formatAlert(alert);
      const idempotencyKey = `sb-alert:${monitorId}:${alert.id}`;

      await Promise.all(
        targets.map(async (t) => {
          if (t.deliver) {
            if (!subagent) {
              logger.error(
                `[sb-alerts] target ${t.sessionKey} needs deliver:true but api.runtime.subagent is unavailable — dropped alert id=${alert.id}`,
              );
              return;
            }
            try {
              const res = await subagent.run({
                sessionKey: t.sessionKey,
                message: body,
                deliver: true,
                lane: "alert",
                extraSystemPrompt: RELAY_PROMPT,
                idempotencyKey,
              });
              logger.info(`[sb-alerts] delivered alert id=${alert.id} → ${t.sessionKey} (runId=${res.runId})`);
            } catch (err) {
              logger.warn(`[sb-alerts] deliver failed alert id=${alert.id} → ${t.sessionKey}: ${err}`);
            }
            return;
          }

          const r = appendAlertTurns({
            agentId: t.agentId,
            sessionKey: t.sessionKey,
            separatorText: separator,
            assistantText: body,
            logger,
          });
          if (r.ok) {
            logger.info(`[sb-alerts] appended alert id=${alert.id} → ${t.sessionKey} (sid=${r.sessionId})`);
          } else {
            logger.warn(`[sb-alerts] append failed alert id=${alert.id} → ${t.sessionKey}: ${r.reason}`);
          }
        }),
      );
    },
  };
}
