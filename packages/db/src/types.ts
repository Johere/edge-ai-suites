export interface Monitor {
  id: string;
  name: string;
  sourceUrl: string;
  status: "online" | "offline" | "error";
  useCase: string;
  videoSummaryTask: string; // task name registered in multilevel-video-understanding service
  createdAt: string;
}

export interface Event {
  id: number;
  monitorId: string;
  motionType: string;          // "motion" | "static"
  startTime: string;
  endTime?: string;
  durationSeconds?: number;
  eventFilePath?: string;      // original video segment (*.mp4)
  prefilterPassed?: number;    // 0 | 1
  prefilterClasses?: string;   // JSON array: ["person","knife"]
  prefilterConfidence?: number;
  trajectoryRegion?: string;   // "x0,y0,x1,y1"
  createdAt: string;
}

export interface Recording {
  id: number;
  monitorId: string;
  filePath: string;
  startTime: string;
  endTime: string;
  durationSeconds?: number;
  fileSizeBytes?: number;
  createdAt: string;
}

export interface VideoSummaryTask {
  id: number;
  monitorId: string;
  eventId?: number;
  clipStartTime?: string;
  clipEndTime?: string;
  clipDuration?: number;
  summaryClipInput?: string;   // cropped/prepared clip sent to video summary service (*_input.mp4)
  summaryText?: string;
  status: "pending" | "processing" | "completed" | "failed" | "ignored";
  errorMessage?: string;
  latencySeconds?: number;
  promptTokens?: number;
  imageTokens?: number;
  completionTokens?: number;
  startedAt?: string;
  completedAt?: string;
  createdAt: string;
  // User-defined extension fields (added via SchemaManager, e.g. event, severity, desc)
  [key: string]: unknown;
}

export interface Alert {
  id: number;
  monitorId: string;
  taskId?: number;
  eventId?: number;
  useCase: string;
  alertType: string;
  description?: string;
  createdAt: string;
  ackAt?: string;
  ackBy?: string;
  // severity is NOT stored here — retrieve via task_id JOIN to video_summary_tasks
}

export interface Report {
  id: number;
  monitorId: string;
  useCase: string;
  periodStart: string;
  periodEnd: string;
  reportText?: string;
  eventCount?: number;
  motionCount?: number;
  latencySeconds?: number;
  promptTokens?: number;
  imageTokens?: number;
  completionTokens?: number;
  status: string;
  reportType: string;
  createdAt: string;
}

// Alert with JOIN'd task and event details
export interface AlertWithTask extends Alert {
  taskDetails?: {
    id: number;
    summaryClipInput?: string;
    summaryText?: string;
    status: string;
    // User-defined extension fields from video_summary_tasks (e.g. event, severity, desc)
    [key: string]: unknown;
  };
  eventDetails?: {
    id: number;
    motionType: string;
    startTime: string;
    endTime?: string;
  };
}
