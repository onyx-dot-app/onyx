import { create } from "zustand";
import type { UploadFilesOptions } from "@/lib/projects/svc";
import { type ProjectFile, UserFileStatus } from "@/lib/projects/types";

interface UploadProgressStore {
  progressByTempId: Readonly<Record<string, number>>;
  /** Counts held uploads that settled, so a holder can update its files. */
  heldSettled: number;
}

export const useUploadProgressStore = create<UploadProgressStore>(() => ({
  progressByTempId: {},
  heldSettled: 0,
}));

/** One request uploads a batch of files, so its files share one controller. */
interface UploadBatch {
  controller: AbortController;
  pending: Set<string>;
  /** The server has the whole body, so it stores the files even if aborted. */
  sent: boolean;
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
  /** Whether the user cancelled this file while its batch kept uploading. */
  isCancelled: (tempId: string) => boolean;
  finish: (uploaded?: ProjectFile[]) => void;
} {
  const batch: UploadBatch = {
    controller: new AbortController(),
    pending: new Set(tempIds),
    sent: false,
  };
  tempIds.forEach((id) => batchByTempId.set(id, batch));
  return {
    options: {
      signal: batch.controller.signal,
      onProgress: (progress) => {
        if (progress >= 1) batch.sent = true;
        useUploadProgressStore.setState((state) => {
          const progressByTempId = { ...state.progressByTempId };
          batch.pending.forEach((id) => {
            progressByTempId[id] = progress;
          });
          return { progressByTempId };
        });
      },
    },
    isCancelled: (tempId) => !batch.pending.has(tempId),
    finish: (uploaded = []) => {
      const uploadedByTempId = new Map(uploaded.map((f) => [f.temp_id, f]));
      let settledHeld = false;
      tempIds.forEach((id) => {
        if (batchByTempId.get(id) === batch) batchByTempId.delete(id);
        if (heldUploads.has(id)) {
          heldUploads.set(id, uploadedByTempId.get(id) ?? null);
          settledHeld = true;
        }
      });
      clearProgress(tempIds);
      if (settledHeld)
        useUploadProgressStore.setState((state) => ({
          heldSettled: state.heldSettled + 1,
        }));
    },
  };
}

/**
 * Stops waiting for the file's upload. The request is aborted when no other
 * file in its batch still waits for it and its body is not fully sent;
 * otherwise the upload finishes and the cancelled files are deleted.
 */
export function cancelUpload(tempId: string): void {
  const batch = batchByTempId.get(tempId);
  if (!batch) return;
  batchByTempId.delete(tempId);
  batch.pending.delete(tempId);
  clearProgress([tempId]);
  if (batch.pending.size === 0 && !batch.sent) batch.controller.abort();
}

/** Keeps the results of these files' running uploads for `releaseUploads`. */
export function holdUploads(files: ProjectFile[]): void {
  files.forEach((file) => {
    if (file.temp_id && batchByTempId.has(file.temp_id))
      heldUploads.set(file.temp_id, undefined);
  });
}

/** Forgets held files that no one will release, such as an abandoned edit. */
export function dropHeldUploads(files: ProjectFile[]): void {
  files.forEach((file) => {
    if (file.temp_id) heldUploads.delete(file.temp_id);
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
    if (result === undefined)
      return batchByTempId.has(file.temp_id) ? [file] : [];
    heldUploads.delete(file.temp_id);
    return result === null ? [] : [{ ...file, ...result }];
  });
}
