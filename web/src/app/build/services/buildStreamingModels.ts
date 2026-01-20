// =============================================================================
// Usage Limits Types
// =============================================================================

export type LimitType = "weekly" | "total";

export interface UsageLimits {
  /** Whether the user has reached their limit */
  isLimited: boolean;
  /** Type of limit period: "weekly" for paid, "total" for free */
  limitType: LimitType;
  /** Number of messages used in current period */
  messagesUsed: number;
  /** Maximum messages allowed in the period */
  limit: number;
  /** For weekly limits: timestamp when the limit resets (null for total limits) */
  resetTimestamp: Date | null;
}

// API response shape (snake_case from backend)
export interface ApiUsageLimitsResponse {
  is_limited: boolean;
  limit_type: LimitType;
  messages_used: number;
  limit: number;
  reset_timestamp: string | null;
}

// =============================================================================
// Artifact & Message Types
// =============================================================================

export type ArtifactType =
  | "nextjs_app"
  | "pptx"
  | "xlsx"
  | "docx"
  | "markdown"
  | "chart"
  | "csv"
  | "image";

export interface Artifact {
  id: string;
  session_id: string;
  type: ArtifactType;
  name: string;
  path: string;
  preview_url?: string | null;
  created_at: Date;
  updated_at: Date;
}

export interface BuildMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: Date;
  // TODO: Add tool calls, artifacts references, etc.
}

export type SessionStatus =
  | "idle"
  | "creating"
  | "running"
  | "completed"
  | "failed";

export interface Session {
  id: string | null;
  status: SessionStatus;
  artifacts: Artifact[];
  messages: BuildMessage[];
  error: string | null;
  webappUrl: string | null;
}

export interface SessionHistoryItem {
  id: string;
  title: string;
  createdAt: Date;
}

// =============================================================================
// API Response Types
// =============================================================================

export interface ApiSessionResponse {
  id: string;
  org_id: string;
  user_id: string;
  sandbox_id: string | null;
  name: string | null;
  status: "active" | "idle" | "archived";
  created_at: string;
  last_activity_at: string;
}

export interface ApiMessageResponse {
  id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface ApiArtifactResponse {
  id: string;
  session_id: string;
  type: ArtifactType;
  path: string;
  name: string;
  created_at: string;
  updated_at: string;
  preview_url?: string | null;
}

// =============================================================================
// SSE Packet Types
// =============================================================================

export interface StepStartPacket {
  type: "step_start";
  step_id: string;
  title?: string;
}

export interface StepDeltaPacket {
  type: "step_delta";
  step_id: string;
  content: string;
}

export interface StepEndPacket {
  type: "step_end";
  step_id: string;
  status: "success" | "failed" | "skipped";
}

export interface OutputStartPacket {
  type: "output_start";
}

export interface OutputDeltaPacket {
  type: "output_delta";
  content: string;
}

export interface ArtifactCreatedPacket {
  type: "artifact_created";
  artifact: {
    id: string;
    type: ArtifactType;
    name: string;
    path: string;
    preview_url?: string;
  };
}

export interface DonePacket {
  type: "done";
  summary?: string;
}

export interface ErrorPacket {
  type: "error";
  message: string;
  code?: string;
}

export type StreamPacket =
  | StepStartPacket
  | StepDeltaPacket
  | StepEndPacket
  | OutputStartPacket
  | OutputDeltaPacket
  | ArtifactCreatedPacket
  | DonePacket
  | ErrorPacket
  | { type: string }; // catch-all for unknown packet types
