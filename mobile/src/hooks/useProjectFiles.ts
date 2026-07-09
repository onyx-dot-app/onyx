import { useCallback, useEffect, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { QUERY_KEYS } from "@/api/query-keys";
import {
  getUserFileStatuses,
  linkFileToProject,
  unlinkFileFromProject,
} from "@/api/files/files";
import {
  generateTempId,
  uploadProjectFile,
  type NormalizedAsset,
} from "@/api/files/upload";
import { pickDocuments, pickImages } from "@/api/files/pickers";
import { getErrorMessage } from "@/api/errors";
import { useWorkspaceSettings } from "@/api/settings";
import { ChatFileType } from "@/chat/interfaces";
import {
  isProcessingStatus,
  UserFileStatus,
  type ProjectDetails,
  type ProjectFile,
} from "@/chat/contracts/projects";
import { useProjectUploads, useUploadStore } from "@/state/uploadStore";
import { useSession } from "@/state/session";

const POLL_INTERVAL_MS = 3000;

function optimisticFile(asset: NormalizedAsset, tempId: string): ProjectFile {
  return {
    id: tempId,
    temp_id: tempId,
    name: asset.name,
    file_id: tempId,
    status: UserFileStatus.UPLOADING,
    chat_file_type: asset.mimeType?.startsWith("image/")
      ? ChatFileType.IMAGE
      : ChatFileType.DOCUMENT,
    token_count: null,
    created_at: new Date().toISOString(),
  };
}

export interface UseProjectFiles {
  // Optimistic (uploading) entries first, then committed files.
  files: ProjectFile[];
  progressById: Map<string, number>;
  errors: string[];
  isBusy: boolean;
  addDocuments: () => Promise<void>;
  addImages: () => Promise<void>;
  linkRecent: (fileId: string) => Promise<void>;
  removeFile: (fileId: string) => Promise<void>;
  dismissErrors: () => void;
}

// Project file management: optimistic uploads, link/unlink, size pre-check, and
// indexing-status polling layered over the committed list from useProjectDetails.
export function useProjectFiles(
  projectId: number | null,
  committedFiles: ProjectFile[] | null | undefined,
): UseProjectFiles {
  const queryClient = useQueryClient();
  const serverUrl = useSession((state) => state.serverUrl);
  const { settings } = useWorkspaceSettings();
  const maxUploadMb = settings.user_file_max_upload_size_mb;

  const bucket = useProjectUploads(projectId);
  const begin = useUploadStore((state) => state.begin);
  const setProgress = useUploadStore((state) => state.setProgress);
  const finish = useUploadStore((state) => state.finish);
  const setErrors = useUploadStore((state) => state.setErrors);
  const clearErrors = useUploadStore((state) => state.clearErrors);

  const committed = committedFiles ?? [];

  const { files, progressById } = useMemo(() => {
    const optimistic = bucket ? [...bucket.uploads.values()] : [];
    const progress = new Map<string, number>();
    optimistic.forEach((upload) =>
      progress.set(upload.file.id, upload.progress),
    );
    return {
      files: [...optimistic.map((upload) => upload.file), ...committed],
      progressById: progress,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bucket, committedFiles]);

  const invalidateProject = useCallback(
    () =>
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.userProject(serverUrl, projectId),
      }),
    [queryClient, serverUrl, projectId],
  );

  const runUpload = useCallback(
    async (assets: NormalizedAsset[]) => {
      if (projectId == null || assets.length === 0) return;

      // Size pre-check mirrors web's client-side guard.
      const maxBytes =
        maxUploadMb != null && maxUploadMb > 0
          ? maxUploadMb * 1024 * 1024
          : null;
      const rejected: string[] = [];
      const valid = assets.filter((asset) => {
        if (maxBytes != null && asset.size != null && asset.size > maxBytes) {
          rejected.push(`${asset.name} exceeds the ${maxUploadMb} MB limit`);
          return false;
        }
        return true;
      });

      if (valid.length === 0) {
        setErrors(projectId, rejected);
        return;
      }

      const items = valid.map((asset) => ({ asset, tempId: generateTempId() }));
      begin(
        projectId,
        items.map(({ asset, tempId }) => optimisticFile(asset, tempId)),
      );
      // begin() clears errors; re-surface size rejections now so they show while
      // the uploads are still in flight.
      if (rejected.length > 0) setErrors(projectId, rejected);

      try {
        // One request per file (the native uploader takes a single file).
        await Promise.all(
          items.map(async ({ asset, tempId }) => {
            try {
              const result = await uploadProjectFile(
                asset,
                projectId,
                tempId,
                (ratio) => setProgress(projectId, tempId, ratio),
              );
              result.rejected_files.forEach((file) =>
                rejected.push(`${file.file_name}: ${file.reason}`),
              );
            } catch (error) {
              console.warn(`upload failed for ${asset.name}`, error);
              rejected.push(`${asset.name} could not be uploaded`);
            }
          }),
        );
        // Refetch first (picks up the created files), then drop optimistic entries.
        await invalidateProject();
      } catch (error) {
        // Uploads landed server-side but the refetch failed; focus-refetch recovers.
        console.warn("project refetch after upload failed", error);
        rejected.push("Uploaded, but the file list didn't refresh.");
      } finally {
        items.forEach(({ tempId }) => finish(projectId, tempId));
        if (rejected.length > 0) setErrors(projectId, rejected);
        else clearErrors(projectId);
      }
    },
    [
      projectId,
      maxUploadMb,
      begin,
      setProgress,
      finish,
      setErrors,
      clearErrors,
      invalidateProject,
    ],
  );

  // Wraps the picker so a permission denial / native error surfaces inline
  // instead of vanishing (the sheet is already closed by the time this runs).
  const runPicked = useCallback(
    async (pick: () => Promise<NormalizedAsset[]>) => {
      try {
        await runUpload(await pick());
      } catch (error) {
        console.warn("file picker failed", error);
        if (projectId != null) {
          setErrors(projectId, [
            getErrorMessage(error, "Couldn't open the file picker."),
          ]);
        }
      }
    },
    [runUpload, projectId, setErrors],
  );

  const addDocuments = useCallback(() => runPicked(pickDocuments), [runPicked]);
  const addImages = useCallback(() => runPicked(pickImages), [runPicked]);

  const linkRecent = useCallback(
    async (fileId: string) => {
      if (projectId == null) return;
      try {
        await linkFileToProject(projectId, fileId);
        await invalidateProject();
      } catch (error) {
        console.warn("link file to project failed", error);
        setErrors(projectId, [
          getErrorMessage(error, "Couldn't add that file."),
        ]);
      }
    },
    [projectId, invalidateProject, setErrors],
  );

  const removeFile = useCallback(
    async (fileId: string) => {
      if (projectId == null) return;
      try {
        await unlinkFileFromProject(projectId, fileId);
        await invalidateProject();
      } catch (error) {
        console.warn("unlink file from project failed", error);
        setErrors(projectId, [
          getErrorMessage(error, "Couldn't remove that file."),
        ]);
      }
    },
    [projectId, invalidateProject, setErrors],
  );

  const dismissErrors = useCallback(() => {
    if (projectId != null) clearErrors(projectId);
  }, [projectId, clearErrors]);

  // Poll still-working files, patching the cached details. `trackedKey` is a stable
  // string (change-detection only, never decoded) so the effect doesn't reset the
  // timer each render (committed is a fresh array).
  const trackedIds = useMemo(
    () =>
      committed
        .filter((file) => isProcessingStatus(file.status))
        .map((file) => file.id)
        .sort(),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [committedFiles],
  );
  const trackedKey = trackedIds.join(",");

  useEffect(() => {
    if (projectId == null || trackedIds.length === 0) return;
    let cancelled = false;

    const interval = setInterval(() => {
      void (async () => {
        try {
          const statuses = await getUserFileStatuses(trackedIds);
          if (cancelled) return;
          queryClient.setQueryData<ProjectDetails>(
            QUERY_KEYS.userProject(serverUrl, projectId),
            (old) => {
              if (!old?.files) return old;
              const byId = new Map(statuses.map((file) => [file.id, file]));
              return {
                ...old,
                // /statuses returns the same UserFileSnapshot shape as /details,
                // so take the full polled file (forward-compatible with new fields).
                files: old.files.map((file) => byId.get(file.id) ?? file),
              };
            },
          );
        } catch (error) {
          // transient poll failure — retry next tick
          console.warn("file status poll failed", error);
        }
      })();
    }, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
    // trackedIds is re-read via trackedKey (stable when its contents are unchanged)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, serverUrl, trackedKey, queryClient]);

  return {
    files,
    progressById,
    errors: bucket?.errors ?? [],
    isBusy: (bucket?.uploads.size ?? 0) > 0,
    addDocuments,
    addImages,
    linkRecent,
    removeFile,
    dismissErrors,
  };
}
