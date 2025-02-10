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

export interface FolderResponse {
  id: number;
  name: string;
  description: string;
  files: FileResponse[];
  assistant_ids?: number[];
  created_at: string;
}

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
};

export interface FileUploadResponse {
  file_paths: string[];
}

export interface DocumentsContextType {
  folders: FolderResponse[];
  currentFolder: number | null;
  presentingDocument: MinimalOnyxDocument | null;
  searchQuery: string;
  page: number;
  refreshFolders: () => Promise<void>;
  createFolder: (name: string, description: string) => Promise<FolderResponse>;
  deleteItem: (itemId: number, isFolder: boolean) => Promise<void>;
  moveItem: (
    itemId: number,
    currentFolderId: number | null,
    isFolder: boolean
  ) => Promise<void>;
  downloadItem: (documentId: string) => Promise<void>;
  renameItem: (
    itemId: number,
    currentName: string,
    isFolder: boolean
  ) => Promise<void>;
  setCurrentFolder: (folderId: number | null) => void;
  setPresentingDocument: (document: MinimalOnyxDocument | null) => void;
  setSearchQuery: (query: string) => void;
  setPage: (page: number) => void;
  getFolderDetails: (folderId: number) => Promise<FolderResponse>;
  updateFolderDetails: (
    folderId: number,
    name: string,
    description: string
  ) => Promise<void>;
  isLoading: boolean;
  uploadFile: (
    formData: FormData,
    folderId: number | null
  ) => Promise<FileUploadResponse>;
  selectedFiles: FileResponse[];
  selectedFolders: FolderResponse[];
  addSelectedFile: (file: FileResponse) => void;
  removeSelectedFile: (file: FileResponse) => void;
  addSelectedFolder: (folder: FolderResponse) => void;
  removeSelectedFolder: (folder: FolderResponse) => void;
  clearSelectedItems: () => void;
  createFileFromLink: (
    url: string,
    folderId: number | null
  ) => Promise<FileUploadResponse>;
  setSelectedFiles: Dispatch<SetStateAction<FileResponse[]>>;
  setSelectedFolders: Dispatch<SetStateAction<FolderResponse[]>>;
  handleUpload: (files: File[]) => Promise<void>;
  handleCreateFileFromLink: () => Promise<void>;
  refreshFolderDetails: () => Promise<void>;
  folderDetails: FolderResponse | undefined | null;
  setFolderDetails: Dispatch<SetStateAction<FolderResponse | undefined | null>>;
  showUploadWarning: boolean;
  setShowUploadWarning: Dispatch<SetStateAction<boolean>>;
  linkUrl: string;
  setLinkUrl: Dispatch<SetStateAction<string>>;
  isCreatingFileFromLink: boolean;
  setIsCreatingFileFromLink: Dispatch<SetStateAction<boolean>>;
  error: string | null;
  setError: Dispatch<SetStateAction<string | null>>;
  getFolders: () => Promise<FolderResponse[]>;
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

  const refreshFolders = useCallback(async () => {
    try {
      const data = await documentsService.fetchFolders();
      setFolders(data);
    } catch (error) {
      console.error("Failed to fetch folders:", error);
      setError("Failed to fetch folders");
    }
  }, []);

  const uploadFile = useCallback(
    async (
      formData: FormData,
      folderId: number | null
    ): Promise<FileUploadResponse> => {
      if (folderId) {
        formData.append("folder_id", folderId.toString());
      }
      try {
        const data = await documentsService.uploadFileRequest(formData);
        await refreshFolders();
        return data;
      } catch (error) {
        console.error("Failed to upload file:", error);
        throw error;
      }
    },
    [refreshFolders]
  );

  const createFolder = useCallback(
    async (name: string, description: string) => {
      try {
        const newFolder = await documentsService.createNewFolder(
          name,
          description
        );
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

  const moveItem = useCallback(
    async (
      itemId: number,
      currentFolderId: number | null,
      isFolder: boolean
    ) => {
      try {
        await documentsService.moveItem(itemId, currentFolderId, isFolder);
        await refreshFolders();
      } catch (error) {
        console.error("Failed to move item:", error);
        throw error;
      }
    },
    [refreshFolders]
  );

  const downloadItem = useCallback(async (documentId: string) => {
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
    } catch (error) {
      console.error("Failed to download item:", error);
      throw error;
    }
  }, []);

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
    setSelectedFiles((prev) => [...prev, file]);
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
    async (
      url: string,
      folderId: number | null
    ): Promise<FileUploadResponse> => {
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

  const value: DocumentsContextType = {
    folderDetails,
    setFolderDetails,
    folders,
    currentFolder,
    presentingDocument,
    searchQuery,
    page,
    refreshFolders,
    createFolder,
    deleteItem,
    moveItem,
    downloadItem,
    renameItem,
    setCurrentFolder,
    setPresentingDocument,
    setSearchQuery,
    setPage,
    getFolderDetails,
    updateFolderDetails,
    isLoading,
    uploadFile,
    selectedFiles,
    selectedFolders,
    addSelectedFile,
    removeSelectedFile,
    addSelectedFolder,
    removeSelectedFolder,
    clearSelectedItems,
    createFileFromLink,
    setSelectedFiles,
    setSelectedFolders,
    handleUpload,
    handleCreateFileFromLink,
    refreshFolderDetails,
    showUploadWarning,
    setShowUploadWarning,
    linkUrl,
    setLinkUrl,
    isCreatingFileFromLink,
    setIsCreatingFileFromLink,
    error,
    setError,
    getFolders,
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
