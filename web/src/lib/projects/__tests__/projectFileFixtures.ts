import { ChatFileType } from "@/app/app/interfaces";
import { type ProjectFile, UserFileStatus } from "@/lib/projects/types";

/** A completed text attachment; override only what the test cares about. */
export function projectFile(overrides: Partial<ProjectFile> = {}): ProjectFile {
  return {
    id: "file",
    name: "file.txt",
    project_id: null,
    user_id: null,
    file_id: "file-file-id",
    created_at: "2026-01-01T00:00:00Z",
    status: UserFileStatus.COMPLETED,
    file_type: "text/plain",
    last_accessed_at: "2026-01-01T00:00:00Z",
    chat_file_type: ChatFileType.PLAIN_TEXT,
    token_count: null,
    chunk_count: null,
    content_ready: true,
    ...overrides,
  };
}
