import { create } from "zustand";
import type { UploadFilesOptions } from "@/lib/projects/svc";

interface UploadProgressStore {
  progressByTempId: Readonly<Record<string, number>>;
}

const useUploadProgressStore = create<UploadProgressStore>(() => ({
  progressByTempId: {},
}));

/** One request uploads a batch of files, so its files share one controller. */
interface UploadBatch {
  controller: AbortController;
  pending: Set<string>;
}

const batchByTempId = new Map<string, UploadBatch>();

function clearProgress(tempIds: string[]): void {
  useUploadProgressStore.setState((state) => {
    const progressByTempId = { ...state.progressByTempId };
    tempIds.forEach((id) => delete progressByTempId[id]);
    return { progressByTempId };
  });
}

/** Registers an upload request for the files with these temporary IDs. */
export function trackUpload(tempIds: string[]): {
  options: Required<UploadFilesOptions>;
  finish: () => void;
} {
  const batch: UploadBatch = {
    controller: new AbortController(),
    pending: new Set(tempIds),
  };
  tempIds.forEach((id) => batchByTempId.set(id, batch));
  return {
    options: {
      signal: batch.controller.signal,
      onProgress: (progress) =>
        useUploadProgressStore.setState((state) => {
          const progressByTempId = { ...state.progressByTempId };
          batch.pending.forEach((id) => {
            progressByTempId[id] = progress;
          });
          return { progressByTempId };
        }),
    },
    finish: () => {
      tempIds.forEach((id) => {
        if (batchByTempId.get(id) === batch) batchByTempId.delete(id);
      });
      clearProgress(tempIds);
    },
  };
}

/**
 * Stops waiting for the file's upload. The request is aborted when no other
 * file in its batch still waits for it.
 */
export function cancelUpload(tempId: string): void {
  const batch = batchByTempId.get(tempId);
  if (!batch) return;
  batchByTempId.delete(tempId);
  batch.pending.delete(tempId);
  clearProgress([tempId]);
  if (batch.pending.size === 0) batch.controller.abort();
}

/** The fraction of the file's upload request sent, once known. */
export function useUploadProgress(tempId: string): number | undefined {
  return useUploadProgressStore((state) => state.progressByTempId[tempId]);
}
