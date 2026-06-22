export interface StateQueryParams {
  monitorId: string;
  action: "get" | "set";
  state?: Record<string, unknown>;
}

export async function stateQuery(params: StateQueryParams): Promise<unknown> {
  // TODO: implement
  return {};
}
