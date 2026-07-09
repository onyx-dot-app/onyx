import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getErrorMessage } from "@/api/errors";
import { getUserFileStatuses } from "@/api/files/files";
import { pickDocuments, pickImages } from "@/api/files/pickers";
import {
  generateTempId,
  uploadUserFile,
  type NormalizedAsset,
} from "@/api/files/upload";
import { useWorkspaceSettings } from "@/api/settings";
import { projectFilesToFileDescriptors } from "@/chat/fileDescriptors";
import {
  isProcessingStatus,
  UserFileStatus,
  type ProjectFile,
} from "@/chat/contracts/projects";
import { type FileDescriptor } from "@/chat/interfaces";
import {
  buildOptimisticFile,
  isFailedFile,
  partitionBySize,
} from "@/lib/files";

const POLL_INTERVAL_MS = 3000;

// PROCESSING/INDEXING are server-side and pollable; UPLOADING is client-only
// (its `id` is a temp id the status endpoint wouldn't know).
function isServerProcessing(file: ProjectFile): boolean {
  const upper = String(file.status).toUpperCase();
  return (
    upper === UserFileStatus.PROCESSING || upper === UserFileStatus.INDEXING
  );
}

export interface UseMessageAttachments {
  files: ProjectFile[];
  progressById: Map<string, number>;
  errors: string[];
  descriptors: FileDescriptor[];
  // any file still uploading/indexing OR failed → block send (removal unblocks)
  hasBlockingFiles: boolean;
  addDocuments: () => Promise<void>;
  addImages: () => Promise<void>;
  addRecent: (file: ProjectFile) => void;
  removeFile: (id: string) => void;
  dismissErrors: () => void;
  clear: () => void;
}

// Per-message draft attachments: pick → upload (unlinked user file) → poll status →
// build descriptors → clear on send. Web-faithful equivalent of `currentMessageFiles`.
// State is LOCAL (never a store) and reset whenever `resetKey` changes, because the
// composer lives in one persistent ChatSurface that never remounts across conversations
// — so attachments must not leak across `[sessionId, projectId]`. All async writes are
// guarded by a captured `resetKey` + matched by temp id, so a late upload/poll for a
// conversation the user already left is dropped, never resurrected.
export function useMessageAttachments(resetKey: string): UseMessageAttachments {
  const { settings } = useWorkspaceSettings();
  const maxUploadMb = settings.user_file_max_upload_size_mb;

  const [files, setFiles] = useState<ProjectFile[]>([]);
  const [progressById, setProgressById] = useState<Map<string, number>>(
    () => new Map(),
  );
  const [errors, setErrors] = useState<string[]>([]);

  // The current conversation key, read non-reactively from async callbacks.
  const keyRef = useRef(resetKey);
  keyRef.current = resetKey;

  const clear = useCallback(() => {
    setFiles([]);
    setProgressById(new Map());
    setErrors([]);
  }, []);

  // Conversation changed → drop the previous conversation's draft. Runs on mount too
  // (a no-op on empty state).
  useEffect(() => {
    clear();
  }, [resetKey, clear]);

  const runUpload = useCallback(
    async (assets: NormalizedAsset[]) => {
      if (assets.length === 0) return;
      const myKey = keyRef.current;
      const isCurrent = () => keyRef.current === myKey;

      // Size pre-check mirrors web's client-side guard.
      const { valid, rejections: sizeRejections } = partitionBySize(
        assets,
        maxUploadMb,
      );
      if (sizeRejections.length > 0 && isCurrent()) {
        setErrors((prev) => [...prev, ...sizeRejections]);
      }
      if (valid.length === 0) return;

      const items = valid.map((asset) => ({ asset, tempId: generateTempId() }));
      if (!isCurrent()) return;
      setFiles((prev) => [
        ...prev,
        ...items.map(({ asset, tempId }) => buildOptimisticFile(asset, tempId)),
      ]);

      const uploadErrors: string[] = [];
      await Promise.all(
        items.map(async ({ asset, tempId }) => {
          try {
            const result = await uploadUserFile(
              asset,
              null,
              tempId,
              (ratio) => {
                if (isCurrent()) {
                  setProgressById((prev) => new Map(prev).set(tempId, ratio));
                }
              },
            );
            const created = result.user_files[0];
            result.rejected_files.forEach((file) =>
              uploadErrors.push(`${file.file_name}: ${file.reason}`),
            );
            if (!isCurrent()) return;
            // Reconcile the optimistic entry (matched by temp id) with the server
            // file; if it was rejected, drop it. A missing temp id means the user
            // switched conversations — skip.
            setFiles((prev) => {
              const index = prev.findIndex((file) => file.temp_id === tempId);
              if (index < 0) return prev;
              const next = [...prev];
              if (created) next[index] = created;
              else next.splice(index, 1);
              return next;
            });
          } catch (error) {
            console.warn(`attachment upload failed for ${asset.name}`, error);
            uploadErrors.push(`${asset.name} could not be uploaded`);
            if (isCurrent()) {
              setFiles((prev) =>
                prev.filter((file) => file.temp_id !== tempId),
              );
            }
          } finally {
            if (isCurrent()) {
              setProgressById((prev) => {
                const next = new Map(prev);
                next.delete(tempId);
                return next;
              });
            }
          }
        }),
      );

      if (uploadErrors.length > 0 && isCurrent()) {
        setErrors((prev) => [...prev, ...uploadErrors]);
      }
    },
    [maxUploadMb],
  );

  // Surface a picker permission denial / native error inline (the picker throws
  // rather than returning empty on denial).
  const runPicked = useCallback(
    async (pick: () => Promise<NormalizedAsset[]>) => {
      // Capture the draft key before the picker opens; if the user switches
      // conversations while it's open, drop the picked files and any error so they
      // can't land in the new chat.
      const myKey = keyRef.current;
      // A fresh pick starts from a clean error state (mirrors useProjectFiles),
      // so stale/duplicate rejections don't stack across attempts.
      setErrors([]);
      try {
        const assets = await pick();
        if (keyRef.current !== myKey) return;
        await runUpload(assets);
      } catch (error) {
        if (keyRef.current !== myKey) return;
        console.warn("file picker failed", error);
        setErrors((prev) => [
          ...prev,
          getErrorMessage(error, "Couldn't open the file picker."),
        ]);
      }
    },
    [runUpload],
  );

  const addDocuments = useCallback(() => runPicked(pickDocuments), [runPicked]);
  const addImages = useCallback(() => runPicked(pickImages), [runPicked]);

  // Attach an already-indexed recent file (web's onPickRecent — purely client-side,
  // no server link for a per-message attachment).
  const addRecent = useCallback((file: ProjectFile) => {
    setFiles((prev) =>
      prev.some((existing) => existing.id === file.id) ? prev : [...prev, file],
    );
  }, []);

  const removeFile = useCallback((id: string) => {
    setFiles((prev) => prev.filter((file) => file.id !== id));
    setProgressById((prev) => {
      if (!prev.has(id)) return prev;
      const next = new Map(prev);
      next.delete(id);
      return next;
    });
  }, []);

  const dismissErrors = useCallback(() => setErrors([]), []);

  // Poll server-side processing files, patching local state. `trackedKey` is a stable
  // string so the effect doesn't reset the timer every render.
  const trackedIds = useMemo(
    () =>
      files
        .filter(isServerProcessing)
        .map((file) => file.id)
        .sort(),
    [files],
  );
  const trackedKey = trackedIds.join(",");

  useEffect(() => {
    if (trackedIds.length === 0) return;
    const myKey = keyRef.current;
    let cancelled = false;

    const interval = setInterval(() => {
      void (async () => {
        try {
          const statuses = await getUserFileStatuses(trackedIds);
          if (cancelled || keyRef.current !== myKey) return;
          const byId = new Map(statuses.map((file) => [file.id, file]));
          setFiles((prev) => prev.map((file) => byId.get(file.id) ?? file));
        } catch (error) {
          // transient poll failure — retry next tick
          console.warn("attachment status poll failed", error);
        }
      })();
    }, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
    // trackedIds is re-read via trackedKey (stable when its contents are unchanged)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trackedKey]);

  const descriptors = useMemo(
    () => projectFilesToFileDescriptors(files),
    [files],
  );
  const hasBlockingFiles = useMemo(
    () =>
      files.some(
        (file) => isProcessingStatus(file.status) || isFailedFile(file),
      ),
    [files],
  );

  return {
    files,
    progressById,
    errors,
    descriptors,
    hasBlockingFiles,
    addDocuments,
    addImages,
    addRecent,
    removeFile,
    dismissErrors,
    clear,
  };
}
