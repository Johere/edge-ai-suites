export interface MonitorCtlParams {
  action: "start" | "stop" | "register_source" | "list";
  monitorId?: string;
  sourceUrl?: string;
}

export async function monitorCtl(params: MonitorCtlParams): Promise<unknown> {
  // TODO: implement
  return {};
}
