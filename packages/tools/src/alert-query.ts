export interface AlertQueryParams {
  monitorId?: string;
  status?: "unacked" | "acked" | "all";
  limit?: number;
}

export async function alertQuery(params: AlertQueryParams): Promise<unknown[]> {
  // TODO: implement
  return [];
}
