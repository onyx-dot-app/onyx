// =============================================================================
// Sharing Types
// =============================================================================

export type SharingScope = "private" | "public_org";

export type SessionOrigin = "INTERACTIVE" | "SCHEDULED" | "SLACK";

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
  attachments?: BuildMessageAttachment[];
  /** Structured sandbox event data (tool calls, thinking, plans) */
  message_metadata?: Record<string, any> | null;
}

export interface BuildMessageAttachment {
  name: string;
  path: string;
  mimeType: string;
}

export type SessionStatus =
  | "idle"
  | "creating"
  | "running"
  | "active"
  | "failed";

export interface SessionHistoryItem {
  id: string;
  title: string;
  createdAt: Date;
}

// =============================================================================
// API Response Types
// =============================================================================

type ApiSandboxStatus =
  | "provisioning"
  | "running"
  | "sleeping"
  | "terminated"
  | "failed";

interface ApiSandboxResponse {
  id: string;
  status: ApiSandboxStatus;
  container_id: string | null;
  created_at: string;
  last_heartbeat: string | null;
}

export interface ApiSandboxStatusResponse {
  status: ApiSandboxStatus | null;
}

export interface ApiSessionResponse {
  id: string;
  user_id: string | null;
  name: string | null;
  status: "initializing" | "active" | "idle" | "failed";
  created_at: string;
  last_activity_at: string;
  nextjs_port: number | null;
  sandbox: ApiSandboxResponse | null;
  artifacts: ApiArtifactResponse[];
  sharing_scope: SharingScope;
  origin: SessionOrigin;
  agent_provider: string | null;
  agent_model: string | null;
  skills_stale: boolean;
}

export interface ApiSessionSkillsState {
  skills_stale: boolean;
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

type InteractiveTurnStatus =
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
  has_webapp: boolean | null;
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
// Client Runtime Types
// =============================================================================

export type SandboxRuntimeStatus = ApiSandboxStatus | "restoring";

export interface SandboxRuntimeState extends Omit<
  ApiSandboxResponse,
  "status"
> {
  status: SandboxRuntimeStatus;
}

// =============================================================================
// SSE Packet Types
// =============================================================================

// Artifact Packets
type BackendArtifactType =
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

interface ArtifactCreatedPacket {
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
