"use client";

import React, {
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
} from "@/app/build/services/apiServices";

/**
 * Upload File Status - tracks the state of files being uploaded
 */
export enum UploadFileStatus {
  UPLOADING = "UPLOADING",
  PROCESSING = "PROCESSING",
  COMPLETED = "COMPLETED",
  FAILED = "FAILED",
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
  // Path in sandbox after upload (e.g., "user_uploaded_files/doc.pdf")
  path?: string;
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
        // Upload each file to the session's sandbox
        for (const optimisticFile of optimisticFiles) {
          try {
            const result = await uploadFileApi(sessionId, optimisticFile.file!);
            // Update status to completed with path
            setCurrentMessageFiles((prev) =>
              prev.map((f) =>
                f.id === optimisticFile.id
                  ? {
                      ...f,
                      status: UploadFileStatus.COMPLETED,
                      path: result.path,
                      name: result.filename,
                    }
                  : f
              )
            );
          } catch (error) {
            console.error("File upload failed:", error);
            // Mark as failed
            setCurrentMessageFiles((prev) =>
              prev.map((f) =>
                f.id === optimisticFile.id
                  ? { ...f, status: UploadFileStatus.FAILED }
                  : f
              )
            );
          }
        }
      } else {
        // No session yet - mark as pending (will upload when session is created)
        // Keep status as UPLOADING until we have a session to upload to
        setTimeout(() => {
          setCurrentMessageFiles((prev) =>
            prev.map((f) =>
              optimisticFiles.some((of) => of.id === f.id)
                ? { ...f, status: UploadFileStatus.COMPLETED }
                : f
            )
          );
        }, 100);
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
