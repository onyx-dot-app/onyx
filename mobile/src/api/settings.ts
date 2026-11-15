import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/api/client";
import { QUERY_KEYS } from "@/api/query-keys";
import { useSession } from "@/state/session";

export interface WorkspaceSettings {
  disable_default_assistant: boolean;
  // null = no cap
  user_file_max_upload_size_mb: number | null;
  deep_research_enabled: boolean;
  // false when the deployment sets DISABLE_VECTOR_DB — nothing indexed, so no sources to pick from.
  vector_db_enabled: boolean;
}

interface WorkspaceSettingsResponse {
  disable_default_assistant?: boolean | null;
  user_file_max_upload_size_mb?: number | null;
  deep_research_enabled?: boolean | null;
  vector_db_enabled?: boolean | null;
}

export function useWorkspaceSettings() {
  const serverUrl = useSession((state) => state.serverUrl);
  const query = useQuery({
    queryKey: QUERY_KEYS.workspaceSettings(serverUrl),
    // No serverUrl → `getBaseUrl()` throws, so stay idle until connected.
    enabled: serverUrl !== null,
    queryFn: ({ signal }) =>
      apiFetch<WorkspaceSettingsResponse>("/settings", { signal }),
  });

  const settings: WorkspaceSettings = {
    disable_default_assistant: query.data?.disable_default_assistant ?? false,
    user_file_max_upload_size_mb:
      query.data?.user_file_max_upload_size_mb ?? null,
    deep_research_enabled: query.data?.deep_research_enabled ?? true,
    vector_db_enabled: query.data?.vector_db_enabled ?? true,
  };

  return { ...query, settings };
}
