// Re-export the OpenClaw plugin SDK surface this example uses. Mirrors smarthome-video/api.ts —
// the `openclaw` package is provided by the gateway at bundle/load time (not a repo dependency),
// so this file (and index.ts) are validated by OpenClaw's bundler, not by the repo's tsc.
export {
  definePluginEntry,
  type OpenClawPluginApi,
} from "openclaw/plugin-sdk/plugin-entry";
