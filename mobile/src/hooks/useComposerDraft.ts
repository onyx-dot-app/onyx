import { useCallback, useContext, useMemo } from "react";

import { pickDocuments, pickImages } from "@/api/files/pickers";
import { type NormalizedAsset } from "@/api/files/upload";
import { isUploadingStatus, type ProjectFile } from "@/chat/contracts/projects";
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
  // True while any file is still uploading or has failed; send stays blocked until it's removed.
  hasBlockingFiles: boolean;
  addDocuments: () => Promise<void>;
  addImages: () => Promise<void>;
  addRecent: (file: ProjectFile) => void;
  removeFile: (id: string) => void;
  // Call once a normal composer send is accepted: clears both the text and the attachments.
  consume: () => void;
  // Call once a starter/prompt send is accepted: clears the attachments but keeps the text.
  consumeAttachments: () => void;
}

// This is the only place that reads ComposerDraftContext — everything else goes through this
// hook, combining the context's text with file records read live from the userFileStore.
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
  // A file that's finished transferring can be sent even while the backend is still processing
  // or indexing it — only an active transfer or a failure blocks send.
  const hasBlockingFiles = useMemo(
    () =>
      files.some(
        (file) => isUploadingStatus(file.status) || isFailedFile(file),
      ),
    [files],
  );

  // Destructured so these callbacks depend on the provider's stable methods, not the whole `ctx`
  // object, which gets a new identity on every keystroke and would otherwise break FileCard's memo.
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
      // A chip's `file.id` is a temp id before its upload reconciles and the file's real server id
      // after, but the draft still stores it under the original temp id. Resolving through the
      // store's server-to-client index handles both cases (it's a no-op for an already-temp id) —
      // skipping this would leave a completed upload's chip stuck, unable to be removed.
      const store = useUserFileStore.getState();
      const clientId = store.serverIdToClientId[id] ?? id;
      ctxRemoveFile(draftKey, clientId);
      // The store only lets the draft that started an upload cancel/delete it, so this is a no-op
      // for a shared or recent-attached file — it's only de-referenced from the draft above.
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
