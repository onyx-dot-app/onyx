import React, { useState, useEffect } from "react";
import {
  FileResponse,
  FolderResponse,
  useDocumentsContext,
} from "../../DocumentsContext";
import {
  FileListItem,
  SkeletonFileListItem,
} from "../../components/FileListItem";
import { Button } from "@/components/ui/button";
import { Loader2, ArrowUp, ArrowDown } from "lucide-react";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import TextView from "@/components/chat/TextView";
import { Input } from "@/components/ui/input";
import { FileUploadSection } from "./upload/FileUploadSection";
import { useDocumentSelection } from "@/app/chat/useDocumentSelection";
import { getDisplayNameForModel } from "@/lib/hooks";
import { SortType, SortDirection } from "../UserFolderContent";

interface DocumentListProps {
  files: FileResponse[];
  onRename: (
    itemId: number,
    currentName: string,
    isFolder: boolean
  ) => Promise<void>;
  onDelete: (itemId: number, isFolder: boolean, itemName: string) => void;
  onDownload: (documentId: string) => Promise<void>;
  onUpload: (files: File[]) => void;
  onMove: (fileId: number, targetFolderId: number) => Promise<void>;
  folders: FolderResponse[];
  isLoading: boolean;
  disabled?: boolean;
  editingItemId: number | null;
  onSaveRename: (itemId: number, isFolder: boolean) => Promise<void>;
  onCancelRename: () => void;
  newItemName: string;
  setNewItemName: React.Dispatch<React.SetStateAction<string>>;
  folderId: number;
  tokenPercentage?: number;
  totalTokens?: number;
  maxTokens?: number;
  selectedModelName?: string;
  searchQuery?: string;
  sortType?: SortType;
  sortDirection?: SortDirection;
  onSortChange?: (newSortType: SortType) => void;
  hoveredColumn?: SortType | null;
  setHoveredColumn?: React.Dispatch<React.SetStateAction<SortType | null>>;
  renderSortIndicator?: (columnType: SortType) => JSX.Element | null;
  renderHoverIndicator?: (columnType: SortType) => JSX.Element | null;
  externalUploadingFiles?: string[];
  updateUploadingFiles?: (newUploadingFiles: string[]) => void;
}

// Animated dots component for the indexing status
export const AnimatedDots: React.FC = () => {
  const [dots, setDots] = useState(1);

  useEffect(() => {
    const interval = setInterval(() => {
      setDots((prev) => (prev === 3 ? 1 : prev + 1));
    }, 500);

    return () => clearInterval(interval);
  }, []);

  return <span>{".".repeat(dots)}</span>;
};

export const DocumentList: React.FC<DocumentListProps> = ({
  files,
  onRename,
  onDelete,
  onDownload,
  onUpload,
  onMove,
  folders,
  isLoading,
  editingItemId,
  onSaveRename,
  onCancelRename,
  newItemName,
  setNewItemName,
  folderId,
  tokenPercentage,
  totalTokens,
  maxTokens,
  selectedModelName,
  searchQuery = "",
  sortType,
  sortDirection,
  onSortChange,
  hoveredColumn,
  setHoveredColumn,
  renderSortIndicator,
  renderHoverIndicator,
  externalUploadingFiles = [],
  updateUploadingFiles,
}) => {
  const [presentingDocument, setPresentingDocument] =
    useState<FileResponse | null>(null);
  const [uploadingFiles, setUploadingFiles] = useState<string[]>([]);
  const [refreshInterval, setRefreshInterval] = useState<NodeJS.Timeout | null>(
    null
  );

  // Merge external uploading files with local ones
  useEffect(() => {
    if (externalUploadingFiles.length > 0) {
      setUploadingFiles((prev) => {
        const combinedFiles = [...prev, ...externalUploadingFiles];
        // Remove duplicates using Array.from and Set
        return Array.from(new Set(combinedFiles));
      });
      startRefreshInterval();
    }
  }, [externalUploadingFiles]);

  const { createFileFromLink } = useDocumentsContext();

  const handleCreateFileFromLink = async (url: string) => {
    setUploadingFiles((prev) => [...prev, url]);

    try {
      await createFileFromLink(url, folderId);
      startRefreshInterval();
    } catch (error) {
      console.error("Error creating file from link:", error);
    }
  };

  const handleFileUpload = (files: File[]) => {
    const fileNames = files.map((file) => file.name);
    setUploadingFiles((prev) => [...prev, ...fileNames]);

    onUpload(files);

    startRefreshInterval();
  };

  // Filter files based on search query
  const filteredFiles = searchQuery
    ? files.filter((file) =>
        file.name.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : files;

  // Sort files if sorting props are provided
  const sortedFiles =
    sortType && sortDirection
      ? [...filteredFiles].sort((a, b) => {
          let comparison = 0;

          if (sortType === SortType.TimeCreated) {
            const dateA = a.created_at ? new Date(a.created_at).getTime() : 0;
            const dateB = b.created_at ? new Date(b.created_at).getTime() : 0;
            comparison = dateB - dateA;
          } else if (sortType === SortType.Alphabetical) {
            comparison = a.name.localeCompare(b.name);
          } else if (sortType === SortType.Tokens) {
            comparison = (b.token_count || 0) - (a.token_count || 0);
          }

          return sortDirection === SortDirection.Ascending
            ? -comparison
            : comparison;
        })
      : filteredFiles;

  const startRefreshInterval = () => {
    if (refreshInterval) {
      clearInterval(refreshInterval);
    }

    // Add a timestamp to track when we started refreshing
    const startTime = Date.now();
    const MAX_REFRESH_TIME = 30000; // 30 seconds max for any upload to complete

    const interval = setInterval(() => {
      // Check if we've been waiting too long, if so, clear uploading state
      if (Date.now() - startTime > MAX_REFRESH_TIME) {
        setUploadingFiles([]);
        if (updateUploadingFiles) {
          updateUploadingFiles([]);
        }
        clearInterval(interval);
        setRefreshInterval(null);
        return;
      }

      const allFilesUploaded = uploadingFiles.every((uploadingFile) => {
        if (uploadingFile.startsWith("http")) {
          // For URL uploads, extract the domain and check for files containing it
          try {
            // Get the hostname (domain) from the URL
            const url = new URL(uploadingFile);
            const hostname = url.hostname;

            // Look for recently added files that might match this URL
            // Check if any file has this hostname in its name
            return files.some(
              (file) =>
                // Check for hostname in filename (URLs typically become domain-based filenames)
                file.name.toLowerCase().includes(hostname.toLowerCase()) ||
                // Also check for files that might have been created in the last minute
                // This is a fallback if hostname matching doesn't work
                (file.lastModified &&
                  new Date(file.lastModified).getTime() > startTime - 60000)
            );
          } catch (e) {
            // If URL parsing fails, fall back to checking if any new files exist
            console.error("Failed to parse URL:", e);
            return false; // Force continued checking
          }
        }

        // For regular file uploads, check if filename exists in the files list
        return files.some((file) => file.name === uploadingFile);
      });

      if (allFilesUploaded && uploadingFiles.length > 0) {
        setUploadingFiles([]);
        if (updateUploadingFiles) {
          updateUploadingFiles([]);
        }
        clearInterval(interval);
        setRefreshInterval(null);
      }
    }, 2000);

    setRefreshInterval(interval);
  };

  useEffect(() => {
    if (uploadingFiles.length > 0 && files.length > 0) {
      // Filter out any uploading files that now exist in the files list
      const remainingUploadingFiles = uploadingFiles.filter((uploadingFile) => {
        if (uploadingFile.startsWith("http")) {
          try {
            // For URLs, check if any file contains the hostname
            const url = new URL(uploadingFile);
            const hostname = url.hostname;

            return !files.some((file) =>
              file.name.toLowerCase().includes(hostname.toLowerCase())
            );
          } catch (e) {
            console.error("Failed to parse URL:", e);
            return true; // Keep in the list if we can't parse
          }
        } else {
          // For regular files, check if the filename exists
          return !files.some((file) => file.name === uploadingFile);
        }
      });

      // Update the uploading files list if there's a change
      if (remainingUploadingFiles.length !== uploadingFiles.length) {
        setUploadingFiles(remainingUploadingFiles);

        // Also update parent component's state if the function is provided
        if (updateUploadingFiles) {
          updateUploadingFiles(remainingUploadingFiles);
        }

        // If all files are uploaded, clear the refresh interval
        if (remainingUploadingFiles.length === 0 && refreshInterval) {
          clearInterval(refreshInterval);
          setRefreshInterval(null);
        }
      }
    }
  }, [files, uploadingFiles, refreshInterval, updateUploadingFiles]);

  useEffect(() => {
    return () => {
      if (refreshInterval) {
        clearInterval(refreshInterval);
      }
    };
  }, [refreshInterval]);

  const handleUploadComplete = () => {
    startRefreshInterval();
  };

  return (
    <>
      <div className="flex flex-col h-full">
        <div className="relative h-[calc(100vh-550px)] w-full overflow-hidden">
          {presentingDocument && (
            <TextView
              presentingDocument={{
                semantic_identifier: presentingDocument.name,
                document_id: presentingDocument.document_id,
              }}
              onClose={() => setPresentingDocument(null)}
            />
          )}

          <div className="space-y-0 overflow-y-auto h-[calc(100%)]">
            {isLoading ? (
              Array.from({ length: 3 }).map((_, index) => (
                <div
                  key={`skeleton-${index}`}
                  className="flex items-center p-3 rounded-lg border border-neutral-200 dark:border-neutral-700 animate-pulse"
                >
                  <div className="w-5 h-5 bg-neutral-200 dark:bg-neutral-700 rounded mr-3"></div>
                  <div className="flex-1">
                    <div className="h-4 bg-neutral-200 dark:bg-neutral-700 rounded w-1/3 mb-2"></div>
                    <div className="h-3 bg-neutral-200 dark:bg-neutral-700 rounded w-1/4"></div>
                  </div>
                </div>
              ))
            ) : (
              <>
                <div className="flex w-full pr-8 border-b border-border dark:border-border-200">
                  <div className="items-center flex w-full py-2 px-4 text-sm font-medium text-text-400 dark:text-neutral-400">
                    {onSortChange && setHoveredColumn ? (
                      <>
                        <button
                          onClick={() => onSortChange(SortType.Alphabetical)}
                          onMouseEnter={() =>
                            setHoveredColumn(SortType.Alphabetical)
                          }
                          onMouseLeave={() => setHoveredColumn(null)}
                          className="w-[40%] flex items-center cursor-pointer transition-colors"
                        >
                          Name {renderSortIndicator?.(SortType.Alphabetical)}
                          {renderHoverIndicator?.(SortType.Alphabetical)}
                        </button>
                        <button
                          onClick={() => onSortChange(SortType.TimeCreated)}
                          onMouseEnter={() =>
                            setHoveredColumn(SortType.TimeCreated)
                          }
                          onMouseLeave={() => setHoveredColumn(null)}
                          className="w-[30%] flex items-center cursor-pointer transition-colors"
                        >
                          Created {renderSortIndicator?.(SortType.TimeCreated)}
                          {renderHoverIndicator?.(SortType.TimeCreated)}
                        </button>
                        <button
                          onClick={() => onSortChange(SortType.Tokens)}
                          onMouseEnter={() => setHoveredColumn(SortType.Tokens)}
                          onMouseLeave={() => setHoveredColumn(null)}
                          className="w-[30%] flex items-center cursor-pointer transition-colors"
                        >
                          LLM Tokens {renderSortIndicator?.(SortType.Tokens)}
                          {renderHoverIndicator?.(SortType.Tokens)}
                        </button>
                      </>
                    ) : (
                      <>
                        <div className="w-[40%]">Name</div>
                        <div className="w-[30%]">Created</div>
                        <div className="w-[30%]">LLM Tokens</div>
                      </>
                    )}
                  </div>
                </div>

                {sortedFiles.map((file) => (
                  <div key={file.id}>
                    {editingItemId === file.id ? (
                      <div className="flex items-center p-3 rounded-lg border border-neutral-200 dark:border-neutral-700">
                        <div className="flex-1 flex items-center gap-3">
                          <Input
                            value={newItemName}
                            onChange={(e) => setNewItemName(e.target.value)}
                            className="mr-2"
                            autoFocus
                          />
                          <Button
                            onClick={() => onSaveRename(file.id, false)}
                            className="mr-2"
                            size="sm"
                          >
                            Save
                          </Button>
                          <Button
                            onClick={onCancelRename}
                            variant="outline"
                            size="sm"
                          >
                            Cancel
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <FileListItem
                        file={file}
                        view="list"
                        onRename={onRename}
                        onDelete={onDelete}
                        onDownload={onDownload}
                        onMove={onMove}
                        folders={folders}
                        onSelect={() => setPresentingDocument(file)}
                        isIndexed={file.indexed || false}
                      />
                    )}
                  </div>
                ))}
                {uploadingFiles.map((fileName, index) => (
                  <div
                    key={`uploading-${index}`}
                    className="group relative mr-8 flex cursor-pointer items-center border-b border-border dark:border-border-200 hover:bg-[#f2f0e8]/50 dark:hover:bg-[#1a1a1a]/50 py-4 px-4 transition-all ease-in-out"
                  >
                    <div className="flex items-center flex-1 min-w-0">
                      <div className="flex items-center gap-3 w-[40%] min-w-0">
                        <Loader2 className="h-4 w-4 animate-spin text-blue-500 shrink-0" />
                        <span className="truncate text-sm text-text-dark dark:text-text-dark">
                          {fileName.startsWith("http")
                            ? `Processing URL: ${fileName.substring(0, 30)}${
                                fileName.length > 30 ? "..." : ""
                              }`
                            : fileName}
                        </span>
                      </div>
                      <div className="w-[30%] text-sm text-text-400 dark:text-neutral-400">
                        -
                      </div>
                      <div className="w-[30%] flex items-center text-text-400 dark:text-neutral-400 text-sm">
                        -
                      </div>
                    </div>
                  </div>
                ))}

                {sortedFiles.length === 0 && uploadingFiles.length === 0 && (
                  <div className="text-center py-8 text-neutral-500 dark:text-neutral-400">
                    {searchQuery
                      ? "No documents match your search."
                      : "No documents in this folder yet. Upload files or add URLs to get started."}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
        <div className="w-full flex justify-center z-10 py-4   dark:border-neutral-800">
          <div className="w-full max-w-[90rem] mx-auto px-4 md:px-8 2xl:px-14 flex justify-center">
            <FileUploadSection
              onUpload={handleFileUpload}
              onUrlUpload={handleCreateFileFromLink}
              isUploading={uploadingFiles.length > 0}
              onUploadComplete={handleUploadComplete}
            />
          </div>
        </div>
      </div>
    </>
  );
};
