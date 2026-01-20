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
  | "web_app" // Backend sends this
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
  /** Tool calls associated with this message (for assistant messages) */
  toolCalls?: ToolCall[];
}

// =============================================================================
// Tool Call Types (for tracking agent tool usage)
// =============================================================================

export type ToolCallStatus =
  | "pending"
  | "in_progress"
  | "completed"
  | "failed"
  | "cancelled";

export interface ToolCall {
  /** Unique ID for this tool call */
  id: string;
  /** Tool kind/category (e.g., "edit", "execute", "other") */
  kind: string;
  /** Tool name (e.g., "write", "bash", "ls") */
  name: string;
  /** Human-readable title */
  title: string;
  /** Current status */
  status: ToolCallStatus;
  /** Tool input parameters */
  input?: Record<string, unknown>;
  /** Result content (when completed) */
  result?: string;
  /** Error message (when failed) */
  error?: string;
  /** When the tool call started */
  startedAt: Date;
  /** When the tool call finished */
  finishedAt?: Date;
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
// SSE Packet Types (matching backend build_packet_types.py)
// =============================================================================

// Step/Thinking Packets
export interface StepStartPacket {
  type: "step_start";
  step_id: string;
  step_name?: string;
  timestamp: string;
}

export interface StepDeltaPacket {
  type: "step_delta";
  step_id: string;
  content: string;
  timestamp: string;
}

export interface StepEndPacket {
  type: "step_end";
  step_id: string;
  status: "completed" | "failed" | "cancelled";
  timestamp: string;
}

// Tool Call Packets
export interface ToolStartPacket {
  type: "tool_start";
  tool_call_id: string;
  tool_name: string;
  tool_input: Record<string, any>;
  title?: string;
  timestamp: string;
}

export interface ToolProgressPacket {
  type: "tool_progress";
  tool_call_id: string;
  tool_name: string;
  status: "pending" | "in_progress" | "completed" | "failed" | "cancelled";
  progress?: number;
  message?: string;
  timestamp: string;
}

export interface ToolEndPacket {
  type: "tool_end";
  tool_call_id: string;
  tool_name: string;
  status: "success" | "error" | "cancelled";
  result?: string | Record<string, any>;
  error?: string;
  timestamp: string;
}

// Agent Output Packets
export interface OutputStartPacket {
  type: "output_start";
  timestamp: string;
}

export interface OutputDeltaPacket {
  type: "output_delta";
  content: string;
  timestamp: string;
}

export interface OutputEndPacket {
  type: "output_end";
  timestamp: string;
}

// Plan Packets
export interface PlanEntry {
  id: string;
  description: string;
  status: "pending" | "in_progress" | "completed" | "cancelled";
  priority?: number;
}

export interface PlanPacket {
  type: "plan";
  plan?: string;
  entries?: PlanEntry[];
  timestamp: string;
}

// Mode Update Packets
export interface ModeUpdatePacket {
  type: "mode_update";
  mode: string;
  description?: string;
  timestamp: string;
}

// Completion Packets
export interface DonePacket {
  type: "done";
  summary: string;
  stop_reason?:
    | "end_turn"
    | "max_tokens"
    | "max_turn_requests"
    | "refusal"
    | "cancelled";
  usage?: Record<string, any>;
  timestamp: string;
}

// Error Packets
export interface ErrorPacket {
  type: "error";
  message: string;
  code?: number;
  details?: Record<string, any>;
  timestamp: string;
}

// File Write Packets
export interface FileWritePacket {
  type: "file_write";
  path: string;
  size_bytes?: number;
  operation: "create" | "update" | "delete";
  timestamp: string;
}

// Artifact Packets
export type BackendArtifactType =
  | "web_app"
  | "markdown"
  | "image"
  | "csv"
  | "excel"
  | "pptx"
  | "docx"
  | "pdf"
  | "code"
  | "other";

export interface ArtifactCreatedPacket {
  type: "artifact_created";
  artifact: {
    id: string;
    type: BackendArtifactType;
    name: string;
    path: string;
    preview_url?: string;
    download_url?: string;
    mime_type?: string;
    size_bytes?: number;
  };
  timestamp: string;
}

// Permission Packets (for future use)
export interface PermissionRequestPacket {
  type: "permission_request";
  request_id: string;
  operation: string;
  description: string;
  auto_approve: boolean;
  timestamp: string;
}

export interface PermissionResponsePacket {
  type: "permission_response";
  request_id: string;
  approved: boolean;
  reason?: string;
  timestamp: string;
}

// Union type for all packets
export type StreamPacket =
  | StepStartPacket
  | StepDeltaPacket
  | StepEndPacket
  | ToolStartPacket
  | ToolProgressPacket
  | ToolEndPacket
  | OutputStartPacket
  | OutputDeltaPacket
  | OutputEndPacket
  | PlanPacket
  | ModeUpdatePacket
  | DonePacket
  | ErrorPacket
  | FileWritePacket
  | ArtifactCreatedPacket
  | PermissionRequestPacket
  | PermissionResponsePacket
  | { type: string; timestamp?: string }; // catch-all for unknown packet types
