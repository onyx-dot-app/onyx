"use client";

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useMemo,
  useRef,
  useEffect,
  type ReactNode,
} from "react";
import {
  uploadFile as uploadFileApi,
  deleteFile as deleteFileApi,
  fetchDirectoryListing,
} from "@/app/craft/services/apiServices";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";

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
  // Original File object for upload
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

/** Blocked file extensions (executables/dangerous) - matches backend BLOCKED_EXTENSIONS */
const BLOCKED_EXTENSIONS = new Set([
  // Windows executables
  ".exe",
  ".dll",
  ".msi",
  ".scr",
  ".com",
  ".bat",
  ".cmd",
  ".ps1",
  // macOS
  ".app",
  ".dmg",
  ".pkg",
  // Linux
  ".deb",
  ".rpm",
  ".so",
  // Cross-platform
  ".jar",
  ".war",
  ".ear",
  // Other potentially dangerous
  ".vbs",
  ".vbe",
  ".wsf",
  ".wsh",
  ".hta",
  ".cpl",
  ".reg",
  ".lnk",
  ".pif",
]);

/** Format bytes to human-readable string */
function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Get file extension (lowercase, including dot) */
function getFileExtension(filename: string): string {
  const lastDot = filename.lastIndexOf(".");
  if (lastDot === -1) return "";
  return filename.slice(lastDot).toLowerCase();
}

/** Validation result for a single file */
interface FileValidationResult {
  valid: boolean;
  error?: string;
}

/** Validate a single file before upload */
function validateFile(file: File): FileValidationResult {
  // Check file size
  if (file.size > MAX_FILE_SIZE_BYTES) {
    return {
      valid: false,
      error: `File too large (${formatBytes(
        file.size
      )}). Maximum is ${formatBytes(MAX_FILE_SIZE_BYTES)}.`,
    };
  }

  // Check blocked extensions
  const ext = getFileExtension(file.name);
  if (ext && BLOCKED_EXTENSIONS.has(ext)) {
    return {
      valid: false,
      error: `File type '${ext}' is not allowed for security reasons.`,
    };
  }

  // Check for missing extension
  if (!ext) {
    return {
      valid: false,
      error: "File must have an extension.",
    };
  }

  return { valid: true };
}

/** Validate total files and size constraints */
function validateBatch(
  newFiles: File[],
  existingFiles: BuildFile[]
): FileValidationResult {
  const totalCount = existingFiles.length + newFiles.length;
  if (totalCount > MAX_FILES_PER_SESSION) {
    return {
      valid: false,
      error: `Too many files. Maximum is ${MAX_FILES_PER_SESSION} files per session.`,
    };
  }

  const existingSize = existingFiles.reduce((sum, f) => sum + f.size, 0);
  const newSize = newFiles.reduce((sum, f) => sum + f.size, 0);
  const totalSize = existingSize + newSize;

  if (totalSize > MAX_TOTAL_SIZE_BYTES) {
    return {
      valid: false,
      error: `Total size exceeds limit. Maximum is ${formatBytes(
        MAX_TOTAL_SIZE_BYTES
      )} per session.`,
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
const createOptimisticFile = (file: File): BuildFile => {
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
};

/**
 * Error types for better error handling
 */
export enum UploadErrorType {
  NETWORK = "NETWORK",
  AUTH = "AUTH",
  NOT_FOUND = "NOT_FOUND",
  SERVER = "SERVER",
  UNKNOWN = "UNKNOWN",
}

function classifyError(error: unknown): {
  type: UploadErrorType;
  message: string;
} {
  if (error instanceof Error) {
    const message = error.message.toLowerCase();
    if (message.includes("401") || message.includes("unauthorized")) {
      return { type: UploadErrorType.AUTH, message: "Session expired" };
    }
    if (message.includes("404") || message.includes("not found")) {
      return { type: UploadErrorType.NOT_FOUND, message: "Resource not found" };
    }
    if (message.includes("500") || message.includes("server")) {
      return { type: UploadErrorType.SERVER, message: "Server error" };
    }
    if (message.includes("network") || message.includes("fetch")) {
      return { type: UploadErrorType.NETWORK, message: "Network error" };
    }
    return { type: UploadErrorType.UNKNOWN, message: error.message };
  }
  return { type: UploadErrorType.UNKNOWN, message: "Upload failed" };
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
   */
  setActiveSession: (sessionId: string | null) => void;

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
  // =========================================================================
  // State
  // =========================================================================

  const [currentMessageFiles, setCurrentMessageFiles] = useState<BuildFile[]>(
    []
  );
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);

  // Get triggerFilesRefresh from the store to refresh the file explorer
  const triggerFilesRefresh = useBuildSessionStore(
    (state) => state.triggerFilesRefresh
  );

  // =========================================================================
  // Refs for race condition protection
  // =========================================================================

  const isUploadingPendingRef = useRef(false);
  const fetchingSessionRef = useRef<string | null>(null);
  const prevSessionRef = useRef<string | null>(null);
  // Track active deletions to prevent refetch race condition
  const activeDeletionsRef = useRef<Set<string>>(new Set());
  // When true, skip the refetch that runs after clearFiles (e.g. Enter to dismiss file)
  const suppressRefetchRef = useRef(false);

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

  /**
   * Upload pending files to the given session.
   * Internal function - called automatically by effects.
   * Reads current files from state internally to avoid stale closures.
   */
  const uploadPendingFilesInternal = useCallback(
    async (sessionId: string): Promise<void> => {
      if (isUploadingPendingRef.current) return;

      // Read current files and find pending ones atomically
      let pendingFiles: BuildFile[] = [];
      setCurrentMessageFiles((prev) => {
        pendingFiles = prev.filter(
          (f) => f.status === UploadFileStatus.PENDING && f.file
        );
        // Mark as uploading in the same state update to avoid race conditions
        if (pendingFiles.length > 0) {
          return prev.map((f) =>
            pendingFiles.some((pf) => pf.id === f.id)
              ? { ...f, status: UploadFileStatus.UPLOADING }
              : f
          );
        }
        return prev;
      });

      if (pendingFiles.length === 0) return;

      isUploadingPendingRef.current = true;

      try {
        // Upload in parallel
        const results = await Promise.all(
          pendingFiles.map(async (file) => {
            try {
              const result = await uploadFileApi(sessionId, file.file!);
              return { id: file.id, success: true as const, result };
            } catch (error) {
              const { message } = classifyError(error);
              return {
                id: file.id,
                success: false as const,
                errorMessage: message,
              };
            }
          })
        );

        // Update statuses
        setCurrentMessageFiles((prev) =>
          prev.map((f) => {
            const result = results.find((r) => r.id === f.id);
            if (!result) return f;
            return result.success
              ? {
                  ...f,
                  status: UploadFileStatus.COMPLETED,
                  path: result.result.path,
                  name: result.result.filename,
                  file: undefined, // Clear blob to free memory
                }
              : {
                  ...f,
                  status: UploadFileStatus.FAILED,
                  error: result.errorMessage,
                };
          })
        );

        // Refresh file explorer if any uploads succeeded
        const anySucceeded = results.some((r) => r.success);
        if (anySucceeded) {
          triggerFilesRefresh(sessionId);
        }
      } finally {
        isUploadingPendingRef.current = false;
      }
    },
    [triggerFilesRefresh]
  );

  /**
   * Fetch existing attachments from the backend.
   * Internal function - called automatically by effects.
   */
  const fetchExistingAttachmentsInternal = useCallback(
    async (sessionId: string, replace: boolean): Promise<void> => {
      // Request deduplication
      if (fetchingSessionRef.current === sessionId) return;

      fetchingSessionRef.current = sessionId;

      try {
        const listing = await fetchDirectoryListing(sessionId, "attachments");

        // Use deterministic IDs based on session and path for stable React keys
        const attachments: BuildFile[] = listing.entries
          .filter((entry) => !entry.is_directory)
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
            const localOnlyFiles = prev.filter(
              (f) =>
                f.status === UploadFileStatus.UPLOADING ||
                f.status === UploadFileStatus.PENDING ||
                f.status === UploadFileStatus.PROCESSING ||
                // Keep recently uploaded files (have temp ID, not fetched from backend)
                f.id.startsWith("temp_")
            );

            // Merge: backend attachments + local-only files (avoiding duplicates by path)
            const backendPaths = new Set(attachments.map((f) => f.path));
            const nonDuplicateLocalFiles = localOnlyFiles.filter(
              (f) => !f.path || !backendPaths.has(f.path)
            );

            return [...attachments, ...nonDuplicateLocalFiles];
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
        const { type } = classifyError(error);
        if (type !== UploadErrorType.NOT_FOUND) {
          console.error(
            "[UploadFilesContext] fetchExistingAttachments error:",
            error
          );
        }
        if (replace) {
          // On error, only clear files that aren't being processed locally
          setCurrentMessageFiles((prev) =>
            prev.filter(
              (f) =>
                f.status === UploadFileStatus.UPLOADING ||
                f.status === UploadFileStatus.PENDING ||
                f.status === UploadFileStatus.PROCESSING ||
                f.id.startsWith("temp_")
            )
          );
        }
      } finally {
        fetchingSessionRef.current = null;
      }
    },
    []
  );

  // =========================================================================
  // Effects - Automatic state machine transitions
  // =========================================================================

  /**
   * Effect: Handle session changes
   *
   * When activeSessionId changes:
   * - If changed to a DIFFERENT non-null session: fetch attachments (replace mode)
   * - If changed to null: do nothing (don't clear - session might be temporarily null during revalidation)
   *
   * This prevents unnecessary fetches/clears when the focus handler temporarily
   * resets the pre-provisioned session state.
   */
  useEffect(() => {
    const prevSession = prevSessionRef.current;
    const currentSession = activeSessionId;

    // Only update ref when we have a non-null session (ignore temporary nulls)
    if (currentSession) {
      // Session changed to a different non-null value
      if (currentSession !== prevSession) {
        prevSessionRef.current = currentSession;
        fetchExistingAttachmentsInternal(currentSession, true);
      }
    }
    // When session becomes null, don't clear files or update ref.
    // This handles the case where pre-provisioning temporarily resets on focus.
    // Files will be cleared when user actually navigates away or logs out.
  }, [activeSessionId, fetchExistingAttachmentsInternal]);

  /**
   * Effect: Auto-upload pending files when session becomes available
   *
   * This handles the case where user attaches files before session is ready.
   */
  useEffect(() => {
    if (activeSessionId && hasPendingFiles) {
      uploadPendingFilesInternal(activeSessionId);
    }
  }, [activeSessionId, hasPendingFiles, uploadPendingFilesInternal]);

  /**
   * Effect: Refetch attachments after files are cleared
   *
   * When files are cleared (e.g., after sending a message) but we're still
   * on the same session, refetch to restore any backend attachments.
   *
   * IMPORTANT: Skip refetch if files went to 0 due to active deletions.
   * This prevents a race condition where refetch returns the file before
   * backend deletion completes, causing the file pill to persist.
   */
  const prevFilesLengthRef = useRef(currentMessageFiles.length);
  useEffect(() => {
    const prevLength = prevFilesLengthRef.current;
    const currentLength = currentMessageFiles.length;
    prevFilesLengthRef.current = currentLength;

    // Files were just cleared (went from >0 to 0)
    const filesWereCleared = prevLength > 0 && currentLength === 0;

    // Skip refetch if there are active deletions in progress
    // This prevents the deleted file from being re-added before backend deletion completes
    const hasActiveDeletions = activeDeletionsRef.current.size > 0;
    // Skip refetch if caller explicitly suppressed (e.g. user hit Enter to dismiss file)
    const shouldSuppressRefetch = suppressRefetchRef.current;
    if (shouldSuppressRefetch) {
      suppressRefetchRef.current = false;
    }

    // Refetch if on same session and files were cleared (not deleted)
    if (
      filesWereCleared &&
      activeSessionId &&
      prevSessionRef.current === activeSessionId &&
      !hasActiveDeletions &&
      !shouldSuppressRefetch
    ) {
      fetchExistingAttachmentsInternal(activeSessionId, false);
    }
  }, [
    currentMessageFiles.length,
    activeSessionId,
    fetchExistingAttachmentsInternal,
  ]);

  // =========================================================================
  // Public API
  // =========================================================================

  /**
   * Set the active session. Triggers fetching/clearing as needed.
   */
  const setActiveSession = useCallback((sessionId: string | null) => {
    setActiveSessionId(sessionId);
  }, []);

  /**
   * Upload files. Uses activeSessionId internally.
   * Validates files before upload (size, extension, batch limits).
   */
  const uploadFiles = useCallback(
    async (files: File[]): Promise<BuildFile[]> => {
      // Get current files for batch validation
      const existingFiles = currentMessageFiles;

      // Validate batch constraints first
      const batchValidation = validateBatch(files, existingFiles);
      if (!batchValidation.valid) {
        // Create failed files for all with the batch error
        const failedFiles = files.map((f) =>
          createFailedFile(f, batchValidation.error!)
        );
        setCurrentMessageFiles((prev) => [...prev, ...failedFiles]);
        return failedFiles;
      }

      // Validate each file individually and separate valid from invalid
      const validFiles: File[] = [];
      const failedFiles: BuildFile[] = [];

      for (const file of files) {
        const validation = validateFile(file);
        if (validation.valid) {
          validFiles.push(file);
        } else {
          failedFiles.push(createFailedFile(file, validation.error!));
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
        // Session available - upload immediately
        const uploadPromises = optimisticFiles.map(async (optimisticFile) => {
          try {
            const result = await uploadFileApi(sessionId, optimisticFile.file!);
            return {
              id: optimisticFile.id,
              success: true as const,
              result,
            };
          } catch (error) {
            const { message } = classifyError(error);
            return {
              id: optimisticFile.id,
              success: false as const,
              errorMessage: message,
            };
          }
        });

        const results = await Promise.all(uploadPromises);

        // Batch update all file statuses
        setCurrentMessageFiles((prev) =>
          prev.map((f) => {
            const uploadResult = results.find((r) => r.id === f.id);
            if (!uploadResult) return f;

            if (uploadResult.success) {
              return {
                ...f,
                status: UploadFileStatus.COMPLETED,
                path: uploadResult.result.path,
                name: uploadResult.result.filename,
                file: undefined, // Clear blob to free memory
              };
            } else {
              return {
                ...f,
                status: UploadFileStatus.FAILED,
                error: uploadResult.errorMessage,
              };
            }
          })
        );

        // Refresh file explorer if any uploads succeeded
        const anySucceeded = results.some((r) => r.success);
        if (anySucceeded) {
          triggerFilesRefresh(sessionId);
        }
      } else {
        // No session yet - mark as PENDING (effect will auto-upload when session available)
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
    [activeSessionId, currentMessageFiles, triggerFilesRefresh]
  );

  /**
   * Remove a file. Uses activeSessionId internally for sandbox deletion.
   */
  const removeFile = useCallback(
    (fileId: string) => {
      // Track this deletion to prevent refetch race condition
      activeDeletionsRef.current.add(fileId);

      // Use functional update to get current state and avoid stale closures
      let removedFile: BuildFile | null = null;
      let removedIndex = -1;

      setCurrentMessageFiles((prev) => {
        const index = prev.findIndex((f) => f.id === fileId);
        if (index === -1) return prev;

        // Capture file info for potential rollback and backend deletion
        const file = prev[index];
        if (!file) return prev;
        removedFile = file;
        removedIndex = index;

        // Return filtered array (optimistic removal)
        return prev.filter((f) => f.id !== fileId);
      });

      // After state update, trigger backend deletion if needed
      // Use setTimeout to ensure state update has completed
      setTimeout(() => {
        if (removedFile?.path && activeSessionId) {
          const filePath = removedFile.path;
          const fileToRestore = removedFile;
          const indexToRestore = removedIndex;

          deleteFileApi(activeSessionId, filePath)
            .then(() => {
              // Deletion succeeded - remove from active deletions
              activeDeletionsRef.current.delete(fileId);
              // Refresh file explorer
              triggerFilesRefresh(activeSessionId);
            })
            .catch((error) => {
              console.error(
                "[UploadFilesContext] Failed to delete file from sandbox:",
                error
              );
              // Remove from active deletions
              activeDeletionsRef.current.delete(fileId);
              // Rollback: restore the file at its original position
              setCurrentMessageFiles((prev) => {
                // Check if file was already re-added (e.g., by another operation)
                if (prev.some((f) => f.id === fileToRestore.id)) return prev;

                const newFiles = [...prev];
                const insertIndex = Math.min(indexToRestore, newFiles.length);
                newFiles.splice(insertIndex, 0, fileToRestore);
                return newFiles;
              });
            });
        } else {
          // No backend deletion needed - remove from active deletions immediately
          activeDeletionsRef.current.delete(fileId);
        }
      }, 0);
    },
    [activeSessionId, triggerFilesRefresh]
  );

  /**
   * Clear all files from the input bar.
   */
  const clearFiles = useCallback((options?: { suppressRefetch?: boolean }) => {
    if (options?.suppressRefetch) {
      suppressRefetchRef.current = true;
    }
    setCurrentMessageFiles([]);
  }, []);

  // =========================================================================
  // Context value
  // =========================================================================

  const value = useMemo<UploadFilesContextValue>(
    () => ({
      currentMessageFiles,
      activeSessionId,
      setActiveSession,
      uploadFiles,
      removeFile,
      clearFiles,
      hasUploadingFiles,
      hasPendingFiles,
    }),
    [
      currentMessageFiles,
      activeSessionId,
      setActiveSession,
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
