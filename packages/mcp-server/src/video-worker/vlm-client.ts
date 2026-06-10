export interface SummaryRequest {
  videoUrl: string;
  prompt?: string;
  taskId?: string;
}

export interface SummaryResponse {
  summary: string;
  events?: Array<Record<string, unknown>>;
}

/**
 * REST client for the multi-level video understanding service.
 */
export class VlmClient {
  private baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  async summarize(request: SummaryRequest): Promise<SummaryResponse> {
    const response = await fetch(`${this.baseUrl}/v1/summary`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      throw new Error(`VLM service error: ${response.status} ${response.statusText}`);
    }

    return response.json() as Promise<SummaryResponse>;
  }

  async healthCheck(): Promise<boolean> {
    try {
      const response = await fetch(`${this.baseUrl}/v1/health`);
      return response.ok;
    } catch {
      return false;
    }
  }
}
