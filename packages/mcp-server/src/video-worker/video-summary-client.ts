export interface SummaryRequest {
  /** Path to the video file. Supports file://, http(s):// or local absolute path. */
  video: string;
  /** Task name registered in multilevel-video-understanding (e.g. "child_safety_monitor"). */
  task?: string;
  /** Optional user prompt forwarded as `{question}` template variable. */
  prompt?: string;
}

export interface SummaryUsage {
  prompt_tokens?: number;
  image_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
}

export interface SummaryResponse {
  /** "success" | "failed" — same string the service writes to its own status field. */
  status: string;
  /** The summary text; non-null when status="success". */
  summary: string | null;
  message?: string;
  job_id?: string;
  video_name?: string;
  video_duration?: number;
  usage?: SummaryUsage;
}

/** Host↔container path remap. See ServerConfig.summaryService.pathRemap. */
export interface PathRemap {
  hostPrefix: string;
  containerPrefix: string;
}

/**
 * REST client for multilevel-video-understanding. Field names match the service's
 * SummarizationRequest schema exactly — see GET /v1/openapi.json.
 */
export class VideoSummaryClient {
  private baseUrl: string;
  private pathRemap?: PathRemap;

  constructor(baseUrl: string, pathRemap?: PathRemap) {
    this.baseUrl = baseUrl;
    this.pathRemap = pathRemap;
  }

  private remapVideoPath(path: string): string {
    if (!this.pathRemap) return path;
    const { hostPrefix, containerPrefix } = this.pathRemap;
    if (path.startsWith(hostPrefix)) {
      return containerPrefix + path.slice(hostPrefix.length);
    }
    return path;
  }

  async summarize(request: SummaryRequest): Promise<SummaryResponse> {
    const remapped: SummaryRequest = { ...request, video: this.remapVideoPath(request.video) };
    const response = await fetch(`${this.baseUrl}/v1/summary`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(remapped),
    });

    if (!response.ok) {
      // Capture FastAPI's structured error body so callers can see what went wrong
      // (missing field name, bad video path, unknown task, etc.).
      let detail: string;
      try { detail = JSON.stringify(await response.json()); }
      catch { detail = response.statusText; }
      throw new Error(`video-summary HTTP ${response.status}: ${detail}`);
    }

    const body = (await response.json()) as SummaryResponse;
    if (body.status !== "success") {
      throw new Error(`video-summary status=${body.status}: ${body.message ?? "<no message>"}`);
    }
    return body;
  }
}
