import { create } from "zustand";
import type { UploadFilesOptions } from "@/lib/projects/svc";
import { type ProjectFile, UserFileStatus } from "@/lib/projects/types";

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

/**
 * Uploads of files held outside the composer, such as a draft set aside for
 * an edit. The upload cannot update a file that is not attached, so its result
 * waits here: the uploaded file, or null when the upload failed.
 */
const heldUploads = new Map<string, ProjectFile | null | undefined>();

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
  finish: (uploaded?: ProjectFile[]) => void;
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
    finish: (uploaded = []) => {
      const uploadedByTempId = new Map(uploaded.map((f) => [f.temp_id, f]));
      tempIds.forEach((id) => {
        if (batchByTempId.get(id) === batch) batchByTempId.delete(id);
        if (heldUploads.has(id))
          heldUploads.set(id, uploadedByTempId.get(id) ?? null);
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

/** Keeps the results of these files' running uploads for `releaseUploads`. */
export function holdUploads(files: ProjectFile[]): void {
  files.forEach((file) => {
    if (file.temp_id && batchByTempId.has(file.temp_id))
      heldUploads.set(file.temp_id, undefined);
  });
}

/**
 * Brings held files up to date. A file whose upload finished becomes the
 * uploaded file, and a file whose upload failed is dropped. A file still
 * uploading stays, and its upload updates it once it is attached again.
 */
export function releaseUploads(files: ProjectFile[]): ProjectFile[] {
  return files.flatMap((file) => {
    if (file.status !== UserFileStatus.UPLOADING || !file.temp_id)
      return [file];
    const result = heldUploads.get(file.temp_id);
    heldUploads.delete(file.temp_id);
    if (result === null) return [];
    if (result) return [{ ...file, ...result }];
    return batchByTempId.has(file.temp_id) ? [file] : [];
  });
}
