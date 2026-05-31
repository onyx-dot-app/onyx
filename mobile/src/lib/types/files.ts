// User-file types — mirror of web `web/src/app/app/projects/projectsService.ts`
// (the subset the mobile chat composer needs) and the backend
// `CategorizedFilesSnapshot` / `UserFileSnapshot` shapes returned by
// `POST /user/projects/file/upload` and `POST /user/projects/file/statuses`.

import type { ChatFileType } from "./chat";

/**
 * Lifecycle of an uploaded user file. `UPLOADING` is a FE-only optimistic state
 * (web parity); the rest come from the backend `UserFileStatus`.
 */
export enum UserFileStatus {
  UPLOADING = "UPLOADING", // UI only — optimistic, before the upload POST resolves
  PROCESSING = "PROCESSING",
  COMPLETED = "COMPLETED",
  SKIPPED = "SKIPPED",
  FAILED = "FAILED",
  CANCELED = "CANCELED",
  DELETING = "DELETING",
}

/**
 * A user file as returned by the upload / statuses / recent-files endpoints
 * (backend `UserFileSnapshot`). `file_id` is the reference sent in chat
 * `file_descriptors`; `id` is the durable DB id (→ `user_file_id`).
 */
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

/** A file the backend refused (oversized, unsupported, …). */
export interface RejectedFile {
  file_name: string;
  reason: string;
}

/** Response of `POST /user/projects/file/upload`. */
export interface CategorizedFiles {
  user_files: ProjectFile[];
  rejected_files: RejectedFile[];
}
