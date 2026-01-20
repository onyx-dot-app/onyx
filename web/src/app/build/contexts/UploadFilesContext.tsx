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

  // Remove a file from current message
  removeFile: (fileId: string) => void;

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

      // TODO: Actually upload to /api/build/session/{sessionId}/files/upload
      // For now, simulate upload completion after a delay
      if (sessionId) {
        try {
          // const formData = new FormData();
          // files.forEach((file) => formData.append("files", file));
          // const response = await fetch(
          //   `/api/build/session/${sessionId}/files/upload`,
          //   { method: "POST", body: formData }
          // );
          // if (!response.ok) throw new Error("Upload failed");
          // const result = await response.json();

          // Simulate success - update status to completed
          setTimeout(() => {
            setCurrentMessageFiles((prev) =>
              prev.map((f) =>
                optimisticFiles.some((of) => of.id === f.id)
                  ? { ...f, status: UploadFileStatus.COMPLETED }
                  : f
              )
            );
          }, 500);
        } catch (error) {
          // Mark as failed
          setCurrentMessageFiles((prev) =>
            prev.map((f) =>
              optimisticFiles.some((of) => of.id === f.id)
                ? { ...f, status: UploadFileStatus.FAILED }
                : f
            )
          );
        }
      } else {
        // No session yet - just mark as completed (will upload when session starts)
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

  const removeFile = useCallback((fileId: string) => {
    setCurrentMessageFiles((prev) => prev.filter((f) => f.id !== fileId));
  }, []);

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
