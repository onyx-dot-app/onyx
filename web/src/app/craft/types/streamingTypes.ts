// =============================================================================
// Sharing Types
// =============================================================================

export type SharingScope = "private" | "public_org";

export type SessionOrigin = "INTERACTIVE" | "SCHEDULED";

// =============================================================================
// Session Error Constants
// =============================================================================

export const SessionErrorCode = {
  RATE_LIMIT_EXCEEDED: "RATE_LIMIT_EXCEEDED",
} as const;

export type SessionErrorCode =
  (typeof SessionErrorCode)[keyof typeof SessionErrorCode];

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
  type: "user" | "assistant" | "system";
  content: string;
  timestamp: Date;
  turn_index?: number;
  /** Structured sandbox event data (tool calls, thinking, plans) */
  message_metadata?: Record<string, any> | null;
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
  /** Raw input from sandbox (complete command/parameters) */
  raw_input?: Record<string, any> | null;
  /** Raw output from sandbox (complete result) */
  raw_output?: Record<string, any> | null;
  /** Content block from sandbox (description text) */
  content?: any | null;
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
  | "active"
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

export interface ApiSandboxResponse {
  id: string;
  status:
    | "provisioning"
    | "running"
    | "idle"
    | "sleeping"
    | "terminated"
    | "failed"
    | "restoring"; // Frontend-only: set during snapshot restore
  container_id: string | null;
  created_at: string;
  last_heartbeat: string | null;
  nextjs_port: number | null;
}

export interface ApiSandboxStatusResponse {
  status: Exclude<ApiSandboxResponse["status"], "restoring"> | null;
}

export interface ApiSessionResponse {
  id: string;
  user_id: string | null;
  name: string | null;
  status: "active" | "idle" | "archived";
  created_at: string;
  last_activity_at: string;
  sandbox: ApiSandboxResponse | null;
  artifacts: ApiArtifactResponse[];
  sharing_scope: SharingScope;
  origin: SessionOrigin;
  agent_provider: string | null;
  agent_model: string | null;
}

export interface ApiDetailedSessionResponse extends ApiSessionResponse {
  session_loaded_in_sandbox: boolean;
}

export interface ApiMessageResponse {
  id: string;
  session_id: string;
  turn_index: number;
  type: "user" | "assistant";
  content: string;
  message_metadata?: Record<string, any> | null;
  created_at: string;
}

export type InteractiveTurnStatus =
  | "QUEUED"
  | "RUNNING"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELLED";

export interface ApiInteractiveTurnResponse {
  turn_id: string;
  session_id: string;
  status: InteractiveTurnStatus;
  turn_index: number;
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

export interface ApiWebappInfoResponse {
  has_webapp: boolean;
  webapp_url: string | null;
  status: string;
  ready: boolean;
  sharing_scope: SharingScope;
}

export interface FileSystemEntry {
  name: string;
  path: string;
  is_directory: boolean;
  size: number | null;
  mime_type: string | null;
}

export interface DirectoryListing {
  path: string;
  entries: FileSystemEntry[];
}

// =============================================================================
// SSE Packet Types
// =============================================================================

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

// Union type for all packets
export type StreamPacket =
  | ArtifactCreatedPacket
  | { type: string; timestamp?: string }; // catch-all for unknown packet types
