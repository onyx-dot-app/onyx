import { useCallback, useContext, useMemo } from "react";

import { pickDocuments, pickImages } from "@/api/files/pickers";
import { type NormalizedAsset } from "@/api/files/upload";
import {
  isProcessingStatus,
  type ProjectFile,
} from "@/chat/contracts/projects";
import { projectFilesToFileDescriptors } from "@/chat/fileDescriptors";
import { type FileDescriptor } from "@/chat/interfaces";
import { ComposerDraftContext } from "@/components/chat/ComposerDraftProvider";
import { useUpload } from "@/hooks/useUpload";
import { isFailedFile } from "@/lib/files";
import {
  EMPTY_IDS,
  useFilesByIds,
  useUserFileStore,
  type UploadTarget,
} from "@/state/userFileStore";

export interface UseComposerDraft {
  text: string;
  setText: (text: string) => void;
  files: ProjectFile[];
  descriptors: FileDescriptor[];
  // any file still uploading/indexing OR failed → block send (removal unblocks)
  hasBlockingFiles: boolean;
  addDocuments: () => Promise<void>;
  addImages: () => Promise<void>;
  addRecent: (file: ProjectFile) => void;
  removeFile: (id: string) => void;
  consume: () => void; // accepted composer send: clear text + attachments
  consumeAttachments: () => void; // accepted starter send: clear attachments, keep text
}

// Sole ComposerDraftContext consumer: text/refs from context, file records from the store,
// uploads via useUpload.
export function useComposerDraft(draftKey: string): UseComposerDraft {
  const ctx = useContext(ComposerDraftContext);
  if (!ctx) {
    throw new Error(
      "useComposerDraft must be used within a ComposerDraftProvider",
    );
  }
  const upload = useUpload();
  const target = useMemo<UploadTarget>(
    () => ({ kind: "draft", draftKey }),
    [draftKey],
  );

  const draft = ctx.drafts[draftKey];
  const text = draft?.text ?? "";
  const clientIds: readonly string[] = draft?.clientIds ?? EMPTY_IDS;
  const files = useFilesByIds(clientIds);

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

  // Depend on the provider's stable methods, not the whole `ctx` (its identity changes every
  // keystroke), so these callbacks stay stable and the FileCard memo holds while typing.
  const {
    setText: ctxSetText,
    addFiles,
    removeFile: ctxRemoveFile,
    consume: ctxConsume,
    consumeAttachments: ctxConsumeAttachments,
  } = ctx;

  const setText = useCallback(
    (value: string) => ctxSetText(draftKey, value),
    [ctxSetText, draftKey],
  );

  const runPicked = useCallback(
    async (pick: () => Promise<NormalizedAsset[]>) => {
      addFiles(draftKey, await upload.pickAndUpload(pick, target));
    },
    [upload, addFiles, draftKey, target],
  );

  const addDocuments = useCallback(() => runPicked(pickDocuments), [runPicked]);
  const addImages = useCallback(() => runPicked(pickImages), [runPicked]);

  const addRecent = useCallback(
    (file: ProjectFile) => addFiles(draftKey, [upload.registerExisting(file)]),
    [upload, addFiles, draftKey],
  );

  const removeFile = useCallback(
    (id: string) => {
      // A chip renders with file.id — a tempId before reconcile, its SERVER id after. The draft is
      // keyed by clientId (tempId), so resolve back through the store's server→client index (a
      // no-op for an already-client id), else a completed upload can't be removed.
      const store = useUserFileStore.getState();
      const clientId = store.serverIdToClientId[id] ?? id;
      ctxRemoveFile(draftKey, clientId);
      // Only hard-delete an upload this draft owns (the store gates on task target); a shared or
      // recent-attached record is just de-referenced above.
      if (store.tasksById[clientId]?.status === "uploading") {
        upload.remove(clientId, target);
      }
    },
    [ctxRemoveFile, draftKey, upload, target],
  );

  const consume = useCallback(() => {
    ctxConsume(draftKey);
  }, [ctxConsume, draftKey]);

  const consumeAttachments = useCallback(() => {
    ctxConsumeAttachments(draftKey);
  }, [ctxConsumeAttachments, draftKey]);

  return {
    text,
    setText,
    files,
    descriptors,
    hasBlockingFiles,
    addDocuments,
    addImages,
    addRecent,
    removeFile,
    consume,
    consumeAttachments,
  };
}
