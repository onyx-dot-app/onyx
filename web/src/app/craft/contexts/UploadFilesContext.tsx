"use client";

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useMemo,
  useRef,
  type ReactNode,
  type SetStateAction,
} from "react";
import { useTranslations } from "next-intl";
import {
  uploadFile as uploadFileApi,
  deleteFile as deleteFileApi,
  fetchDirectoryListing,
} from "@/app/craft/services/apiServices";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import { FetchError, isNotFoundError } from "@/lib/fetcher";

/**
 * Upload File Status - tracks the state of files being uploaded
 */
export enum UploadFileStatus {
  /** File is currently being uploaded to the sandbox */
  UPLOADING = "UPLOADING",
  /** File is being processed after upload */
  PROCESSING = "PROCESSING",
  /** File has been successfully uploaded and has a path */
  COMPLETED = "COMPLETED",
  /** File upload failed */
  FAILED = "FAILED",
  /** File is waiting for a session to be created before uploading */
  PENDING = "PENDING",
}

/**
 * Build File - represents a file attached to a build session
 */
export interface BuildFile {
  id: string;
  name: string;
  status: UploadFileStatus;
  file_type: string;
  size: number;
  created_at: string;
  // Draft source retained until send or visit end, including sandbox replacement.
  file?: File;
  // Path in sandbox after upload (e.g., "attachments/doc.pdf")
  path?: string;
  // Error message if upload failed
  error?: string;
}

// Helper to generate unique temp IDs
const generateTempId = () => {
  try {
    return `temp_${crypto.randomUUID()}`;
  } catch {
    return `temp_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`;
  }
};

// =============================================================================
// File Validation (matches backend: build/configs.py and build/utils.py)
// =============================================================================

/** Maximum individual file size - matches BUILD_MAX_UPLOAD_FILE_SIZE_MB (50MB) */
const MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024;

/** Maximum total attachment size per session - matches BUILD_MAX_TOTAL_UPLOAD_SIZE_MB (200MB) */
const MAX_TOTAL_SIZE_BYTES = 200 * 1024 * 1024;

/** Maximum files per session - matches BUILD_MAX_UPLOAD_FILES_PER_SESSION */
const MAX_FILES_PER_SESSION = 20;

/** Format bytes to human-readable string */
function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Validation result for a single file */
type FileValidationResult = { valid: true } | { valid: false; error: string };

/** Translator bound to the craft.uploadFiles namespace */
type UploadTranslate = ReturnType<typeof useTranslations<"craft.uploadFiles">>;

/** Validate a single file before upload */
function validateFile(file: File, t: UploadTranslate): FileValidationResult {
  // Check file size. Extension/type are intentionally not restricted - uploaded
  // files only run inside the isolated sandbox, which is the security boundary.
  if (file.size > MAX_FILE_SIZE_BYTES) {
    return {
      valid: false,
      error: t("errors.fileTooLarge", {
        size: formatBytes(file.size),
        max: formatBytes(MAX_FILE_SIZE_BYTES),
      }),
    };
  }

  return { valid: true };
}

/** Validate total files and size constraints */
function validateBatch(
  newFiles: File[],
  existingFiles: BuildFile[],
  t: UploadTranslate
): FileValidationResult {
  const totalCount = existingFiles.length + newFiles.length;
  if (totalCount > MAX_FILES_PER_SESSION) {
    return {
      valid: false,
      error: t("errors.tooManyFiles", { max: MAX_FILES_PER_SESSION }),
    };
  }

  const existingSize = existingFiles.reduce((sum, f) => sum + f.size, 0);
  const newSize = newFiles.reduce((sum, f) => sum + f.size, 0);
  const totalSize = existingSize + newSize;

  if (totalSize > MAX_TOTAL_SIZE_BYTES) {
    return {
      valid: false,
      error: t("errors.totalSizeExceeded", {
        max: formatBytes(MAX_TOTAL_SIZE_BYTES),
      }),
    };
  }

  return { valid: true };
}

/** Create a failed BuildFile for validation errors */
function createFailedFile(file: File, error: string): BuildFile {
  return {
    id: generateTempId(),
    name: file.name,
    status: UploadFileStatus.FAILED,
    file_type: file.type,
    size: file.size,
    created_at: new Date().toISOString(),
    error,
  };
}

// Create optimistic file from File object
function createOptimisticFile(file: File): BuildFile {
  const tempId = generateTempId();
  return {
    id: tempId,
    name: file.name,
    status: UploadFileStatus.UPLOADING,
    file_type: file.type,
    size: file.size,
    created_at: new Date().toISOString(),
    file,
  };
}

interface AttachmentScope {
  sessionId: string | null;
  // URL session owns a draft; null identifies the mounted welcome draft.
  draftId: string | null;
  fetching: boolean;
  dismissed: boolean;
  clearRevision: number;
}

function createAttachmentScope(
  sessionId: string | null,
  draftId: string | null = sessionId
): AttachmentScope {
  return {
    sessionId,
    draftId,
    fetching: false,
    dismissed: false,
    clearRevision: 0,
  };
}

function attachmentErrorMessage(error: unknown, t: UploadTranslate): string {
  if (
    error instanceof FetchError &&
    (error.status === 401 || error.status === 403)
  )
    return t("errors.sessionExpired");
  if (isNotFoundError(error)) return t("errors.notFound");
  if (error instanceof FetchError && error.status >= 500)
    return t("errors.server");
  if (error instanceof TypeError) return t("errors.network");
  return error instanceof Error ? error.message : t("errors.uploadFailed");
}

function isLocalAttachment(file: BuildFile): boolean {
  return (
    file.status === UploadFileStatus.UPLOADING ||
    file.status === UploadFileStatus.PENDING ||
    file.status === UploadFileStatus.PROCESSING ||
    file.id.startsWith("temp_")
  );
}

/**
 * UploadFilesContext - Centralized file upload state management
 *
 * This context manages:
 * - File attachment state (current files attached to input)
 * - Active session binding (which session files are associated with)
 * - Automatic upload of pending files when session becomes available
 * - Automatic fetch of existing attachments when session changes
 * - File upload, removal, and clearing operations
 *
 * Components should:
 * - Call `setActiveSession(sessionId)` when session changes
 * - Call `uploadFiles(files)` to attach files (uses active session internally)
 * - Call `removeFile(fileId)` to remove files (uses active session internally)
 * - Read `currentMessageFiles` to display attached files
 */
interface UploadFilesContextValue {
  // Current message files (attached to the input bar)
  currentMessageFiles: BuildFile[];
  getCurrentMessageFiles: () => BuildFile[];

  // Active session ID (set by parent components)
  activeSessionId: string | null;

  /**
   * Set the active session ID. This triggers:
   * - Fetching existing attachments from the new session (if different)
   * - Clearing files if navigating to no session
   * - Auto-uploading any pending files
   *
   * Call this when:
   * - Session ID changes in URL
   * - Pre-provisioned session becomes available
   * Pass the URL session as draftId; null keeps one welcome draft across sandbox replacements.
   */
  setActiveSession: (
    sessionId: string | null,
    options?: { draftId: string | null }
  ) => void;

  /** End the current chat visit, including a pending welcome session. */
  endSessionVisit: () => void;

  /**
   * Upload files to the active session.
   * - If session is available: uploads immediately
   * - If no session: marks as PENDING (auto-uploads when session available)
   */
  uploadFiles: (files: File[]) => Promise<BuildFile[]>;

  /**
   * Remove a file from the input bar.
   * If the file was uploaded, also deletes from the sandbox.
   */
  removeFile: (fileId: string) => void;

  /**
   * Clear all attached files from the input bar.
   * Does NOT delete from sandbox (use for form reset).
   * @param options.suppressRefetch - When true, skips the refetch that would
   *   normally restore session attachments (e.g. when user hits Enter to dismiss
   *   a file from the input bar).
   */
  clearFiles: (options?: { suppressRefetch?: boolean }) => void;

  // Check if any files are uploading
  hasUploadingFiles: boolean;

  // Check if any files are pending upload
  hasPendingFiles: boolean;
}

const UploadFilesContext = createContext<UploadFilesContextValue | null>(null);

export interface UploadFilesProviderProps {
  children: ReactNode;
}

export function UploadFilesProvider({ children }: UploadFilesProviderProps) {
  const t = useTranslations("craft.uploadFiles");
  // =========================================================================
  // State
  // =========================================================================

  const [currentMessageFiles, setRenderedFiles] = useState<BuildFile[]>([]);
  const currentMessageFilesRef = useRef<BuildFile[]>([]);
  // Actions publish one accepted value to React and asynchronous operations.
  const setCurrentMessageFiles = useCallback(
    (update: SetStateAction<BuildFile[]>) => {
      const next =
        typeof update === "function"
          ? update(currentMessageFilesRef.current)
          : update;
      currentMessageFilesRef.current = next;
      setRenderedFiles(next);
    },
    []
  );
  const getCurrentMessageFiles = useCallback(
    () => currentMessageFilesRef.current,
    []
  );
  const [activeScope, setActiveScope] = useState(() =>
    createAttachmentScope(null)
  );
  const activeSessionId = activeScope.sessionId;

  // Get triggerFilesRefresh from the store to refresh the file explorer
  const triggerFilesRefresh = useBuildSessionStore(
    (state) => state.triggerFilesRefresh
  );

  // =========================================================================
  // Refs for race condition protection
  // =========================================================================

  const activeScopeRef = useRef(activeScope);
  const attachmentMutationRevisionRef = useRef<number>(0);
  // Track active deletions to prevent refetch race condition
  const activeDeletionsRef = useRef<Set<string>>(new Set());

  // =========================================================================
  // Derived state
  // =========================================================================

  const hasUploadingFiles = useMemo(() => {
    return currentMessageFiles.some(
      (file) => file.status === UploadFileStatus.UPLOADING
    );
  }, [currentMessageFiles]);

  const hasPendingFiles = useMemo(() => {
    return currentMessageFiles.some(
      (file) => file.status === UploadFileStatus.PENDING
    );
  }, [currentMessageFiles]);

  // =========================================================================
  // Internal operations (not exposed to consumers)
  // =========================================================================

  // Immediate and pending uploads share completion and session-scope checks.
  const uploadAttachedFiles = useCallback(
    async (sessionId: string, files: BuildFile[]): Promise<void> => {
      const scope: AttachmentScope = activeScopeRef.current;
      if (scope.sessionId !== sessionId) return;
      const results = await Promise.all(
        files.map(async (file) => {
          if (!file.file) return undefined;
          try {
            const result = await uploadFileApi(sessionId, file.file);
            return { id: file.id, success: true as const, result };
          } catch (error) {
            return {
              id: file.id,
              success: false as const,
              errorMessage: attachmentErrorMessage(error, t),
            };
          }
        })
      );
      if (results.some((result) => result?.success))
        triggerFilesRefresh(sessionId);
      if (activeScopeRef.current !== scope) return;
      const resultsById = new Map(
        results.flatMap((result) =>
          result ? [[result.id, result] as const] : []
        )
      );
      setCurrentMessageFiles((previous) =>
        previous.map((file) => {
          const result = resultsById.get(file.id);
          if (!result) return file;
          return result.success
            ? {
                ...file,
                status: UploadFileStatus.COMPLETED,
                path: result.result.path,
                name: result.result.filename,
              }
            : {
                ...file,
                status: UploadFileStatus.FAILED,
                error: result.errorMessage,
              };
        })
      );
    },
    [triggerFilesRefresh, t, setCurrentMessageFiles]
  );

  const uploadPendingFilesInternal = useCallback(
    async (sessionId: string): Promise<void> => {
      const scope: AttachmentScope = activeScopeRef.current;
      if (scope.sessionId !== sessionId) return;
      const pendingFiles = currentMessageFilesRef.current.filter(
        (file) => file.status === UploadFileStatus.PENDING && file.file
      );
      if (pendingFiles.length === 0) return;
      const pendingIds: Set<string> = new Set(
        pendingFiles.map((file) => file.id)
      );
      setCurrentMessageFiles((files) =>
        files.map((file) =>
          pendingIds.has(file.id)
            ? { ...file, status: UploadFileStatus.UPLOADING }
            : file
        )
      );
      await uploadAttachedFiles(sessionId, pendingFiles);
    },
    [uploadAttachedFiles, setCurrentMessageFiles]
  );

  /**
   * Fetch existing attachments from the backend.
   * Session activation and attachment actions call this function.
   */
  const fetchExistingAttachmentsInternal = useCallback(
    async function fetchAttachments(
      sessionId: string,
      replace: boolean
    ): Promise<void> {
      const scope: AttachmentScope = activeScopeRef.current;
      if (scope.sessionId !== sessionId) return;
      const clearRevision = scope.clearRevision;
      const mutationRevision: number = attachmentMutationRevisionRef.current;
      let retryAfterMutation: boolean = false;
      // Request deduplication
      if (scope.fetching) return;

      scope.fetching = true;

      try {
        const listing = await fetchDirectoryListing(sessionId, "attachments");
        if (
          activeScopeRef.current !== scope ||
          scope.clearRevision !== clearRevision
        )
          return;
        if (attachmentMutationRevisionRef.current !== mutationRevision) {
          retryAfterMutation = true;
          return;
        }

        // Use deterministic IDs based on session and path for stable React keys
        const attachments: BuildFile[] = listing.entries
          .filter(
            (entry) =>
              !entry.is_directory &&
              !activeDeletionsRef.current.has(`${sessionId}:${entry.path}`)
          )
          .map((entry) => ({
            id: `existing_${sessionId}_${entry.path}`,
            name: entry.name,
            status: UploadFileStatus.COMPLETED,
            file_type: entry.mime_type || "application/octet-stream",
            size: entry.size || 0,
            created_at: new Date().toISOString(),
            path: entry.path,
          }));

        if (replace) {
          // When replacing, preserve any files that are still being processed locally
          // (uploading, pending, or recently completed uploads that might not be in
          // backend listing yet due to race conditions)
          setCurrentMessageFiles((prev) => {
            // Keep files that are still in-flight or don't have a path yet
            const localOnlyFiles = prev.filter(isLocalAttachment);

            // Local records own draft sources, including when the server lists their path.
            const localPaths = new Set(localOnlyFiles.map((file) => file.path));
            return [
              ...attachments.filter((file) => !localPaths.has(file.path)),
              ...localOnlyFiles,
            ];
          });
        } else if (attachments.length > 0) {
          setCurrentMessageFiles((prev) => {
            const existingPaths = new Set(prev.map((f) => f.path));
            const newFiles = attachments.filter(
              (f) => !existingPaths.has(f.path)
            );
            return [...prev, ...newFiles];
          });
        }
      } catch (error) {
        if (
          activeScopeRef.current !== scope ||
          scope.clearRevision !== clearRevision
        )
          return;
        if (!isNotFoundError(error)) {
          console.error(
            "[UploadFilesContext] fetchExistingAttachments error:",
            error
          );
        }
        if (replace) {
          // On error, only clear files that aren't being processed locally
          setCurrentMessageFiles((prev) => prev.filter(isLocalAttachment));
        }
      } finally {
        if (activeScopeRef.current === scope) {
          scope.fetching = false;
          if (retryAfterMutation && scope.clearRevision === clearRevision)
            await fetchAttachments(sessionId, replace);
        }
      }
    },
    [t, setCurrentMessageFiles]
  );

  // =========================================================================
  // Public API
  // =========================================================================

  /**
   * Set the active session. Triggers fetching/clearing as needed.
   */
  const resetActiveScope = useCallback(
    (
      sessionId: string | null,
      preserveFiles: boolean,
      draftId: string | null = sessionId
    ) => {
      const nextScope = createAttachmentScope(sessionId, draftId);
      activeScopeRef.current = nextScope;
      if (!preserveFiles) {
        setCurrentMessageFiles([]);
      }
      setActiveScope(nextScope);
      if (sessionId)
        queueMicrotask(() => {
          if (activeScopeRef.current !== nextScope) return;
          void fetchExistingAttachmentsInternal(sessionId, true);
          void uploadPendingFilesInternal(sessionId);
        });
    },
    [
      fetchExistingAttachmentsInternal,
      uploadPendingFilesInternal,
      setCurrentMessageFiles,
    ]
  );

  const setActiveSession = useCallback(
    (sessionId: string | null, options?: { draftId: string | null }) => {
      const previous: AttachmentScope = activeScopeRef.current;
      const draftId = options ? options.draftId : sessionId;
      if (previous.sessionId === sessionId && previous.draftId === draftId)
        return;
      // Claiming the welcome sandbox continues the same draft and pending operations.
      if (
        previous.sessionId === sessionId &&
        previous.draftId === null &&
        draftId === sessionId
      ) {
        previous.draftId = draftId;
        return;
      }
      const sameDraft = previous.draftId === draftId;
      if (sameDraft && draftId === null) {
        setCurrentMessageFiles((files) =>
          files
            .filter((file) => file.file)
            .map((file) => ({
              ...file,
              path: undefined,
              error: undefined,
              status: UploadFileStatus.PENDING,
            }))
        );
      }
      resetActiveScope(sessionId, sameDraft, draftId);
    },
    [resetActiveScope, setCurrentMessageFiles]
  );

  const endSessionVisit = useCallback(
    () => resetActiveScope(null, false),
    [resetActiveScope]
  );

  /**
   * Upload files. Uses activeSessionId internally.
   * Validates files before upload (size, batch limits).
   */
  const uploadFiles = useCallback(
    async (files: File[]): Promise<BuildFile[]> => {
      const scope: AttachmentScope = activeScopeRef.current;
      if (scope !== activeScope) return [];
      // Get current files for batch validation
      const existingFiles = currentMessageFilesRef.current;

      // Validate batch constraints first
      const batchValidation = validateBatch(files, existingFiles, t);
      if (!batchValidation.valid) {
        // Create failed files for all with the batch error
        const failedFiles = files.map((f) =>
          createFailedFile(f, batchValidation.error)
        );
        setCurrentMessageFiles((prev) => [...prev, ...failedFiles]);
        return failedFiles;
      }

      // Validate each file individually and separate valid from invalid
      const validFiles: File[] = [];
      const failedFiles: BuildFile[] = [];

      for (const file of files) {
        const validation = validateFile(file, t);
        if (validation.valid) {
          validFiles.push(file);
        } else {
          failedFiles.push(createFailedFile(file, validation.error));
        }
      }

      // Add failed files immediately
      if (failedFiles.length > 0) {
        setCurrentMessageFiles((prev) => [...prev, ...failedFiles]);
      }

      // If no valid files, return early
      if (validFiles.length === 0) {
        return failedFiles;
      }

      // Create optimistic files for valid files
      const optimisticFiles = validFiles.map(createOptimisticFile);

      // Add to current message files immediately
      setCurrentMessageFiles((prev) => [...prev, ...optimisticFiles]);

      const sessionId = activeSessionId;

      if (sessionId) {
        await uploadAttachedFiles(sessionId, optimisticFiles);
        if (activeScopeRef.current !== scope) return [];
      } else {
        // No session yet; session activation starts pending uploads.
        setCurrentMessageFiles((prev) =>
          prev.map((f) =>
            optimisticFiles.some((of) => of.id === f.id)
              ? { ...f, status: UploadFileStatus.PENDING }
              : f
          )
        );
      }

      return [...failedFiles, ...optimisticFiles];
    },
    [
      activeScope,
      activeSessionId,
      uploadAttachedFiles,
      t,
      setCurrentMessageFiles,
    ]
  );

  const removeFile = useCallback(
    (fileId: string) => {
      const scope: AttachmentScope = activeScopeRef.current;
      if (scope !== activeScope) return;
      const currentFiles = currentMessageFilesRef.current;
      const removedIndex = currentFiles.findIndex((file) => file.id === fileId);
      const removedFile = currentFiles[removedIndex];
      if (!removedFile) return;
      const deletionKey: string = `${activeSessionId}:${removedFile.path}`;
      if (activeDeletionsRef.current.has(deletionKey)) return;

      setCurrentMessageFiles((files) =>
        files.filter((file) => file.id !== fileId)
      );
      if (!removedFile.path || !activeSessionId) return;

      const deletionClearRevision = scope.clearRevision;
      activeDeletionsRef.current.add(deletionKey);
      deleteFileApi(activeSessionId, removedFile.path)
        .then(() => {
          attachmentMutationRevisionRef.current += 1;
          triggerFilesRefresh(activeSessionId);
          activeDeletionsRef.current.delete(deletionKey);
          if (activeScopeRef.current !== scope) return;
        })
        .catch((error) => {
          activeDeletionsRef.current.delete(deletionKey);
          if (
            activeScopeRef.current.dismissed &&
            (activeScopeRef.current !== scope ||
              scope.clearRevision !== deletionClearRevision)
          )
            return;
          if (activeScopeRef.current !== scope) {
            if (activeScopeRef.current.sessionId === activeSessionId)
              void fetchExistingAttachmentsInternal(activeSessionId, false);
            return;
          }
          console.error(
            "[UploadFilesContext] Failed to delete file from sandbox:",
            error
          );
          setCurrentMessageFiles((files) => {
            if (files.some((file) => file.id === removedFile.id)) return files;
            const restoredFiles = [...files];
            restoredFiles.splice(
              Math.min(removedIndex, files.length),
              0,
              removedFile
            );
            return restoredFiles;
          });
        });
    },
    [
      activeScope,
      activeSessionId,
      triggerFilesRefresh,
      fetchExistingAttachmentsInternal,
      setCurrentMessageFiles,
    ]
  );

  /**
   * Clear all files from the input bar.
   */
  const clearFiles = useCallback(
    (options?: { suppressRefetch?: boolean }) => {
      if (activeScopeRef.current !== activeScope) return;
      if (options?.suppressRefetch) {
        activeScope.dismissed = true;
        activeScope.clearRevision += 1;
      }
      const hadFiles = currentMessageFilesRef.current.length > 0;
      setCurrentMessageFiles([]);
      if (hadFiles && activeSessionId && !options?.suppressRefetch)
        void fetchExistingAttachmentsInternal(activeSessionId, false);
    },
    [
      activeScope,
      activeSessionId,
      fetchExistingAttachmentsInternal,
      setCurrentMessageFiles,
    ]
  );

  // =========================================================================
  // Context value
  // =========================================================================

  const value = useMemo<UploadFilesContextValue>(
    () => ({
      currentMessageFiles,
      getCurrentMessageFiles,
      activeSessionId,
      setActiveSession,
      endSessionVisit,
      uploadFiles,
      removeFile,
      clearFiles,
      hasUploadingFiles,
      hasPendingFiles,
    }),
    [
      currentMessageFiles,
      getCurrentMessageFiles,
      activeSessionId,
      setActiveSession,
      endSessionVisit,
      uploadFiles,
      removeFile,
      clearFiles,
      hasUploadingFiles,
      hasPendingFiles,
    ]
  );

  return (
    <UploadFilesContext.Provider value={value}>
      {children}
    </UploadFilesContext.Provider>
  );
}

export function useUploadFilesContext() {
  const context = useContext(UploadFilesContext);
  if (!context) {
    throw new Error(
      "useUploadFilesContext must be used within an UploadFilesProvider"
    );
  }
  return context;
}
