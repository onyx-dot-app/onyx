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
  // Returns optimistic clientIds synchronously; the transfer runs in the background, errors toast.
  upload: (assets: NormalizedAsset[], target: UploadTarget) => string[];
  // Pick then upload; the one place picker-error-to-toast routing lives.
  pickAndUpload: (
    pick: () => Promise<NormalizedAsset[]>,
    target: UploadTarget,
  ) => Promise<string[]>;
  registerExisting: (file: ProjectFile) => string;
  // `target` is the removing surface; the store only cancels/deletes an upload its target owns.
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
                // Backend echoes temp_id only when its `size|name` file-key matches ours, but
                // mobile picks routinely differ so it comes back null. Upload is 1:1, so the
                // returned file is this record's — stamp our tempId when the server didn't echo one.
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
              // Absent task = user already removed this attachment, aborting the transfer (rejects
              // here). Intentional cancel, not a failure — don't toast.
              if (useUserFileStore.getState().tasksById[tempId] == null) return;
              store.removeFile(tempId, target);
              uploadRejections.push(`${asset.name} could not be uploaded`);
            }
          }),
        );

        // Committed list renders from the store, hydrated by this refetch; the optimistic record
        // stays (deduped against the committed list) — no hand-off.
        if (target.kind === "project") {
          try {
            await queryClient.invalidateQueries({
              queryKey: QUERY_KEYS.userProject(serverUrl, target.projectId),
            });
          } catch {
            uploadRejections.push(
              "Uploaded, but the file list didn't refresh.",
            );
          }
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
