import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/api/client";
import { QUERY_KEYS } from "@/api/query-keys";
import { useSession } from "@/state/session";
import type { Project, ProjectDetails } from "@/chat/contracts/projects";

// Unpaginated; each project embeds its `chat_sessions`.
export function useProjects() {
  const serverUrl = useSession((state) => state.serverUrl);

  const query = useQuery({
    queryKey: QUERY_KEYS.userProjects(serverUrl),
    // No serverUrl → `getBaseUrl()` throws, so stay idle until connected.
    enabled: serverUrl !== null,
    queryFn: ({ signal }) => apiFetch<Project[]>("/user/projects", { signal }),
  });

  const projects = useMemo(() => query.data ?? [], [query.data]);
  return { ...query, projects };
}

export function useProjectDetails(projectId: number | null) {
  const serverUrl = useSession((state) => state.serverUrl);

  return useQuery({
    queryKey: QUERY_KEYS.userProject(serverUrl, projectId),
    // reject a NaN id from a malformed route param
    enabled:
      serverUrl !== null && projectId !== null && Number.isFinite(projectId),
    queryFn: ({ signal }) =>
      apiFetch<ProjectDetails>(`/user/projects/${projectId}/details`, {
        signal,
      }),
  });
}
