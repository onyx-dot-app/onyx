// Mobile-native project types (read model, PR 6) — not shared with web.
import type { ChatFileType } from "@/chat/interfaces";
import type { ChatSessionSummary } from "@/api/chat/sessions";

// UPLOADING is client-only (PR 7); the rest come from the backend. Matched
// case-insensitively — payload casing isn't guaranteed.
export enum UserFileStatus {
  UPLOADING = "UPLOADING",
  PROCESSING = "PROCESSING",
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
