export interface Monitor {
  id: string;
  name: string;
  sourceUrl: string;
  status: "online" | "offline" | "error";
  useCaseId: string;
  createdAt: string;
}

export interface Alert {
  id: number;
  sourceId: string;
  event: string;
  severity: string;
  description: string;
  acked: boolean;
  createdAt: string;
}

export interface VideoSummaryTask {
  id: number;
  monitorId: string;
  videoPath: string;
  status: "pending" | "processing" | "completed" | "failed";
  summary?: string;
  createdAt: string;
  completedAt?: string;
}
