import { useEffect } from "react";
import { AppState } from "react-native";

import { getUserFileStatuses } from "@/api/files/files";
import { isServerProcessingStatus } from "@/chat/contracts/projects";
import { useUserFileStore } from "@/state/userFileStore";

const POLL_INTERVAL_MS = 3000;

// Only server-processing files (real id post-reconcile) are pollable; UPLOADING is client-only.
function serverProcessingIds(): string[] {
  return Object.values(useUserFileStore.getState().filesById)
    .filter((record) => isServerProcessingStatus(record.file.status))
    .map((record) => record.file.id);
}

async function pollOnce(): Promise<void> {
  const ids = serverProcessingIds();
  if (ids.length === 0) return;
  try {
    const statuses = await getUserFileStatuses(ids);
    useUserFileStore.getState().reconcile(statuses);
  } catch {
    // transient — retry next tick / next foreground
  }
}

// Mounted once outside the morphing ChatSurface. The single status poller for the whole app: while
// ANY file in the store is server-processing (draft, project, or recent — they all live in
// filesById now), polls /statuses every 3s and re-polls on app-foreground (so a file that finished
// while backgrounded reconciles on return).
export function UploadReconciler(): null {
  const hasProcessing = useUserFileStore((state) =>
    Object.values(state.filesById).some((record) =>
      isServerProcessingStatus(record.file.status),
    ),
  );

  useEffect(() => {
    if (!hasProcessing) return;
    const interval = setInterval(() => void pollOnce(), POLL_INTERVAL_MS);
    const subscription = AppState.addEventListener("change", (state) => {
      if (state === "active") void pollOnce();
    });
    return () => {
      clearInterval(interval);
      subscription.remove();
    };
  }, [hasProcessing]);

  return null;
}
