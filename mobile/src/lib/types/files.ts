// Mirrors web projectsService.ts (subset the mobile chat composer needs).

import type { ChatFileType } from "./chat";

export enum UserFileStatus {
  UPLOADING = "UPLOADING", // UI only — optimistic, before the upload POST resolves
  PROCESSING = "PROCESSING",
  COMPLETED = "COMPLETED",
  SKIPPED = "SKIPPED",
  FAILED = "FAILED",
  CANCELED = "CANCELED",
  DELETING = "DELETING",
}

// `file_id` is the reference sent in chat file_descriptors; `id` is the durable DB id.
export interface ProjectFile {
  id: string;
  name: string;
  project_id: number | null;
  user_id: string | null;
  file_id: string;
  created_at: string;
  status: UserFileStatus;
  file_type: string | null;
  last_accessed_at: string | null;
  chat_file_type: ChatFileType;
  token_count: number | null;
  chunk_count: number | null;
  temp_id?: string | null;
}

export interface RejectedFile {
  file_name: string;
  reason: string;
}

export interface CategorizedFiles {
  user_files: ProjectFile[];
  rejected_files: RejectedFile[];
}
