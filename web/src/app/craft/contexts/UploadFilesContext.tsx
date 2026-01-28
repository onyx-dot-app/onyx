"use client";

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useMemo,
  type ReactNode,
  type Dispatch,
  type SetStateAction,
} from "react";
import {
  uploadFile as uploadFileApi,
  deleteFile as deleteFileApi,
} from "@/app/craft/services/apiServices";

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

interface UploadFilesContextValue {
  // Current message files (attached to the input bar)
  currentMessageFiles: BuildFile[];
  setCurrentMessageFiles: Dispatch<SetStateAction<BuildFile[]>>;

  // Upload files - returns optimistic files immediately
  uploadFiles: (files: File[], sessionId?: string) => Promise<BuildFile[]>;

  // Remove a file from current message (and delete from sandbox if uploaded)
  removeFile: (fileId: string, sessionId?: string) => void;

  // Clear all current message files
  clearFiles: () => void;

  // Check if any files are uploading
  hasUploadingFiles: boolean;
}

const UploadFilesContext = createContext<UploadFilesContextValue | null>(null);

export interface UploadFilesProviderProps {
  children: ReactNode;
}

export function UploadFilesProvider({ children }: UploadFilesProviderProps) {
  const [currentMessageFiles, setCurrentMessageFiles] = useState<BuildFile[]>(
    []
  );

  const hasUploadingFiles = useMemo(() => {
    return currentMessageFiles.some(
      (file) => file.status === UploadFileStatus.UPLOADING
    );
  }, [currentMessageFiles]);

  const uploadFiles = useCallback(
    async (files: File[], sessionId?: string): Promise<BuildFile[]> => {
      // Create optimistic files
      const optimisticFiles = files.map(createOptimisticFile);

      // Add to current message files immediately
      setCurrentMessageFiles((prev) => [...prev, ...optimisticFiles]);

      if (sessionId) {
        // Upload all files in parallel for better performance
        const uploadPromises = optimisticFiles.map(async (optimisticFile) => {
          try {
            const result = await uploadFileApi(sessionId, optimisticFile.file!);
            return {
              id: optimisticFile.id,
              success: true as const,
              result,
            };
          } catch (error) {
            console.error("File upload failed:", error);
            let errorMessage = "Upload failed";
            if (error instanceof Error) {
              errorMessage = error.message;
            }
            return {
              id: optimisticFile.id,
              success: false as const,
              errorMessage,
            };
          }
        });

        const results = await Promise.all(uploadPromises);

        // Batch update all file statuses at once
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
      } else {
        // No session yet - mark as PENDING (will upload when session is created)
        // The ChatPanel fallback will handle uploading these when the session is ready
        setCurrentMessageFiles((prev) =>
          prev.map((f) =>
            optimisticFiles.some((of) => of.id === f.id)
              ? { ...f, status: UploadFileStatus.PENDING }
              : f
          )
        );
      }

      return optimisticFiles;
    },
    []
  );

  const removeFile = useCallback(
    (fileId: string, sessionId?: string) => {
      // Find the file to check if it has been uploaded
      const file = currentMessageFiles.find((f) => f.id === fileId);

      // If file has a path and sessionId is provided, delete from sandbox
      if (file?.path && sessionId) {
        deleteFileApi(sessionId, file.path).catch((error) => {
          console.error("Failed to delete file from sandbox:", error);
        });
      }

      setCurrentMessageFiles((prev) => prev.filter((f) => f.id !== fileId));
    },
    [currentMessageFiles]
  );

  const clearFiles = useCallback(() => {
    setCurrentMessageFiles([]);
  }, []);

  const value = useMemo<UploadFilesContextValue>(
    () => ({
      currentMessageFiles,
      setCurrentMessageFiles,
      uploadFiles,
      removeFile,
      clearFiles,
      hasUploadingFiles,
    }),
    [
      currentMessageFiles,
      uploadFiles,
      removeFile,
      clearFiles,
      hasUploadingFiles,
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
