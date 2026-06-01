// useComposerAttachments — owns the in-compose attachment list for the chat
// input bar (mobile analogue of web's ProjectsContext.beginUpload + currentMessageFiles).
//
// Lifecycle of an attachment:
//   1. add* → an optimistic tile (status "uploading", local URI preview for images).
//   2. upload (multipart, per file) → reconcile temp → real (file_id, status).
//   3. while backend status is PROCESSING, poll /file/statuses every 3s until terminal.
//   4. toFileDescriptors() feeds the send request; clear() empties on send.
//
// Recent files (already on the backend) are added directly — no upload — and
// deduped by file_id, mirroring web's onPickRecent.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { appConfig } from "@/lib/config";
import {
  fetchFileStatuses,
  uploadChatFiles,
  type UploadableFile,
} from "@/lib/api";
import { clientConfig } from "@/query/client";
import { queryKeys } from "@/query/keys";
import { authedChatImageSource } from "@/lib/chatImageSource";
import { isImageFile } from "@/lib/fileTypes";
import {
  ChatFileType,
  UserFileStatus,
  type FileDescriptor,
  type ProjectFile,
} from "@/lib/types";
import {
  type AttachmentTileModel,
  type AttachmentTileStatus,
} from "@/components/chat/AttachmentTile";
import { useAuthImageHeaders } from "@/components/chat/useAuthImageHeaders";

/** In-compose attachment — the single source powering the tray + send payload. */
export interface ComposerAttachment {
  /** Stable local id (list key + remove). */
  id: string;
  name: string;
  isImage: boolean;
  status: AttachmentTileStatus;
  /** Local URI for freshly-picked images (instant preview). */
  localUri?: string;
  /** Backend file reference — present once uploaded; sent in file_descriptors. */
  fileId?: string;
  /** Durable backend file id (→ user_file_id). */
  userFileId?: string;
  chatFileType: ChatFileType;
}

export interface UseComposerAttachmentsResult {
  attachments: ComposerAttachment[];
  /** Render-ready tiles for `AttachmentTray`. */
  tiles: AttachmentTileModel[];
  /** `file_id`s currently attached (for the recent-files check / toggle). */
  attachedFileIds: string[];
  /** True while any file's upload POST is still in flight (gates send). */
  isUploading: boolean;
  addImages: (files: UploadableFile[]) => void;
  addDocuments: (files: UploadableFile[]) => void;
  addRecentFile: (file: ProjectFile) => void;
  removeByFileId: (fileId: string) => void;
  remove: (id: string) => void;
  clear: () => void;
  /** FileDescriptors for the uploaded (non-failed) attachments. */
  toFileDescriptors: () => FileDescriptor[];
}

function mapStatus(status: UserFileStatus): AttachmentTileStatus {
  switch (status) {
    case UserFileStatus.COMPLETED:
    case UserFileStatus.SKIPPED:
      return "uploaded";
    case UserFileStatus.FAILED:
    case UserFileStatus.CANCELED:
      return "failed";
    default:
      // UPLOADING / PROCESSING / DELETING — still resolving on the backend.
      return "processing";
  }
}

export function useComposerAttachments(): UseComposerAttachmentsResult {
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([]);
  const queryClient = useQueryClient();
  const authHeaders = useAuthImageHeaders();

  // Monotonic local id source (avoids key collisions within a single tick).
  const counter = useRef(0);
  const nextId = useCallback(() => {
    counter.current += 1;
    return `att-${Date.now()}-${counter.current}`;
  }, []);

  // Mark a single attachment failed. Web shows the failure INLINE on the tile
  // (no modal per file), so we only flip the status — the tile renders "Failed".
  // Avoids stacking one native Alert per file when a multi-file pick fails.
  const markFailed = useCallback((id: string) => {
    setAttachments((prev) =>
      prev.map((a) => (a.id === id ? { ...a, status: "failed" } : a)),
    );
  }, []);

  const uploadOne = useCallback(
    async (id: string, file: UploadableFile) => {
      try {
        const result = await uploadChatFiles([file], clientConfig);
        const uploaded = result.user_files[0];
        if (!uploaded) {
          markFailed(id);
          return;
        }
        setAttachments((prev) =>
          prev.map((a) =>
            a.id === id
              ? {
                  ...a,
                  status: mapStatus(uploaded.status),
                  fileId: uploaded.file_id,
                  userFileId: uploaded.id,
                  chatFileType: uploaded.chat_file_type,
                }
              : a,
          ),
        );
        // Surface the freshly-uploaded file in the recent-files list.
        queryClient.invalidateQueries({ queryKey: [queryKeys.recentFiles] });
      } catch {
        markFailed(id);
      }
    },
    [markFailed, queryClient],
  );

  const addFiles = useCallback(
    (files: UploadableFile[], forceImage: boolean) => {
      const created = files.map((file) => {
        const isImage = forceImage || isImageFile(file.name);
        const attachment: ComposerAttachment = {
          id: nextId(),
          name: file.name,
          isImage,
          status: "uploading",
          localUri: isImage ? file.uri : undefined,
          chatFileType: isImage ? ChatFileType.IMAGE : ChatFileType.DOCUMENT,
        };
        return { attachment, file };
      });
      setAttachments((prev) => [...prev, ...created.map((c) => c.attachment)]);
      created.forEach(({ attachment, file }) => {
        void uploadOne(attachment.id, file);
      });
    },
    [nextId, uploadOne],
  );

  const addImages = useCallback(
    (files: UploadableFile[]) => addFiles(files, true),
    [addFiles],
  );
  const addDocuments = useCallback(
    (files: UploadableFile[]) => addFiles(files, false),
    [addFiles],
  );

  const addRecentFile = useCallback((file: ProjectFile) => {
    setAttachments((prev) => {
      if (prev.some((a) => a.fileId === file.file_id)) return prev;
      return [
        ...prev,
        {
          id: `recent-${file.file_id}`,
          name: file.name,
          isImage:
            file.chat_file_type === ChatFileType.IMAGE ||
            isImageFile(file.name),
          status: mapStatus(file.status),
          fileId: file.file_id,
          userFileId: file.id,
          chatFileType: file.chat_file_type,
        },
      ];
    });
  }, []);

  const removeByFileId = useCallback((fileId: string) => {
    setAttachments((prev) => prev.filter((a) => a.fileId !== fileId));
  }, []);

  const remove = useCallback((id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  }, []);

  const clear = useCallback(() => setAttachments([]), []);

  const toFileDescriptors = useCallback((): FileDescriptor[] => {
    return attachments
      .filter((a) => a.fileId && a.status !== "failed")
      .map((a) => ({
        id: a.fileId as string,
        type: a.chatFileType,
        name: a.name,
        user_file_id: a.userFileId ?? null,
      }));
  }, [attachments]);

  // ── Status polling (web ProjectsContext loop) ──────────────────────────────
  // While any attachment is PROCESSING on the backend, poll its status every 3s
  // until terminal. Keyed on the set of processing file_ids so the interval is
  // recreated when that set changes and torn down when it empties.
  const processingKey = attachments
    .filter((a) => a.status === "processing" && a.fileId)
    .map((a) => a.fileId as string)
    .sort()
    .join(",");

  useEffect(() => {
    if (!processingKey) return;
    const ids = processingKey.split(",");
    const interval = setInterval(() => {
      void (async () => {
        try {
          const statuses = await fetchFileStatuses(ids, clientConfig);
          setAttachments((prev) =>
            prev.map((a) => {
              const match = a.fileId
                ? statuses.find((s) => s.file_id === a.fileId)
                : undefined;
              return match ? { ...a, status: mapStatus(match.status) } : a;
            }),
          );
        } catch {
          // Transient failure — keep polling on the next tick.
        }
      })();
    }, 3000);
    return () => clearInterval(interval);
  }, [processingKey]);

  // ── Derived: render tiles + gating helpers ─────────────────────────────────
  const tiles = useMemo<AttachmentTileModel[]>(() => {
    return attachments.map((a) => {
      let imageSource: AttachmentTileModel["imageSource"];
      if (a.isImage) {
        if (a.localUri) imageSource = { uri: a.localUri };
        // Remote (recent) images need the bearer header — wait until it resolves
        // so we never fire a guaranteed-401 unauthenticated request to /chat/file.
        else if (a.fileId)
          imageSource = authedChatImageSource(
            appConfig.apiBaseUrl,
            a.fileId,
            authHeaders,
          );
      }
      return {
        id: a.id,
        name: a.name,
        isImage: a.isImage,
        status: a.status,
        imageSource,
      };
    });
  }, [attachments, authHeaders]);

  const attachedFileIds = useMemo(
    () =>
      attachments
        .map((a) => a.fileId)
        .filter((id): id is string => Boolean(id)),
    [attachments],
  );

  const isUploading = attachments.some((a) => a.status === "uploading");

  return {
    attachments,
    tiles,
    attachedFileIds,
    isUploading,
    addImages,
    addDocuments,
    addRecentFile,
    removeByFileId,
    remove,
    clear,
    toFileDescriptors,
  };
}
