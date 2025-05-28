"use client";
import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  ReactNode,
  useEffect,
  Dispatch,
  SetStateAction,
} from "react";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import * as documentsService from "@/services/documentsService";
import { ChatFileType, FileDescriptor } from "../interfaces";

export interface FolderResponse {
  id: number;
  name: string;
  description: string;
  files: FileResponse[];
  assistant_ids?: number[];
  created_at: string;
}

export enum FileStatus {
  FAILED = "FAILED",
  INDEXING = "INDEXING",
  INDEXED = "INDEXED",
  REINDEXING = "REINDEXING",
}

// this maps to UserFileSnapshot on the back end
export type FileResponse = {
  id: number;
  name: string;
  document_id: string;
  folder_id: number | null;
  size?: number;
  type?: string;
  lastModified?: string;
  token_count?: number;
  assistant_ids?: number[];
  indexed?: boolean;
  created_at?: string;
  file_id?: string;
  file_type?: string;
  link_url?: string | null;
  status: FileStatus;
  chat_file_type: ChatFileType;
};

export interface FileUploadResponse {
  file_paths: string[];
}

export interface DocumentsContextType {
  folders: FolderResponse[];
  files: FileResponse[];
  currentFolder: number | null;
  presentingDocument: MinimalOnyxDocument | null;
  searchQuery: string;
  page: number;
  isLoading: boolean;
  error: string | null;
  selectedFiles: FileResponse[];
  selectedFolders: FolderResponse[];
  addSelectedFile: (file: FileResponse) => void;
  removeSelectedFile: (file: FileResponse) => void;
  addSelectedFolder: (folder: FolderResponse) => void;
  removeSelectedFolder: (folder: FolderResponse) => void;
  clearSelectedItems: () => void;
  setSelectedFiles: (files: FileResponse[]) => void;
  setSelectedFolders: (folders: FolderResponse[]) => void;
  refreshFolders: () => Promise<void>;
  createFolder: (name: string) => Promise<FolderResponse>;
  deleteItem: (itemId: number, isFolder: boolean) => Promise<void>;
  moveItem: (
    itemId: number,
    newFolderId: number | null,
    isFolder: boolean
  ) => Promise<void>;
  renameFile: (fileId: number, newName: string) => Promise<void>;
  renameFolder: (folderId: number, newName: string) => Promise<void>;
  uploadFile: (
    formData: FormData,
    folderId: number | null
  ) => Promise<FileResponse[]>;
  setCurrentFolder: (folderId: number | null) => void;
  setPresentingDocument: (document: MinimalOnyxDocument | null) => void;
  setSearchQuery: (query: string) => void;
  setPage: (page: number) => void;
  getFilesIndexingStatus: (
    fileIds: number[]
  ) => Promise<Record<number, boolean>>;
  getFolderDetails: (folderId: number) => Promise<FolderResponse>;
  downloadItem: (documentId: string) => Promise<Blob>;
  renameItem: (
    itemId: number,
    newName: string,
    isFolder: boolean
  ) => Promise<void>;
  createFileFromLink: (
    url: string,
    folderId: number | null
  ) => Promise<FileResponse[]>;
  handleUpload: (files: File[]) => Promise<void>;
  refreshFolderDetails: () => Promise<void>;
  getFolders: () => Promise<FolderResponse[]>;
  folderDetails: FolderResponse | null | undefined;
  updateFolderDetails: (
    folderId: number,
    name: string,
    description: string
  ) => Promise<void>;
  currentMessageFiles: FileDescriptor[];
  setCurrentMessageFiles: Dispatch<SetStateAction<FileDescriptor[]>>;
}

const DocumentsContext = createContext<DocumentsContextType | undefined>(
  undefined
);

interface DocumentsProviderProps {
  children: ReactNode;
  initialFolderDetails?: FolderResponse | null;
}

export const DocumentsProvider: React.FC<DocumentsProviderProps> = ({
  children,
  initialFolderDetails,
}) => {
  const [isLoading, setIsLoading] = useState(true);
  const [folders, setFolders] = useState<FolderResponse[]>([]);
  const [currentFolder, setCurrentFolder] = useState<number | null>(null);
  const [presentingDocument, setPresentingDocument] =
    useState<MinimalOnyxDocument | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [page, setPage] = useState(1);
  const [selectedFiles, setSelectedFiles] = useState<FileResponse[]>([]);

  // uploaded files
  const [currentMessageFiles, setCurrentMessageFiles] = useState<
    FileDescriptor[]
  >([]);

  const [selectedFolders, setSelectedFolders] = useState<FolderResponse[]>([]);
  const [folderDetails, setFolderDetails] = useState<
    FolderResponse | undefined | null
  >(initialFolderDetails || null);
  const [showUploadWarning, setShowUploadWarning] = useState(false);
  const [linkUrl, setLinkUrl] = useState("");
  const [isCreatingFileFromLink, setIsCreatingFileFromLink] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchFolders = async () => {
      await refreshFolders();
      setIsLoading(false);
    };
    fetchFolders();
  }, []);

  const refreshFolders = async () => {
    try {
      console.log("fetching folders");
      const data = await documentsService.fetchFolders();
      setFolders(data);
    } catch (error) {
      console.error("Failed to fetch folders:", error);
      setError("Failed to fetch folders");
    }
  };

  const uploadFile = useCallback(
    async (
      formData: FormData,
      folderId: number | null
    ): Promise<FileResponse[]> => {
      if (folderId) {
        formData.append("folder_id", folderId.toString());
      }

      setIsLoading(true);
      setError(null);

      try {
        const response = await fetch("/api/user/file/upload", {
          method: "POST",
          body: formData,
        });

        if (!response.ok) {
          const errorData = await response.json();
          throw new Error(errorData.detail || "Failed to upload file");
        }

        const data = await response.json();
        await refreshFolders();
        return data;
      } catch (error) {
        console.error("Failed to upload file:", error);
        setError(
          error instanceof Error ? error.message : "Failed to upload file"
        );
        throw error;
      } finally {
        setIsLoading(false);
      }
    },
    [refreshFolders]
  );

  const createFolder = useCallback(
    async (name: string) => {
      try {
        const newFolder = await documentsService.createNewFolder(name, " ");
        await refreshFolders();
        return newFolder;
      } catch (error) {
        console.error("Failed to create folder:", error);
        throw error;
      }
    },
    [refreshFolders]
  );

  const deleteItem = useCallback(
    async (itemId: number, isFolder: boolean) => {
      try {
        if (isFolder) {
          await documentsService.deleteFolder(itemId);
        } else {
          await documentsService.deleteFile(itemId);
        }
        await refreshFolders();
      } catch (error) {
        console.error("Failed to delete item:", error);
        throw error;
      }
    },
    [refreshFolders]
  );

  const moveItem = async (
    itemId: number,
    newFolderId: number | null,
    isFolder: boolean
  ): Promise<void> => {
    try {
      if (isFolder) {
        // Move folder logic
        // This is a placeholder - implement actual folder moving logic
      } else {
        // Move file
        const response = await fetch(`/api/user/file/${itemId}/move`, {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ new_folder_id: newFolderId }),
        });

        if (!response.ok) {
          throw new Error("Failed to move file");
        }
      }
      await refreshFolders();
    } catch (error) {
      console.error("Failed to move item:", error);
      setError(error instanceof Error ? error.message : "Failed to move item");
      throw error;
    }
  };

  const downloadItem = useCallback(
    async (documentId: string): Promise<Blob> => {
      try {
        const blob = await documentsService.downloadItem(documentId);
        const url = window.URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = "document";
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        window.URL.revokeObjectURL(url);
        return blob;
      } catch (error) {
        console.error("Failed to download item:", error);
        throw error;
      }
    },
    []
  );

  const renameItem = useCallback(
    async (itemId: number, newName: string, isFolder: boolean) => {
      try {
        await documentsService.renameItem(itemId, newName, isFolder);
        if (isFolder) {
          await refreshFolders();
        }
      } catch (error) {
        console.error("Failed to rename item:", error);
        throw error;
      }
    },
    [refreshFolders]
  );

  const getFolderDetails = useCallback(async (folderId: number) => {
    try {
      return await documentsService.getFolderDetails(folderId);
    } catch (error) {
      console.error("Failed to get folder details:", error);
      throw error;
    }
  }, []);

  const updateFolderDetails = useCallback(
    async (folderId: number, name: string, description: string) => {
      try {
        await documentsService.updateFolderDetails(folderId, name, description);
        await refreshFolders();
      } catch (error) {
        console.error("Failed to update folder details:", error);
        throw error;
      }
    },
    [refreshFolders]
  );

  const addSelectedFile = useCallback((file: FileResponse) => {
    setSelectedFiles((prev) => {
      if (prev.find((f) => f.id === file.id)) {
        return prev;
      }
      return [...prev, file];
    });
  }, []);

  const removeSelectedFile = useCallback((file: FileResponse) => {
    setSelectedFiles((prev) => prev.filter((f) => f.id !== file.id));
  }, []);

  const addSelectedFolder = useCallback((folder: FolderResponse) => {
    setSelectedFolders((prev) => {
      if (prev.find((f) => f.id === folder.id)) {
        return prev;
      }
      return [...prev, folder];
    });
  }, []);

  const removeSelectedFolder = useCallback((folder: FolderResponse) => {
    setSelectedFolders((prev) => prev.filter((f) => f.id !== folder.id));
  }, []);

  const clearSelectedItems = useCallback(() => {
    setSelectedFiles([]);
    setSelectedFolders([]);
  }, []);

  const refreshFolderDetails = useCallback(async () => {
    if (folderDetails) {
      const details = await getFolderDetails(folderDetails.id);
      setFolderDetails(details);
    }
  }, [folderDetails, getFolderDetails]);

  const createFileFromLink = useCallback(
    async (url: string, folderId: number | null): Promise<FileResponse[]> => {
      try {
        const data = await documentsService.createFileFromLinkRequest(
          url,
          folderId
        );
        await refreshFolders();
        return data;
      } catch (error) {
        console.error("Failed to create file from link:", error);
        throw error;
      }
    },
    [refreshFolders]
  );

  const handleUpload = useCallback(
    async (files: File[]) => {
      if (
        folderDetails?.assistant_ids &&
        folderDetails.assistant_ids.length > 0
      ) {
        setShowUploadWarning(true);
      } else {
        await performUpload(files);
      }
    },
    [folderDetails]
  );

  const performUpload = useCallback(
    async (files: File[]) => {
      try {
        const formData = new FormData();
        files.forEach((file) => {
          formData.append("files", file);
        });
        setIsLoading(true);

        await uploadFile(formData, folderDetails?.id || null);
        await refreshFolderDetails();
      } catch (error) {
        console.error("Error uploading documents:", error);
        setError("Failed to upload documents. Please try again.");
      } finally {
        setIsLoading(false);
        setShowUploadWarning(false);
      }
    },
    [uploadFile, folderDetails, refreshFolderDetails]
  );

  const handleCreateFileFromLink = useCallback(async () => {
    if (!linkUrl) return;
    setIsCreatingFileFromLink(true);
    try {
      await createFileFromLink(linkUrl, folderDetails?.id || null);
      setLinkUrl("");
      await refreshFolderDetails();
    } catch (error) {
      console.error("Error creating file from link:", error);
      setError("Failed to create file from link. Please try again.");
    } finally {
      setIsCreatingFileFromLink(false);
    }
  }, [linkUrl, createFileFromLink, folderDetails, refreshFolderDetails]);

  const getFolders = async (): Promise<FolderResponse[]> => {
    try {
      const response = await fetch("/api/user/folder");
      if (!response.ok) {
        throw new Error("Failed to fetch folders");
      }
      return await response.json();
    } catch (error) {
      console.error("Error fetching folders:", error);
      return [];
    }
  };

  const getFilesIndexingStatus = async (
    fileIds: number[]
  ): Promise<Record<number, boolean>> => {
    try {
      const queryParams = fileIds.map((id) => `file_ids=${id}`).join("&");
      const response = await fetch(
        `/api/user/file/indexing-status?${queryParams}`
      );

      if (!response.ok) {
        throw new Error("Failed to fetch indexing status");
      }

      return await response.json();
    } catch (error) {
      console.error("Error fetching indexing status:", error);
      return {};
    }
  };

  const renameFile = useCallback(
    async (fileId: number, newName: string) => {
      try {
        await documentsService.renameItem(fileId, newName, false);
        await refreshFolders();
      } catch (error) {
        console.error("Failed to rename file:", error);
        throw error;
      }
    },
    [refreshFolders]
  );

  const renameFolder = useCallback(
    async (folderId: number, newName: string) => {
      try {
        await documentsService.renameItem(folderId, newName, true);
        await refreshFolders();
      } catch (error) {
        console.error("Failed to rename folder:", error);
        throw error;
      }
    },
    [refreshFolders]
  );

  const value: DocumentsContextType = {
    files: folders.map((folder) => folder.files).flat(),
    folders,
    currentFolder,
    presentingDocument,
    searchQuery,
    page,
    isLoading,
    error,
    selectedFiles,
    selectedFolders,
    addSelectedFile,
    removeSelectedFile,
    addSelectedFolder,
    removeSelectedFolder,
    clearSelectedItems,
    setSelectedFiles,
    setSelectedFolders,
    refreshFolders,
    createFolder,
    deleteItem,
    moveItem,
    renameFile,
    renameFolder,
    uploadFile,
    setCurrentFolder,
    setPresentingDocument,
    setSearchQuery,
    setPage,
    getFilesIndexingStatus,
    getFolderDetails,
    downloadItem,
    renameItem,
    createFileFromLink,
    handleUpload,
    refreshFolderDetails,
    getFolders,
    folderDetails,
    updateFolderDetails,
    currentMessageFiles,
    setCurrentMessageFiles,
  };

  return (
    <DocumentsContext.Provider value={value}>
      {children}
    </DocumentsContext.Provider>
  );
};

export const useDocumentsContext = () => {
  const context = useContext(DocumentsContext);
  if (context === undefined) {
    throw new Error("useDocuments must be used within a DocumentsProvider");
  }
  return context;
};
