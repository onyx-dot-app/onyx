import { UserFileStatus, type ProjectFile } from "@/chat/contracts/projects";
import { ChatFileType } from "@/chat/interfaces";

// Shared ProjectFile builder so the file's shape lives in one place across tests.
export function makeProjectFile(
  overrides: Partial<ProjectFile> = {},
): ProjectFile {
  return {
    id: "f1",
    name: "file.pdf",
    file_id: "f1",
    status: UserFileStatus.COMPLETED,
    chat_file_type: ChatFileType.DOCUMENT,
    token_count: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}
