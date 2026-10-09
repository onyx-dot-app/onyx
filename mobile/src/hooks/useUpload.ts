import { useCallback, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { QUERY_KEYS } from "@/api/query-keys";
import { getErrorMessage } from "@/api/errors";
import { getUploadTransport } from "@/api/files/transport";
import { generateTempId, type NormalizedAsset } from "@/api/files/upload";
import { useWorkspaceSettings } from "@/api/settings";
import { toast } from "@/hooks/useToast";
import { useSession } from "@/state/session";
import type { ProjectFile } from "@/chat/contracts/projects";
import { buildOptimisticFile, partitionBySize } from "@/lib/files";
import {
  setUploadCancel,
  useUserFileStore,
  type FileRecord,
  type UploadTarget,
} from "@/state/userFileStore";

export interface UseUpload {
  // Returns the optimistic clientIds right away; the transfer itself runs in the background and
  // reports errors through a toast, not through the return value or a thrown error.
  upload: (assets: NormalizedAsset[], target: UploadTarget) => string[];
  // Picks files and uploads them. This is the only place a picker error gets turned into a toast.
  pickAndUpload: (
    pick: () => Promise<NormalizedAsset[]>,
    target: UploadTarget,
  ) => Promise<string[]>;
  registerExisting: (file: ProjectFile) => string;
  // `target` must be the surface that started the upload — the store refuses to cancel or delete
  // an upload for any other target.
  remove: (clientId: string, target: UploadTarget) => void;
}

export function useUpload(): UseUpload {
  const queryClient = useQueryClient();
  const serverUrl = useSession((state) => state.serverUrl);
  const { settings } = useWorkspaceSettings();
  const maxUploadMb = settings.user_file_max_upload_size_mb;

  const upload = useCallback(
    (assets: NormalizedAsset[], target: UploadTarget): string[] => {
      const store = useUserFileStore.getState();
      const { valid, rejections } = partitionBySize(assets, maxUploadMb);
      if (rejections.length > 0) toast.warning(rejections.join("\n"));
      if (valid.length === 0) return [];

      const items = valid.map((asset) => ({ asset, tempId: generateTempId() }));
      const records: FileRecord[] = items.map(({ asset, tempId }) => ({
        clientId: tempId,
        file: buildOptimisticFile(asset, tempId),
      }));
      const epoch = store.beginUpload(target, records);

      const projectId = target.kind === "project" ? target.projectId : null;

      void (async () => {
        const uploadRejections: string[] = [];
        await Promise.all(
          items.map(async ({ asset, tempId }) => {
            try {
              const handle = getUploadTransport().upload(
                asset,
                { projectId, tempId },
                (ratio) => store.setProgress(tempId, epoch, ratio),
              );
              setUploadCancel(tempId, handle.cancel);
              const result = await handle.result;
              if (result.user_files.length > 0) {
                // The backend only echoes back our temp_id when its `size|name` file key matches
                // ours, and mobile picks routinely don't match, so it often comes back null. Each
                // upload call sends exactly one file, so the returned file is always this record's
                // — stamp our own tempId onto it whenever the server didn't echo one.
                store.reconcile(
                  result.user_files.map((file) => ({
                    ...file,
                    temp_id: file.temp_id ?? tempId,
                  })),
                  epoch,
                );
              }
              if (result.rejected_files.length > 0) {
                store.removeFile(tempId, target);
                result.rejected_files.forEach((file) =>
                  uploadRejections.push(`${file.file_name}: ${file.reason}`),
                );
              }
            } catch {
              // If the task is already gone, the user removed this attachment themselves, which
              // aborts the transfer and rejects here. That's an intentional cancel, not a failure,
              // so it shouldn't show an error toast.
              if (useUserFileStore.getState().tasksById[tempId] == null) return;
              store.removeFile(tempId, target);
              uploadRejections.push(`${asset.name} could not be uploaded`);
            }
          }),
        );

        // The committed file list renders from the store once this refetch hydrates it; the
        // optimistic record isn't cleared, it just gets deduped against the committed list. Every
        // upload — draft or project — also lands in the user's library, so the recent-files picker
        // needs the same refresh.
        try {
          const invalidations = [
            queryClient.invalidateQueries({
              queryKey: QUERY_KEYS.userRecentFiles(serverUrl),
            }),
          ];
          if (target.kind === "project") {
            invalidations.push(
              queryClient.invalidateQueries({
                queryKey: QUERY_KEYS.userProject(serverUrl, target.projectId),
              }),
            );
          }
          await Promise.all(invalidations);
        } catch {
          uploadRejections.push("Uploaded, but the file list didn't refresh.");
        }

        if (uploadRejections.length > 0)
          toast.error(uploadRejections.join("\n"));
      })();

      return records.map((record) => record.clientId);
    },
    [maxUploadMb, serverUrl, queryClient],
  );

  const pickAndUpload = useCallback(
    async (
      pick: () => Promise<NormalizedAsset[]>,
      target: UploadTarget,
    ): Promise<string[]> => {
      try {
        return upload(await pick(), target);
      } catch (error) {
        toast.error(getErrorMessage(error, "Couldn't open the file picker."));
        return [];
      }
    },
    [upload],
  );

  const registerExisting = useCallback(
    (file: ProjectFile) => useUserFileStore.getState().registerExisting(file),
    [],
  );

  const remove = useCallback(
    (clientId: string, target: UploadTarget) =>
      useUserFileStore.getState().removeFile(clientId, target),
    [],
  );

  return useMemo(
    () => ({ upload, pickAndUpload, registerExisting, remove }),
    [upload, pickAndUpload, registerExisting, remove],
  );
}
