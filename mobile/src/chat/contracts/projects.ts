// These project types are mobile-only; they are not shared with the web codebase.
import type { ChatFileType } from "@/chat/interfaces";
import type { ChatSessionSummary } from "@/api/chat/sessions";

// UPLOADING is set locally before the file has a server record; every other value comes from the
// backend. Payload casing isn't guaranteed, so status checks below compare against an uppercased value.
export enum UserFileStatus {
  UPLOADING = "UPLOADING",
  PROCESSING = "PROCESSING",
  INDEXING = "INDEXING",
  COMPLETED = "COMPLETED",
  SKIPPED = "SKIPPED",
  FAILED = "FAILED",
  CANCELED = "CANCELED",
  DELETING = "DELETING",
}

export interface ProjectFile {
  id: string;
  name: string;
  file_id: string;
  status: UserFileStatus;
  chat_file_type: ChatFileType;
  token_count: number | null;
  created_at: string;
  // This is a client-generated marker set before the file has a server id. The upload endpoint
  // echoes it back, and reconcile() uses that echo to match the returned file to its local record.
  temp_id?: string | null;
}

export interface RejectedFile {
  file_name: string;
  reason: string;
}

// An upload can partially succeed: some files land in rejected_files while others land in
// user_files, in the same response.
export interface CategorizedFiles {
  user_files: ProjectFile[];
  rejected_files: RejectedFile[];
}

export function isProcessingStatus(status: UserFileStatus | string): boolean {
  const upper = String(status).toUpperCase();
  return (
    upper === UserFileStatus.UPLOADING ||
    upper === UserFileStatus.PROCESSING ||
    upper === UserFileStatus.INDEXING
  );
}

// Narrower than isProcessingStatus: true only while the file is still transferring, not once the
// server has started processing or indexing it.
export function isUploadingStatus(status: UserFileStatus | string): boolean {
  return String(status).toUpperCase() === UserFileStatus.UPLOADING;
}

// Excludes UPLOADING because it's set locally, before the file has a real id to poll for.
export function isServerProcessingStatus(
  status: UserFileStatus | string,
): boolean {
  const upper = String(status).toUpperCase();
  return (
    upper === UserFileStatus.PROCESSING || upper === UserFileStatus.INDEXING
  );
}

// The list/detail endpoints embed `chat_sessions` inline, so a project's chats never need a
// separate fetch.
export interface Project {
  id: number;
  name: string;
  description: string | null;
  created_at: string;
  instructions: string | null;
  chat_sessions: ChatSessionSummary[];
}

// Returned by `GET /user/projects/{id}/details`. `persona_id_to_is_featured` decides whether a
// chat row renders that agent's avatar or a plain bubble.
export interface ProjectDetails {
  project: Project;
  files: ProjectFile[] | null;
  persona_id_to_is_featured: Record<number, boolean> | null;
}
