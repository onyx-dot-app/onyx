import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/api/client";
import { QUERY_KEYS } from "@/api/query-keys";
import { useSession } from "@/state/session";

// disable_default_assistant is a workspace setting; when true the client hides id 0.
export interface WorkspaceSettings {
  disable_default_assistant: boolean;
  // admin hard cap for uploads (MB); null = no cap
  user_file_max_upload_size_mb: number | null;
}

interface WorkspaceSettingsResponse {
  disable_default_assistant?: boolean | null;
  user_file_max_upload_size_mb?: number | null;
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
  };

  return { ...query, settings };
}
