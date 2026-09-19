import { ChatFileType, ChatSession } from "@/app/app/interfaces";

export interface Project {
  id: number;
  name: string;
  description: string | null;
  created_at: string;
  user_id: string;
  instructions: string | null;
  chat_sessions: ChatSession[];
}

/**
 * One project that survived a search over project and chat names.
 *
 * A chat hit narrows `chatSessions` to the hits and sets `chatMatched`, so the
 * row can open itself — a match the user cannot see is no match at all. A hit on
 * the project's own name keeps every chat and leaves the row folded.
 */
export interface ProjectSearchMatch {
  project: Project;
  chatSessions: ChatSession[];
  chatMatched: boolean;
}

export interface CategorizedFiles {
  user_files: ProjectFile[];
  rejected_files: RejectedFile[];
}

export interface ProjectFile {
  id: string;
  name: string;
  project_id: number | null;
  user_id: string | null;
  file_id: string;
  created_at: string;
  status: UserFileStatus;
  file_type: string;
  last_accessed_at: string;
  chat_file_type: ChatFileType;
  token_count: number | null;
  chunk_count: number | null;
  temp_id?: string | null;
}

export interface RejectedFile {
  file_name: string;
  reason: string;
}

export interface UserFileDeleteResult {
  has_associations: boolean;
  project_names: string[];
  assistant_names: string[];
}

export enum UserFileStatus {
  UPLOADING = "UPLOADING", //UI only
  PROCESSING = "PROCESSING",
  COMPLETED = "COMPLETED",
  SKIPPED = "SKIPPED",
  FAILED = "FAILED",
  CANCELED = "CANCELED",
  DELETING = "DELETING",
}

export type ProjectDetails = {
  project: Project;
  files?: ProjectFile[];
  persona_id_to_is_featured?: Record<number, boolean>;
};
