import { apiFetch } from "@/api/client";
import type { ProjectFile } from "@/chat/contracts/projects";

export function getUserFileStatuses(fileIds: string[]): Promise<ProjectFile[]> {
  return apiFetch<ProjectFile[]>("/user/projects/file/statuses", {
    method: "POST",
    body: { file_ids: fileIds },
  });
}

export function linkFileToProject(
  projectId: number,
  fileId: string,
): Promise<ProjectFile> {
  return apiFetch<ProjectFile>(
    `/user/projects/${projectId}/files/${encodeURIComponent(fileId)}`,
    { method: "POST" },
  );
}

// The file stays in the user's library.
export function unlinkFileFromProject(
  projectId: number,
  fileId: string,
): Promise<void> {
  return apiFetch<void>(
    `/user/projects/${projectId}/files/${encodeURIComponent(fileId)}`,
    { method: "DELETE" },
  );
}
