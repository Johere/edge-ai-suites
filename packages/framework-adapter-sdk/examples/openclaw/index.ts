import path from "node:path";
import os from "node:os";
import { definePluginEntry, type OpenClawPluginApi } from "./api.js";
import { SmartBuildingAdapter, FileCursorStore } from "@smartbuilding-video/framework-adapter-sdk";
import { parseConfig, ConfigError } from "./src/config.js";
import { createOpenClawSink, type SubagentLike } from "./src/sink.js";

function openclawHome(): string {
  return process.env.OPENCLAW_HOME ?? path.join(os.homedir(), ".openclaw");
}

/**
 * smartbuilding-alerts — a reference OpenClaw framework adapter.
 *
 * Subscribes (via @smartbuilding-video/framework-adapter-sdk) to the MCP server's per-monitor
 * alert resources and injects each new alert into the routed OpenClaw session(s). This is the
 * light "MCP subscribe + raw pass-through" path — complementary to smarthome-video's embedded
 * rule + persona-polish + FS-append heavy path.
 */
export default definePluginEntry({
  id: "smartbuilding-alerts",
  name: "SmartBuilding Alerts",
  description:
    "Subscribes to SmartBuilding MCP alert resources and delivers alerts into OpenClaw sessions (reference framework adapter).",
  register(api: OpenClawPluginApi) {
    let config;
    try {
      config = parseConfig(api.pluginConfig);
    } catch (err) {
      if (err instanceof ConfigError) {
        api.logger.error(`[sb-alerts] invalid plugin config: ${err.message} — adapter not started`);
        return;
      }
      throw err;
    }

    const subagent = api.runtime?.subagent as SubagentLike | undefined;
    if (!subagent) {
      api.logger.warn(
        "[sb-alerts] api.runtime.subagent unavailable — deliver:true (channel) targets will be skipped; " +
          "deliver:false (FS-append) targets still work.",
      );
    }

    const sink = createOpenClawSink({ config, logger: api.logger, subagent });

    const cursorFile =
      config.cursorFile ?? path.join(openclawHome(), "smartbuilding-alerts-cursor.json");

    const adapter = new SmartBuildingAdapter(
      {
        transport: { kind: "http", url: config.mcpServer.url, headers: config.mcpServer.headers },
        monitorIds: Object.keys(config.monitors),
        cursorStore: new FileCursorStore(cursorFile),
        pollFallbackMs: config.pollFallbackMs,
        logger: api.logger,
      },
      sink,
    );

    api.registerService({
      id: "smartbuilding-alerts-adapter",
      async start() {
        api.logger.info(
          `[sb-alerts] starting adapter → ${config.mcpServer.url} for ${Object.keys(config.monitors).length} monitor(s)`,
        );
        await adapter.start();
      },
      async stop() {
        await adapter.stop();
      },
    });
  },
});
