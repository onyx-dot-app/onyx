import { useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useShallow } from "zustand/react/shallow";

import { apiFetch } from "@/api/client";
import { QUERY_KEYS } from "@/api/query-keys";
import { useSession } from "@/state/session";
import type { ProjectFile } from "@/chat/contracts/projects";
import {
  EMPTY_FILES,
  useFilesByIds,
  useLiveFiles,
  useUserFileStore,
} from "@/state/userFileStore";

// Recent library files (the user's full file library). Fetched only while a picker is open; this
// lens holds the list and seeds the userFileStore with the records, then renders each file's live
// store record so its status stays fresh via the single UploadReconciler poll. In-flight uploads
// (from any surface) are shown immediately too, mirroring web's optimistic recent list. The
// engine/lens sibling of useProjectFiles — a hook, hence it lives here and not with the api wrappers.
export function useRecentFiles(enabled: boolean) {
  const serverUrl = useSession((state) => state.serverUrl);
  const query = useQuery({
    queryKey: QUERY_KEYS.userRecentFiles(serverUrl),
    enabled: enabled && serverUrl !== null,
    queryFn: async ({ signal }) => {
      try {
        return await apiFetch<ProjectFile[]>("/user/files/recent", { signal });
      } catch (error) {
        // Log real failures (an empty picker is otherwise silent); skip aborts (picker closed /
        // server switch). Rethrow so TanStack Query keeps its error/retry state.
        if (!signal.aborted) console.warn("recent files fetch failed", error);
        throw error;
      }
    },
  });

  const upsert = useUserFileStore((state) => state.upsert);
  useEffect(() => {
    if (query.data) upsert(query.data);
  }, [query.data, upsert]);

  const fetched = useLiveFiles(query.data ?? EMPTY_FILES);

  const optimisticIds = useUserFileStore(
    useShallow((state) =>
      Object.values(state.tasksById).map((t) => t.clientId),
    ),
  );
  const optimistic = useFilesByIds(optimisticIds);

  const data = useMemo(() => {
    const fetchedIds = new Set(fetched.map((file) => file.id));
    const optimisticOnly = optimistic.filter(
      (file) => !fetchedIds.has(file.id),
    );
    return [...optimisticOnly, ...fetched];
  }, [optimistic, fetched]);

  return { ...query, data };
}
