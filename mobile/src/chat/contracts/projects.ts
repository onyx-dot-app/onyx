// Mobile-native project types (read model, PR 6) — not shared with web.
import type { ChatFileType } from "@/chat/interfaces";
import type { ChatSessionSummary } from "@/api/chat/sessions";

// UPLOADING is client-only (PR 7); the rest come from the backend. Matched
// case-insensitively — payload casing isn't guaranteed.
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
  // client marker for an optimistic upload; the upload endpoint echoes it, but
  // the client reconciles via refetch, so the echo isn't read back.
  temp_id?: string | null;
}

// reason is a human string shown to the user
export interface RejectedFile {
  file_name: string;
  reason: string;
}

// Partial success is normal: rejected files land in rejected_files, not user_files.
export interface CategorizedFiles {
  user_files: ProjectFile[];
  rejected_files: RejectedFile[];
}

// Case-insensitive: payload casing isn't guaranteed.
export function isProcessingStatus(status: UserFileStatus | string): boolean {
  const upper = String(status).toUpperCase();
  return (
    upper === UserFileStatus.UPLOADING ||
    upper === UserFileStatus.PROCESSING ||
    upper === UserFileStatus.INDEXING
  );
}

// `chat_sessions` is embedded by the list/detail endpoints — a project's chats
// need no separate fetch.
export interface Project {
  id: number;
  name: string;
  description: string | null;
  created_at: string;
  instructions: string | null;
  chat_sessions: ChatSessionSummary[];
}

// `GET /user/projects/{id}/details` — project + files inline; featured map drives
// a chat row's avatar-vs-bubble choice.
export interface ProjectDetails {
  project: Project;
  files: ProjectFile[] | null;
  persona_id_to_is_featured: Record<number, boolean> | null;
}
