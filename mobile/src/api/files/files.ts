import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/api/client";
import { QUERY_KEYS } from "@/api/query-keys";
import { useSession } from "@/state/session";
import type { ProjectFile } from "@/chat/contracts/projects";

// Recent library files (across projects); fetched only while the picker is open.
export function useRecentFiles(enabled: boolean) {
  const serverUrl = useSession((state) => state.serverUrl);
  return useQuery({
    queryKey: QUERY_KEYS.userRecentFiles(serverUrl),
    enabled: enabled && serverUrl !== null,
    queryFn: ({ signal }) =>
      apiFetch<ProjectFile[]>("/user/files/recent", { signal }),
  });
}

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

// Unlinks (204); the file stays in the user's library.
export function unlinkFileFromProject(
  projectId: number,
  fileId: string,
): Promise<void> {
  return apiFetch<void>(
    `/user/projects/${projectId}/files/${encodeURIComponent(fileId)}`,
    { method: "DELETE" },
  );
}
