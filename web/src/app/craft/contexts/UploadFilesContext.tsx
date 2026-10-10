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
import { uploadFile as uploadFileApi } from "@/app/craft/services/apiServices";
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
}

function createAttachmentScope(
  sessionId: string | null,
  draftId: string | null = sessionId
): AttachmentScope {
  return { sessionId, draftId };
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

/**
 * UploadFilesContext - Centralized file upload state management
 *
 * This context manages:
 * - File attachment state (current files attached to input)
 * - Active session binding (which session files are associated with)
 * - Automatic upload of pending files when session becomes available
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
   * - Clearing files when leaving the draft
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
   * Keeps uploaded files in the sandbox for message history.
   */
  removeFile: (fileId: string) => void;

  /**
   * Clear all attached files from the input bar.
   * Does NOT delete from sandbox (use for form reset).
   */
  clearFiles: () => void;

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

  // =========================================================================
  // Public API
  // =========================================================================

  /**
   * Bind the upload destination and clear selections when their draft ends.
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
          void uploadPendingFilesInternal(sessionId);
        });
    },
    [uploadPendingFilesInternal, setCurrentMessageFiles]
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
      if (activeScopeRef.current !== activeScope) return;
      setCurrentMessageFiles((files) =>
        files.filter((file) => file.id !== fileId)
      );
    },
    [activeScope, setCurrentMessageFiles]
  );

  const clearFiles = useCallback(() => {
    if (activeScopeRef.current !== activeScope) return;
    setCurrentMessageFiles([]);
  }, [activeScope, setCurrentMessageFiles]);

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
