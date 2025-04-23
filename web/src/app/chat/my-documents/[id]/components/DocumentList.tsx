import React, { useState, useEffect, useCallback } from "react";
import {
  FileResponse,
  FolderResponse,
  useDocumentsContext,
} from "../../DocumentsContext";
import { FileListItem } from "../../components/FileListItem";
import { Button } from "@/components/ui/button";
import {
  Loader2,
  AlertCircle,
  X,
  RefreshCw,
  Trash2,
  MoreHorizontal,
} from "lucide-react";
import TextView from "@/components/chat/TextView";
import { Input } from "@/components/ui/input";
import { FileUploadSection } from "./upload/FileUploadSection";
import { SortType, SortDirection } from "../UserFolderContent";
import { CircularProgress } from "./upload/CircularProgress";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

// Define a type for uploading files that includes progress
interface UploadingFile {
  name: string;
  progress: number;
}

// Add interface for failed uploads
interface FailedUpload {
  name: string;
  error: string;
  isPopoverOpen: boolean;
}

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
  onUploadProgress?: (fileName: string, progress: number) => void;
  invalidFiles?: string[];
  showInvalidFileMessage?: boolean;
  setShowInvalidFileMessage?: React.Dispatch<React.SetStateAction<boolean>>;
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
  onUploadProgress,
  invalidFiles = [],
  showInvalidFileMessage = false,
  setShowInvalidFileMessage,
}) => {
  const [presentingDocument, setPresentingDocument] =
    useState<FileResponse | null>(null);
  const openDocument = (file: FileResponse) => {
    if (file.link_url) {
      window.open(file.link_url, "_blank");
    } else {
      setPresentingDocument(file);
    }
  };
  const [uploadingFiles, setUploadingFiles] = useState<UploadingFile[]>([]);
  const [completedFiles, setCompletedFiles] = useState<string[]>([]);
  // Add state for failed uploads
  const [failedUploads, setFailedUploads] = useState<FailedUpload[]>([]);
  const [refreshInterval, setRefreshInterval] = useState<NodeJS.Timeout | null>(
    null
  );

  // Merge external uploading files with local ones
  useEffect(() => {
    if (externalUploadingFiles.length > 0) {
      setUploadingFiles((prev) => {
        // Convert string filenames to UploadingFile objects with 0 progress
        const newFiles = externalUploadingFiles
          .filter(
            (name) =>
              !prev.some((file) => file.name === name) &&
              !completedFiles.includes(name)
          )
          .map((name) => ({ name, progress: 0 }));

        return [...prev, ...newFiles];
      });
      startRefreshInterval();
    }
  }, [externalUploadingFiles, completedFiles]);

  const { createFileFromLink } = useDocumentsContext();

  const handleCreateFileFromLink = async (url: string) => {
    setUploadingFiles((prev) => [...prev, { name: url, progress: 0 }]);

    try {
      await createFileFromLink(url, folderId);
      startRefreshInterval();
    } catch (error) {
      console.error("Error creating file from link:", error);
      // Remove from uploading files
      setUploadingFiles((prev) => prev.filter((file) => file.name !== url));
      // Add to failed uploads with isPopoverOpen initialized to false
      setFailedUploads((prev) => [
        ...prev,
        {
          name: url,
          error:
            error instanceof Error ? error.message : "Failed to upload file",
          isPopoverOpen: false,
        },
      ]);
    }
  };

  // Add handler for retrying failed uploads
  const handleRetryUpload = async (url: string) => {
    // Remove from failed uploads
    setFailedUploads((prev) => prev.filter((file) => file.name !== url));

    // Add back to uploading files
    setUploadingFiles((prev) => [...prev, { name: url, progress: 0 }]);

    try {
      await createFileFromLink(url, folderId);
      startRefreshInterval();
    } catch (error) {
      console.error("Error retrying file upload from link:", error);
      // Remove from uploading files again
      setUploadingFiles((prev) => prev.filter((file) => file.name !== url));
      // Add back to failed uploads with isPopoverOpen initialized to false
      setFailedUploads((prev) => [
        ...prev,
        {
          name: url,
          error:
            error instanceof Error ? error.message : "Failed to upload file",
          isPopoverOpen: false,
        },
      ]);
    }
  };

  // Add handler for deleting failed uploads
  const handleDeleteFailedUpload = (url: string) => {
    setFailedUploads((prev) => prev.filter((file) => file.name !== url));
  };

  const handleFileUpload = (files: File[]) => {
    const fileObjects = files.map((file) => ({
      name: file.name,
      progress: 0,
    }));

    setUploadingFiles((prev) => [...prev, ...fileObjects]);
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

  // Add a function to mark a file as complete
  const markFileComplete = (fileName: string) => {
    // Update progress to 100%
    setUploadingFiles((prev) =>
      prev.map((file) =>
        file.name === fileName ? { ...file, progress: 100 } : file
      )
    );

    // Add to completed files
    setCompletedFiles((prev) => [...prev, fileName]);

    // Remove from uploading files after showing 100% for a moment
    setTimeout(() => {
      setUploadingFiles((prev) =>
        prev.filter((file) => file.name !== fileName)
      );
    }, 2000); // Show complete state for 2 seconds

    // Remove from completed files after a longer delay
    setTimeout(() => {
      setCompletedFiles((prev) => prev.filter((name) => name !== fileName));
    }, 3000);
  };

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
        setCompletedFiles([]);
        if (updateUploadingFiles) {
          updateUploadingFiles([]);
        }
        clearInterval(interval);
        setRefreshInterval(null);
        return;
      }

      // Simulate progress for files that don't have real progress tracking yet
      setUploadingFiles((prev) =>
        prev.map((file) => {
          // Don't update files that are already complete
          if (completedFiles.includes(file.name) || file.progress >= 100) {
            return file;
          }

          // Slow down progress as it approaches completion for more realistic feel
          let increment;
          if (file.progress < 70) {
            // Normal increment for first 70%
            increment = Math.floor(Math.random() * 10) + 5;
          } else if (file.progress < 90) {
            // Slower increment between 70-90%
            increment = Math.floor(Math.random() * 5) + 2;
          } else {
            // Very slow for final 10%
            increment = Math.floor(Math.random() * 2) + 1;
          }

          const newProgress = Math.min(file.progress + increment, 99); // Cap at 99% until confirmed
          return { ...file, progress: newProgress };
        })
      );

      const allFilesUploaded = uploadingFiles.every((uploadingFile) => {
        // Skip files already marked as complete
        if (completedFiles.includes(uploadingFile.name)) {
          return true;
        }

        if (uploadingFile.name.startsWith("http")) {
          // For URL uploads, extract the domain and check for files containing it
          try {
            // Get the hostname (domain) from the URL
            const url = new URL(uploadingFile.name);
            const hostname = url.hostname;
            alert("checking for " + hostname);
            alert(JSON.stringify(files));

            // Look for recently added files that might match this URL
            const isUploaded = files.some(
              (file) =>
                // Check for hostname in filename
                file.name.toLowerCase().includes(hostname.toLowerCase()) ||
                // Check for recently created files
                (file.lastModified &&
                  new Date(file.lastModified).getTime() > startTime - 60000)
            );

            if (isUploaded) {
              // Mark as complete if found in files list
              markFileComplete(uploadingFile.name);
            }
            return isUploaded;
          } catch (e) {
            console.error("Failed to parse URL:", e);
            return false;
          }
        }

        // For regular file uploads, check if filename exists in the files list
        const isUploaded = files.some(
          (file) => file.name === uploadingFile.name
        );
        if (isUploaded) {
          // Mark as complete if found in files list
          markFileComplete(uploadingFile.name);
        }
        return isUploaded;
      });

      if (
        allFilesUploaded &&
        uploadingFiles.length > 0 &&
        completedFiles.length === uploadingFiles.length
      ) {
        // If all files are marked complete and no new uploads are happening, clean up
        setTimeout(() => {
          setUploadingFiles([]);
          setCompletedFiles([]);
          if (updateUploadingFiles) {
            updateUploadingFiles([]);
          }
          clearInterval(interval);
          setRefreshInterval(null);
        }, 2000);
      }
    }, 1000); // Update every second for smoother animation

    setRefreshInterval(interval);
  };

  useEffect(() => {
    if (uploadingFiles.length > 0 && files.length > 0) {
      // Filter out any uploading files that now exist in the files list
      const remainingUploadingFiles = uploadingFiles.filter((uploadingFile) => {
        if (uploadingFile.name.startsWith("http")) {
          try {
            // For URLs, check if any file contains the hostname
            const url = new URL(uploadingFile.name);
            const hostname = url.hostname;
            const fullUrl = uploadingFile.name;

            return (
              // !files.some((file) =>
              //   file.name.toLowerCase().includes(hostname.toLowerCase())
              // ) &&
              !files.some(
                (file) =>
                  file.link_url &&
                  // (file.link_url
                  //   .toLowerCase()
                  //   .includes(hostname.toLowerCase()) ||
                  file.link_url.toLowerCase() === fullUrl.toLowerCase()
              )
            );
          } catch (e) {
            console.error("Failed to parse URL:", e);
            return true; // Keep in the list if we can't parse
          }
        } else {
          // For regular files, check if the filename exists
          return !files.some((file) => file.name === uploadingFile.name);
        }
      });

      // Update the uploading files list if there's a change
      if (remainingUploadingFiles.length !== uploadingFiles.length) {
        setUploadingFiles(remainingUploadingFiles);

        // Also update parent component's state if the function is provided
        if (updateUploadingFiles) {
          const fileNames = remainingUploadingFiles.map((file) => file.name);
          updateUploadingFiles(fileNames);
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

  // Wrap in useCallback to prevent function recreation on each render
  const toggleFailedUploadPopover = useCallback(
    (index: number, isOpen: boolean) => {
      setFailedUploads((prev) =>
        prev.map((item, i) =>
          i === index ? { ...item, isPopoverOpen: isOpen } : item
        )
      );
    },
    []
  );

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

          <div className="default-scrollbar space-y-0 overflow-y-auto h-[calc(100%)]">
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
                  <div className="items-center flex w-full py-2 px-4 text-sm font-medium text-text-600 dark:text-neutral-400">
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
                        onSelect={() => openDocument(file)}
                        status={file.status}
                      />
                    )}
                  </div>
                ))}
                {uploadingFiles.map((uploadingFile, index) => (
                  <div
                    key={`uploading-${index}`}
                    className={`group relative flex cursor-pointer items-center border-b border-border dark:border-border-200 hover:bg-[#f2f0e8]/50 dark:hover:bg-[#1a1a1a]/50 py-4 px-4 transition-all ease-in-out ${
                      completedFiles.includes(uploadingFile.name)
                        ? "bg-green-50/30 dark:bg-green-900/10"
                        : ""
                    }`}
                  >
                    <div className="flex items-center flex-1 min-w-0">
                      <div className="flex items-center gap-3 w-[40%] min-w-0">
                        {uploadingFile.name.startsWith("http") ? (
                          <Loader2 className="w-4 h-4 animate-spin text-blue-500" />
                        ) : (
                          <CircularProgress
                            progress={uploadingFile.progress}
                            size={18}
                            showPercentage={false}
                          />
                        )}
                        <span className="truncate text-sm text-text-dark dark:text-text-dark">
                          {uploadingFile.name.startsWith("http")
                            ? `${uploadingFile.name.substring(0, 30)}${
                                uploadingFile.name.length > 30 ? "..." : ""
                              }`
                            : uploadingFile.name}
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

                {/* Failed uploads row with three dots menu on right */}
                {failedUploads.map((failedUpload, index) => (
                  <div
                    key={`failed-${index}`}
                    className="group relative flex cursor-pointer items-center border-b border-border dark:border-border-200 py-4 px-4 transition-all ease-in-out "
                  >
                    <div className="flex items-center flex-1 min-w-0">
                      <div className="flex items-center gap-3 w-[40%] min-w-0">
                        <AlertCircle className="h-4 w-4 text-red-500" />
                        <span className="truncate text-sm text-text-dark dark:text-text-dark">
                          {failedUpload.name.startsWith("http")
                            ? `${failedUpload.name.substring(0, 30)}${
                                failedUpload.name.length > 30 ? "..." : ""
                              }`
                            : failedUpload.name}
                        </span>
                      </div>
                      <div className="w-[30%] text-sm text-red-500 dark:text-red-400">
                        Upload failed
                      </div>
                      <div className="w-[30%] flex items-center justify-end">
                        <Popover
                          open={failedUpload.isPopoverOpen}
                          onOpenChange={(open) =>
                            toggleFailedUploadPopover(index, open)
                          }
                        >
                          <PopoverTrigger
                            onClick={(e) => e.stopPropagation()}
                            asChild
                          >
                            <div className="text-neutral-500 dark:text-neutral-400 cursor-pointer opacity-0 group-hover:opacity-100 transition-opacity">
                              <MoreHorizontal className="h-4 w-4" />
                            </div>
                          </PopoverTrigger>
                          <PopoverContent className="w-56 p-3 shadow-lg rounded-md border border-neutral-200 dark:border-neutral-800">
                            <div className="flex flex-col gap-3">
                              <div className="flex items-center gap-2">
                                <p className="text-xs font-medium text-red-500">
                                  Visiting URL failed.
                                  <br />
                                  You can retry or remove it from the list
                                </p>
                              </div>
                              <div className="flex flex-col gap-2">
                                <Button
                                  variant="outline"
                                  size="sm"
                                  className="w-full justify-start text-sm font-medium hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors"
                                  onClick={(e) => {
                                    e.preventDefault();
                                    e.stopPropagation();
                                    toggleFailedUploadPopover(index, false);
                                    handleRetryUpload(failedUpload.name);
                                  }}
                                >
                                  <RefreshCw className="mr-2 h-3.5 w-3.5" />
                                  Retry
                                </Button>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  className="w-full justify-start text-sm font-medium text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 hover:text-red-600 transition-colors"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    toggleFailedUploadPopover(index, false);
                                    handleDeleteFailedUpload(failedUpload.name);
                                  }}
                                >
                                  <Trash2 className="mr-2 h-3.5 w-3.5" />
                                  Remove
                                </Button>
                              </div>
                            </div>
                          </PopoverContent>
                        </Popover>
                      </div>
                    </div>
                  </div>
                ))}

                {sortedFiles.length === 0 &&
                  uploadingFiles.length === 0 &&
                  failedUploads.length === 0 && (
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

        <div className="w-full flex justify-center z-10 py-4 dark:border-neutral-800 relative">
          {showInvalidFileMessage && invalidFiles.length > 0 && (
            <div className="z-50 p-3 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-md text-yellow-800 dark:text-yellow-200 text-sm shadow-md max-w-md flex items-start absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2">
              <AlertCircle className="w-4 h-4 mr-2 flex-shrink-0 mt-0.5" />
              <div className="flex-1">
                <p className="font-medium text-xs">
                  Unsupported file type{invalidFiles.length > 1 ? "s" : ""}
                </p>
                <p className="mt-0.5 text-xs">
                  {invalidFiles.length > 1
                    ? `The following files cannot be uploaded: ${invalidFiles
                        .slice(0, 3)
                        .join(", ")}${
                        invalidFiles.length > 3
                          ? ` and ${invalidFiles.length - 3} more`
                          : ""
                      }`
                    : `The file "${invalidFiles[0]}" cannot be uploaded.`}
                </p>
              </div>
              <button
                onClick={() =>
                  setShowInvalidFileMessage && setShowInvalidFileMessage(false)
                }
                className="flex-shrink-0 text-yellow-700 dark:text-yellow-300 hover:text-yellow-900 dark:hover:text-yellow-100"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
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
