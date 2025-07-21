import React, { useState, useEffect, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/Modal";
import { FolderIcon, ArrowUp, ArrowDown } from "lucide-react";
import { SelectedItemsList } from "./SelectedItemsList";
import {
  useDocumentsContext,
  FolderResponse,
  FileResponse,
} from "../DocumentsContext";
import {
  DndContext,
  closestCenter,
  DragOverlay,
  DragEndEvent,
  DragStartEvent,
  useSensor,
  useSensors,
  PointerSensor,
  DragMoveEvent,
  KeyboardSensor,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import {
  TooltipProvider,
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from "@/components/ui/tooltip";
import { usePopup } from "@/components/admin/connectors/Popup";
import { getFormattedDateTime } from "@/lib/dateUtils";
import { FileUploadSection } from "../[id]/components/upload/FileUploadSection";
import { truncateString } from "@/lib/utils";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import { getFileIconFromFileNameAndLink } from "@/lib/assistantIconUtils";
import { TokenDisplay } from "@/components/TokenDisplay";

// Define a type for uploading files that includes progress
export interface UploadingFile {
  name: string;
  progress: number;
}

const DraggableItem: React.FC<{
  id: string;
  type: "folder" | "file";
  item: FolderResponse | FileResponse;
  onClick?: () => void;
  onSelect?: (e: React.MouseEvent<HTMLDivElement>) => void;
  isSelected: boolean;
}> = ({ id, type, item, onClick, onSelect, isSelected }) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    position: "relative",
    zIndex: isDragging ? 1 : "auto",
  };

  const selectedClassName = isSelected
    ? "bg-neutral-200/50 dark:bg-neutral-800/50"
    : "hover:bg-neutral-200/50 dark:hover:bg-neutral-800/50";

  if (type === "folder") {
    return (
      <div ref={setNodeRef} style={style} {...attributes} {...listeners}>
        <FilePickerFolderItem
          folder={item as FolderResponse}
          onClick={onClick || (() => {})}
          onSelect={onSelect || (() => {})}
          isSelected={isSelected}
          allFilesSelected={false}
        />
      </div>
    );
  }

  const file = item as FileResponse;
  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      className="flex group w-full items-center"
    >
      <div className="w-6 flex items-center justify-center shrink-0">
        <div
          className={`${
            isSelected ? "" : "desktop:opacity-0 group-hover:opacity-100"
          } transition-opacity duration-150`}
          onClick={(e) => {
            e.stopPropagation();
            e.preventDefault();
            onSelect && onSelect(e);
          }}
        >
          <div
            className={`w-4 h-4 border rounded ${
              isSelected
                ? "bg-black border-black"
                : "border-neutral-400 hover:bg-neutral-100 dark:border-neutral-600"
            } flex items-center justify-center cursor-pointer hover:border-neutral-500 dark:hover:border-neutral-500  dark:hover:bg-neutral-800`}
          >
            {isSelected && (
              <svg
                width="10"
                height="10"
                viewBox="0 0 24 24"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
              >
                <path
                  d="M20 6L9 17L4 12"
                  stroke="white"
                  strokeWidth="3"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            )}
          </div>
        </div>
      </div>
      <div
        className={`group w-full relative flex cursor-pointer items-center border-b border-border dark:border-border-200 ${selectedClassName} py-2 px-3 transition-all ease-in-out`}
      >
        <div className="flex items-center flex-1 min-w-0" onClick={onClick}>
          <div className="flex text-sm items-center gap-2 w-[65%] min-w-0">
            {getFileIconFromFileNameAndLink(file.name, file.link_url)}
            {file.name.length > 34 ? (
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="truncate text-text-dark dark:text-text-dark">
                      {truncateString(file.name, 34)}
                    </span>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>{file.name}</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            ) : (
              <span className="truncate text-text-dark dark:text-text-dark">
                {file.name}
              </span>
            )}
          </div>

          <div className="w-[35%] text-right text-sm text-text-400 dark:text-neutral-400 pr-4">
            {file.created_at
              ? getFormattedDateTime(new Date(file.created_at))
              : "–"}
          </div>
        </div>
      </div>
    </div>
  );
};

const FilePickerFolderItem: React.FC<{
  folder: FolderResponse;
  onClick: () => void;
  onSelect: (e: React.MouseEvent<HTMLDivElement>) => void;
  isSelected: boolean;
  allFilesSelected: boolean;
}> = ({ folder, onClick, onSelect, isSelected, allFilesSelected }) => {
  const selectedClassName =
    isSelected || allFilesSelected
      ? "bg-neutral-200/50 dark:bg-neutral-800/50"
      : "hover:bg-neutral-200/50 dark:hover:bg-neutral-800/50";

  // Determine if the folder is empty
  const isEmpty = folder.files.length === 0;

  return (
    <div className="flex group w-full items-center">
      <div className="w-6 flex items-center justify-center shrink-0">
        {!isEmpty && (
          <div
            className={`transition-opacity duration-150 ${
              isSelected || allFilesSelected
                ? "opacity-100"
                : "desktop:opacity-0 group-hover:opacity-100"
            }`}
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onSelect(e);
            }}
          >
            <div
              className={`w-4 h-4 border rounded ${
                isSelected || allFilesSelected
                  ? "bg-black border-black"
                  : "border-neutral-400 dark:border-neutral-600"
              } flex items-center justify-center cursor-pointer hover:border-neutral-500 dark:hover:border-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800`}
            >
              {(isSelected || allFilesSelected) && (
                <svg
                  width="10"
                  height="10"
                  viewBox="0 0 24 24"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                >
                  <path
                    d="M20 6L9 17L4 12"
                    stroke="white"
                    strokeWidth="3"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              )}
            </div>
          </div>
        )}
      </div>
      <div
        className={`group w-full relative flex cursor-pointer items-center border-b border-border dark:border-border-200 ${
          !isEmpty ? selectedClassName : ""
        } py-2 px-3 transition-all ease-in-out`}
      >
        <div className="flex items-center flex-1 min-w-0" onClick={onClick}>
          <div className="flex text-sm items-center gap-2 w-[65%] min-w-0">
            <FolderIcon className="h-5 w-5 text-black dark:text-black shrink-0 fill-black dark:fill-black" />

            {folder.name.length > 40 ? (
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="truncate text-text-dark dark:text-text-dark">
                      {truncateString(folder.name, 40)}
                    </span>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>{folder.name}</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            ) : (
              <span className="truncate text-text-dark dark:text-text-dark">
                {folder.name}
              </span>
            )}
          </div>

          <div className="w-[35%] text-right text-sm text-text-400 dark:text-neutral-400 pr-4">
            {folder.files.length} {folder.files.length === 1 ? "file" : "files"}
          </div>
        </div>
      </div>
    </div>
  );
};

export interface FilePickerModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (
    selectedFiles: FileResponse[],
    selectedFolders: FolderResponse[]
  ) => void;
  buttonContent: string;
  setPresentingDocument: (onyxDocument: MinimalOnyxDocument) => void;
}

// Define a model descriptor interface
interface LLMModelDescriptor {
  modelName: string;
  maxTokens: number;
}

enum SortType {
  TimeCreated = "Time Created",
  Alphabetical = "Alphabetical",
  Files = "Files",
}

enum SortDirection {
  Ascending = "asc",
  Descending = "desc",
}

export const FilePickerModal: React.FC<FilePickerModalProps> = ({
  isOpen,
  onClose,
  onSave,
  setPresentingDocument,
  buttonContent,
}) => {
  const {
    folders,
    refreshFolders,
    uploadFile,
    currentFolder,
    setCurrentFolder,
    renameItem,
    deleteItem,
    moveItem,
    selectedFiles,
    selectedFolders,
    addSelectedFile,
    removeSelectedFile,
    removeSelectedFolder,
    addSelectedFolder,
    createFileFromLink,
  } = useDocumentsContext();

  const [isCreatingFileFromLink, setIsCreatingFileFromLink] = useState(false);
  const [isUploadingFile, setIsUploadingFile] = useState(false);

  // Add new state variables for progress tracking
  const [uploadingFiles, setUploadingFiles] = useState<UploadingFile[]>([]);
  const [completedFiles, setCompletedFiles] = useState<string[]>([]);
  const [refreshInterval, setRefreshInterval] = useState<NodeJS.Timeout | null>(
    null
  );

  const [searchQuery, setSearchQuery] = useState("");
  const [currentFolderFiles, setCurrentFolderFiles] = useState<FileResponse[]>(
    []
  );
  const [activeId, setActiveId] = useState<string | null>(null);
  const [isHoveringRight, setIsHoveringRight] = useState(false);

  let activeSplit = "";
  if (activeId !== undefined && activeId !== null) {
    const active_part_1 = activeId.split("-")[1];
    if (active_part_1) {
      activeSplit = active_part_1;
    }
  }

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const [selectedFileIds, setSelectedFileIds] = useState<Set<number>>(
    new Set()
  );
  const [selectedFolderIds, setSelectedFolderIds] = useState<Set<number>>(
    new Set()
  );

  const { setPopup } = usePopup();

  // Create model descriptors and selectedModel state
  // why is this hardcoded here?
  const modelDescriptors: LLMModelDescriptor[] = [
    { modelName: "Claude 3 Opus", maxTokens: 200000 },
    { modelName: "Claude 3 Sonnet", maxTokens: 180000 },
    { modelName: "GPT-4", maxTokens: 128000 },
  ];

  const firstModelDescriptor = modelDescriptors[0]!;

  const [selectedModel, setSelectedModel] = useState(firstModelDescriptor);

  // Add a new state for tracking uploads
  const [uploadStartTime, setUploadStartTime] = useState<number | null>(null);
  const MAX_UPLOAD_TIME = 30000; // 30 seconds max for any upload

  const [sortType, setSortType] = useState<SortType>(SortType.TimeCreated);
  const [sortDirection, setSortDirection] = useState<SortDirection>(
    SortDirection.Descending
  );
  const [hoveredColumn, setHoveredColumn] = useState<SortType | null>(null);

  useEffect(() => {
    if (isOpen) {
      // Initialize selected file IDs
      const fileIds = new Set<number>();
      selectedFiles.forEach((file) => fileIds.add(file.id));
      setSelectedFileIds(fileIds);

      // Initialize selected folder IDs
      const folderIds = new Set<number>();
      selectedFolders.forEach((folder) => folderIds.add(folder.id));
      setSelectedFolderIds(folderIds);
    }
  }, [isOpen, selectedFiles, selectedFolders]);

  useEffect(() => {
    if (currentFolder) {
      if (currentFolder === -1) {
        // For the special "Recent" folder (id: -1), include files not in any folder that are selected
        const folder = folders.find((f) => f.id === currentFolder);
        const filesInFolder = folder?.files || [];

        // Get selected files that are not in any folder
        const selectedFilesNotInFolders = selectedFiles.filter(
          (file) => !folders.some((f) => f.id === file.folder_id)
        );

        const combinedFiles = [...filesInFolder, ...selectedFilesNotInFolders];

        // Sort the files
        const sortedFiles = combinedFiles.sort((a, b) => {
          let comparison = 0;

          if (sortType === SortType.TimeCreated) {
            comparison =
              new Date(b.created_at || "").getTime() -
              new Date(a.created_at || "").getTime();
          } else if (sortType === SortType.Alphabetical) {
            comparison = a.name.localeCompare(b.name);
          }

          return sortDirection === SortDirection.Ascending
            ? -comparison
            : comparison;
        });

        setCurrentFolderFiles(sortedFiles);
      } else {
        const folder = folders.find(
          (f) => f.id === currentFolder && f.name != "Recent Documents"
        );
        const files = folder?.files || [];

        // Sort the files
        const sortedFiles = [...files].sort((a, b) => {
          let comparison = 0;

          if (sortType === SortType.TimeCreated) {
            comparison =
              new Date(b.created_at || "").getTime() -
              new Date(a.created_at || "").getTime();
          } else if (sortType === SortType.Alphabetical) {
            comparison = a.name.localeCompare(b.name);
          }

          return sortDirection === SortDirection.Ascending
            ? -comparison
            : comparison;
        });

        setCurrentFolderFiles(sortedFiles);
      }
    } else {
      setCurrentFolderFiles([]);
    }
  }, [currentFolder, folders, selectedFiles, sortType, sortDirection]);

  useEffect(() => {
    if (searchQuery) {
      setCurrentFolder(null);
    }
  }, [searchQuery]);

  // Add a useEffect to check for timed-out uploads
  useEffect(() => {
    if (isUploadingFile || isCreatingFileFromLink) {
      if (!uploadStartTime) {
        setUploadStartTime(Date.now());
      }

      const timer = setTimeout(() => {
        // If uploads have been going on for too long, reset the state
        if (uploadStartTime && Date.now() - uploadStartTime > MAX_UPLOAD_TIME) {
          setIsUploadingFile(false);
          setIsCreatingFileFromLink(false);
          setUploadStartTime(null);
          refreshFolders(); // Make sure we have the latest files
        }
      }, MAX_UPLOAD_TIME + 1000); // Check just after the max time

      return () => clearTimeout(timer);
    } else {
      // Reset when not uploading
      setUploadStartTime(null);
    }
  }, [
    isUploadingFile,
    isCreatingFileFromLink,
    uploadStartTime,
    refreshFolders,
  ]);

  const handleFolderClick = (folderId: number) => {
    setCurrentFolder(folderId);
    const clickedFolder = folders.find((f) => f.id === folderId);
    if (clickedFolder) {
      setCurrentFolderFiles(clickedFolder.files || []);
    } else {
      setCurrentFolderFiles([]);
    }
  };
  const handleFileClick = (file: FileResponse) => {
    if (file.link_url) {
      window.open(file.link_url, "_blank");
    } else {
      setPresentingDocument({
        document_id: file.document_id,
        semantic_identifier: file.name,
      });
    }
  };

  const handleFileSelect = (
    e: React.MouseEvent<HTMLDivElement>,
    file: FileResponse
  ) => {
    e.stopPropagation();
    setSelectedFileIds((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(file.id)) {
        newSet.delete(file.id);
        removeSelectedFile(file);
      } else {
        newSet.add(file.id);
        addSelectedFile(file);
      }
      return newSet;
    });
    // Check if the file's folder should be unselected
    if (file.folder_id) {
      setSelectedFolderIds((prev) => {
        const newSet = new Set(prev);
        if (newSet.has(file.folder_id!)) {
          const folder = folders.find((f) => f.id === file.folder_id);
          if (folder) {
            const allFilesSelected = folder.files.every(
              (f) => selectedFileIds.has(f.id) || f.id === file.id
            );

            if (!allFilesSelected) {
              newSet.delete(file.folder_id!);
              if (folder) {
                removeSelectedFolder(folder);
              }
            }
          }
        }
        return newSet;
      });
    }
  };

  const RECENT_DOCS_FOLDER_ID = -1;

  const isRecentFolder = (folderId: number) =>
    folderId === RECENT_DOCS_FOLDER_ID;

  const handleFolderSelect = (folder: FolderResponse) => {
    // Special handling for the recent folder
    const isRecent = isRecentFolder(folder.id);

    setSelectedFolderIds((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(folder.id)) {
        newSet.delete(folder.id);
        removeSelectedFolder(folder);

        // For the recent folder, also remove all its files from selection
        if (isRecent) {
          folder.files.forEach((file) => {
            if (selectedFileIds.has(file.id)) {
              removeSelectedFile(file);
            }
          });
        }
      } else {
        newSet.add(folder.id);
        addSelectedFolder(folder);
      }
      return newSet;
    });

    // Update selectedFileIds based on folder selection
    setSelectedFileIds((prev) => {
      const newSet = new Set(prev);

      // For the recent folder, we need special handling
      if (isRecent) {
        // If we're selecting the recent folder, don't automatically select all its files
        if (!selectedFolderIds.has(folder.id)) {
          return newSet;
        }
      }

      folder.files.forEach((file) => {
        if (selectedFolderIds.has(folder.id)) {
          newSet.delete(file.id);
        } else {
          newSet.add(file.id);
        }
      });
      return newSet;
    });
  };

  const selectedItems = useMemo(() => {
    const items: {
      folders: FolderResponse[];
      files: FileResponse[];
      totalTokens: number;
    } = {
      folders: [],
      files: [],
      totalTokens: 0,
    };

    // First handle selected files that are not in any folder
    selectedFiles.forEach((file) => {
      if (!folders.some((f) => f.id === file.folder_id)) {
        items.files.push(file);
        items.totalTokens += file.token_count || 0;
      }
    });

    // Then handle folders and their files
    folders.forEach((folder) => {
      // For the recent folder, only include it if explicitly selected
      if (isRecentFolder(folder.id)) {
        if (selectedFolderIds.has(folder.id)) {
          items.folders.push(folder);
          folder.files.forEach((file) => {
            items.totalTokens += file.token_count || 0;
          });
        } else {
          // For the recent folder, include individually selected files
          const selectedFilesInFolder = folder.files.filter((file) =>
            selectedFileIds.has(file.id)
          );
          items.files.push(...selectedFilesInFolder);
          selectedFilesInFolder.forEach((file) => {
            items.totalTokens += file.token_count || 0;
          });
        }
        return;
      }

      // For regular folders
      if (selectedFolderIds.has(folder.id)) {
        items.folders.push(folder);
        folder.files.forEach((file) => {
          items.totalTokens += file.token_count || 0;
        });
      } else {
        const selectedFilesInFolder = folder.files.filter((file) =>
          selectedFileIds.has(file.id)
        );
        if (
          selectedFilesInFolder.length === folder.files.length &&
          folder.files.length > 0
        ) {
          items.folders.push(folder);
          folder.files.forEach((file) => {
            items.totalTokens += file.token_count || 0;
          });
        } else {
          items.files.push(...selectedFilesInFolder);
          selectedFilesInFolder.forEach((file) => {
            items.totalTokens += file.token_count || 0;
          });
        }
      }
    });

    return items;
  }, [folders, selectedFileIds, selectedFolderIds, selectedFiles]);

  // Add these new functions for tracking upload progress
  const updateFileProgress = (fileName: string, progress: number) => {
    setUploadingFiles((prev) =>
      prev.map((file) =>
        file.name === fileName ? { ...file, progress } : file
      )
    );
  };

  const markFileComplete = (fileName: string) => {
    setUploadingFiles((prev) => prev.filter((file) => file.name !== fileName));
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

            // Look for recently added files that might match this URL
            const isUploaded = folders.some((folder) =>
              folder.files.some(
                (file) =>
                  file.name.toLowerCase().includes(hostname.toLowerCase()) ||
                  (file.lastModified &&
                    new Date(file.lastModified).getTime() > startTime - 60000)
              )
            );

            if (isUploaded) {
              // Mark as complete if found in files list
              markFileComplete(uploadingFile.name);
            }
            return isUploaded;
          } catch (e) {
            console.error("Failed to parse URL:", e);
            return false; // Force continued checking
          }
        }

        // For regular file uploads, check if filename exists in the folders
        const isUploaded = folders.some((folder) =>
          folder.files.some((file) => file.name === uploadingFile.name)
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
          clearInterval(interval);
          setRefreshInterval(null);
        }, 2000);
      }
    }, 1000); // Update every second for smoother animation

    setRefreshInterval(interval);
  };

  // Cleanup interval on component unmount
  useEffect(() => {
    return () => {
      if (refreshInterval) {
        clearInterval(refreshInterval);
      }
    };
  }, [refreshInterval]);

  const addUploadedFileToContext = async (files: FileList) => {
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      if (file === undefined) {
        continue;
      }
      // Add file to uploading files state
      setUploadingFiles((prev) => [...prev, { name: file.name, progress: 0 }]);
      const formData = new FormData();
      formData.append("files", file);
      const response: FileResponse[] = await uploadFile(formData, null);

      if (response.length > 0) {
        const uploadedFile = response[0];
        if (uploadedFile !== undefined) {
          addSelectedFile(uploadedFile);
        }

        markFileComplete(file.name);
      }
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files) {
      setIsUploadingFile(true);
      try {
        await addUploadedFileToContext(files);
        await refreshFolders();
      } catch (error) {
        console.error("Error uploading file:", error);
      } finally {
        setIsUploadingFile(false);
      }
    }
  };

  const handleDragStart = (event: DragStartEvent) => {
    setActiveId(event.active.id.toString());
  };

  const handleDragMove = (event: DragMoveEvent) => {};

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    setActiveId(null);
    setIsHoveringRight(false);
  };

  const handleDragCancel = () => {
    setActiveId(null);
    setIsHoveringRight(false);
  };

  const handleSortChange = (newSortType: SortType) => {
    if (sortType === newSortType) {
      setSortDirection(
        sortDirection === SortDirection.Ascending
          ? SortDirection.Descending
          : SortDirection.Ascending
      );
    } else {
      setSortType(newSortType);
      setSortDirection(SortDirection.Descending);
    }
  };

  const renderSortIndicator = (columnType: SortType) => {
    if (sortType !== columnType) return null;

    return sortDirection === SortDirection.Ascending ? (
      <ArrowUp className="ml-1 h-3 w-3 inline" />
    ) : (
      <ArrowDown className="ml-1 h-3 w-3 inline" />
    );
  };

  const renderHoverIndicator = (columnType: SortType) => {
    if (sortType === columnType || hoveredColumn !== columnType) return null;

    return <ArrowDown className="ml-1 h-3 w-3 inline opacity-70" />;
  };

  const filteredFolders = folders
    .filter(function (folder) {
      return folder.name.toLowerCase().includes(searchQuery.toLowerCase());
    })
    .sort((a, b) => {
      let comparison = 0;

      if (sortType === SortType.TimeCreated) {
        comparison =
          new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
      } else if (sortType === SortType.Alphabetical) {
        comparison = a.name.localeCompare(b.name);
      } else if (sortType === SortType.Files) {
        comparison = b.files.length - a.files.length;
      }

      return sortDirection === SortDirection.Ascending
        ? -comparison
        : comparison;
    });

  const renderNavigation = () => {
    if (currentFolder !== null) {
      return (
        <div
          className="flex items-center mb-2 text-sm text-neutral-600 cursor-pointer hover:text-neutral-800"
          onClick={() => setCurrentFolder(null)}
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="h-4 w-4 mr-1"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M15 19l-7-7 7-7"
            />
          </svg>
          Back to My Documents
        </div>
      );
    }
    return null;
  };

  const isAllFilesInFolderSelected = (folder: FolderResponse) => {
    return folder.files.every((file) => selectedFileIds.has(file.id));
  };

  const handleRenameItem = async (
    itemId: number,
    currentName: string,
    isFolder: boolean
  ) => {
    const newName = prompt(
      `Enter new name for ${isFolder ? "folder" : "file"}:`,
      currentName
    );
    if (newName && newName !== currentName) {
      try {
        await renameItem(itemId, newName, isFolder);
        setPopup({
          message: `${isFolder ? "Folder" : "File"} renamed successfully`,
          type: "success",
        });
        await refreshFolders();
      } catch (error) {
        console.error("Error renaming item:", error);
        setPopup({
          message: `Failed to rename ${isFolder ? "folder" : "file"}`,
          type: "error",
        });
      }
    }
  };

  const handleDeleteItem = async (itemId: number, isFolder: boolean) => {
    const itemType = isFolder ? "folder" : "file";
    const confirmDelete = window.confirm(
      `Are you sure you want to delete this ${itemType}?`
    );

    if (confirmDelete) {
      try {
        await deleteItem(itemId, isFolder);
        setPopup({
          message: `${itemType} deleted successfully`,
          type: "success",
        });
        await refreshFolders();
      } catch (error) {
        console.error("Error deleting item:", error);
        setPopup({
          message: `Failed to delete ${itemType}`,
          type: "error",
        });
      }
    }
  };

  const handleMoveItem = async (
    itemId: number,
    currentFolderId: number | null,
    isFolder: boolean
  ) => {
    const availableFolders = folders
      .filter((folder) => folder.id !== itemId)
      .map((folder) => `${folder.id}: ${folder.name}`)
      .join("\n");

    const promptMessage = `Enter the ID of the destination folder:\n\nAvailable folders:\n${availableFolders}\n\nEnter 0 to move to the root folder.`;
    const destinationFolderId = prompt(promptMessage);

    if (destinationFolderId !== null) {
      const newFolderId = parseInt(destinationFolderId, 10);
      if (isNaN(newFolderId)) {
        setPopup({
          message: "Invalid folder ID",
          type: "error",
        });
        return;
      }

      try {
        await moveItem(
          itemId,
          newFolderId === 0 ? null : newFolderId,
          isFolder
        );
        setPopup({
          message: `${isFolder ? "Folder" : "File"} moved successfully`,
          type: "success",
        });
        await refreshFolders();
      } catch (error) {
        console.error("Error moving item:", error);
        setPopup({
          message: "Failed to move item",
          type: "error",
        });
      }
    }
  };

  // Add these new functions for removing files and groups
  const handleRemoveFile = (file: FileResponse) => {
    setSelectedFileIds((prev) => {
      const newSet = new Set(prev);
      newSet.delete(file.id);
      return newSet;
    });
    removeSelectedFile(file);
  };

  const handleRemoveFolder = (folder: FolderResponse) => {
    // Special handling for the recent folder
    if (isRecentFolder(folder.id)) {
      // Also remove all files in the recent folder from selection
      folder.files.forEach((file) => {
        if (selectedFileIds.has(file.id)) {
          setSelectedFileIds((prev) => {
            const newSet = new Set(prev);
            newSet.delete(file.id);
            return newSet;
          });
          removeSelectedFile(file);
        }
      });
    }

    setSelectedFolderIds((prev) => {
      const newSet = new Set(prev);
      newSet.delete(folder.id);
      return newSet;
    });
    removeSelectedFolder(folder);
  };

  return (
    <Modal
      noPadding
      hideDividerForTitle
      onOutsideClick={onClose}
      increasedPadding
      className="max-w-4xl py-6 px-1 flex flex-col w-full !overflow-visible h-[70vh]"
      title={
        currentFolder
          ? folders?.find((folder) => folder.id === currentFolder)?.name
          : "My Documents"
      }
    >
      <div className="h-[calc(70vh-5rem)] flex overflow-visible flex-col">
        <div className="grid overflow-x-visible h-full overflow-y-hidden flex-1  w-full divide-x divide-neutral-200 dark:divide-neutral-700 desktop:grid-cols-2">
          <div className="w-full h-full pb-4 overflow-hidden ">
            <div className="px-6 sticky flex flex-col gap-y-2 z-[1000] top-0 mb-2 flex gap-x-2 w-full pr-4">
              <div className="w-full relative">
                <input
                  type="text"
                  placeholder="Search documents..."
                  className="w-full pl-10 pr-4 py-2 border border-neutral-300 dark:border-neutral-600 rounded-md focus:border-transparent dark:bg-neutral-800 dark:text-neutral-100"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />

                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                  <svg
                    className="h-5 w-5 text-text-dark dark:text-neutral-400"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                    />
                  </svg>
                </div>
              </div>
              {renderNavigation()}
            </div>

            {filteredFolders.length + currentFolderFiles.length > 0 ? (
              <div className="pl-2 h-full flex-grow  overflow-y-auto max-h-full default-scrollbar pr-4">
                <div className="flex ml-6 items-center border-b border-border dark:border-border-200 py-2 pr-3 text-sm font-medium text-text-400 dark:text-neutral-400">
                  <div className="flex pl-2 items-center gap-3 w-[65%] min-w-0">
                    <button
                      onClick={() => handleSortChange(SortType.Alphabetical)}
                      onMouseEnter={() =>
                        setHoveredColumn(SortType.Alphabetical)
                      }
                      onMouseLeave={() => setHoveredColumn(null)}
                      className="px-1 cursor-pointer flex items-center"
                    >
                      Name
                      {renderSortIndicator(SortType.Alphabetical)}
                      {renderHoverIndicator(SortType.Alphabetical)}
                    </button>
                  </div>
                  <div className="w-[35%] text-right pr-4">
                    <button
                      onClick={() =>
                        handleSortChange(
                          currentFolder === null
                            ? SortType.Files
                            : SortType.TimeCreated
                        )
                      }
                      onMouseEnter={() =>
                        setHoveredColumn(
                          currentFolder === null
                            ? SortType.Files
                            : SortType.TimeCreated
                        )
                      }
                      onMouseLeave={() => setHoveredColumn(null)}
                      className="cursor-pointer flex items-center justify-end w-full ml-auto"
                    >
                      <span className="ml-auto gap-x-1 flex items-center">
                        {renderSortIndicator(
                          currentFolder === null
                            ? SortType.Files
                            : SortType.TimeCreated
                        )}
                        {renderHoverIndicator(
                          currentFolder === null
                            ? SortType.Files
                            : SortType.TimeCreated
                        )}
                        {currentFolder === null ? "Files" : "Created"}
                      </span>
                    </button>
                  </div>
                </div>

                {/* {JSON.stringify(folders)} */}
                <DndContext
                  sensors={sensors}
                  onDragStart={handleDragStart}
                  onDragMove={handleDragMove}
                  onDragEnd={handleDragEnd}
                  onDragCancel={handleDragCancel}
                  collisionDetection={closestCenter}
                >
                  <SortableContext
                    items={[
                      ...filteredFolders.map((f) => `folder-${f.id}`),
                      ...currentFolderFiles.map((f) => `file-${f.id}`),
                    ]}
                    strategy={verticalListSortingStrategy}
                  >
                    <div className="overflow-y-auto ">
                      {currentFolder === null
                        ? filteredFolders.map((folder) => (
                            <FilePickerFolderItem
                              key={`folder-${folder.id}`}
                              folder={folder}
                              onClick={() => handleFolderClick(folder.id)}
                              onSelect={() => handleFolderSelect(folder)}
                              isSelected={selectedFolderIds.has(folder.id)}
                              allFilesSelected={isAllFilesInFolderSelected(
                                folder
                              )}
                            />
                          ))
                        : currentFolderFiles.map((file) => (
                            <DraggableItem
                              key={`file-${file.id}`}
                              id={`file-${file.id}`}
                              type="file"
                              item={file}
                              onClick={() => handleFileClick(file)}
                              onSelect={(e: React.MouseEvent<HTMLDivElement>) =>
                                handleFileSelect(e, file)
                              }
                              isSelected={selectedFileIds.has(file.id)}
                            />
                          ))}
                      {/* Add uploading files visualization */}
                    </div>
                  </SortableContext>

                  <DragOverlay>
                    {activeId && activeSplit ? (
                      <DraggableItem
                        id={activeId}
                        type={activeId.startsWith("folder") ? "folder" : "file"}
                        item={
                          activeId.startsWith("folder")
                            ? folders.find(
                                (f) => f.id === parseInt(activeSplit, 10)
                              )!
                            : currentFolderFiles.find(
                                (f) => f.id === parseInt(activeSplit, 10)
                              )!
                        }
                        isSelected={
                          activeId.startsWith("folder")
                            ? selectedFolderIds.has(parseInt(activeSplit, 10))
                            : selectedFileIds.has(parseInt(activeSplit, 10))
                        }
                      />
                    ) : null}
                  </DragOverlay>
                </DndContext>
              </div>
            ) : folders.length > 0 ? (
              <div className="flex-grow overflow-y-auto px-4">
                <p className="text-text-subtle dark:text-neutral-400">
                  No folders found
                </p>
              </div>
            ) : (
              <div className="flex-grow flex-col overflow-y-auto px-4 flex items-start justify-start gap-y-2">
                <p className="text-sm text-muted-foreground dark:text-neutral-400">
                  No folders found
                </p>
                <a
                  href="/chat/my-documents?createFolder=true"
                  className="inline-flex items-center text-sm justify-center text-neutral-600 dark:text-neutral-400 hover:underline"
                >
                  <FolderIcon className="mr-2 h-4 w-4" />
                  Create folder in My Documents
                </a>
              </div>
            )}
          </div>
          <div
            className={`mobile:hidden overflow-y-auto w-full h-full flex flex-col ${
              isHoveringRight ? "bg-neutral-100 dark:bg-neutral-800/30" : ""
            }`}
            onDragEnter={() => setIsHoveringRight(true)}
            onDragLeave={() => setIsHoveringRight(false)}
          >
            <div className="px-5 h-full flex flex-col">
              {/* Top section: scrollable, takes remaining space */}
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-neutral-800 dark:text-neutral-100">
                  Selected Items
                </h3>
              </div>
              <div className="flex-1 min-h-0 overflow-y-auto">
                <SelectedItemsList
                  uploadingFiles={uploadingFiles}
                  setPresentingDocument={setPresentingDocument}
                  folders={selectedItems.folders}
                  files={selectedItems.files}
                  onRemoveFile={handleRemoveFile}
                  onRemoveFolder={handleRemoveFolder}
                />
              </div>

              {/* Bottom section: fixed height, doesn't flex */}
              <div className="flex-none py-2">
                <FileUploadSection
                  disabled={isUploadingFile || isCreatingFileFromLink}
                  onUpload={(files: File[]) => {
                    setIsUploadingFile(true);
                    setUploadStartTime(Date.now()); // Record start time

                    // Start the refresh interval to simulate progress
                    startRefreshInterval();

                    // Convert File[] to FileList for addUploadedFileToContext
                    const fileListArray = Array.from(files);
                    const fileList = new DataTransfer();
                    fileListArray.forEach((file) => fileList.items.add(file));

                    addUploadedFileToContext(fileList.files)
                      .then(() => refreshFolders())
                      .finally(() => {
                        setIsUploadingFile(false);
                      });
                  }}
                  onUrlUpload={async (url: string) => {
                    setIsCreatingFileFromLink(true);
                    setUploadStartTime(Date.now()); // Record start time

                    // Add URL to uploading files
                    setUploadingFiles((prev) => [
                      ...prev,
                      { name: url, progress: 0 },
                    ]);

                    // Start the refresh interval to simulate progress
                    startRefreshInterval();

                    try {
                      const response: FileResponse[] = await createFileFromLink(
                        url,
                        -1
                      );

                      if (response.length > 0) {
                        // Extract domain from URL to help with detection
                        const urlObj = new URL(url);

                        const createdFile = response[0];
                        if (createdFile !== undefined) {
                          addSelectedFile(createdFile);
                        }
                        // Make sure to remove the uploading file indicator when done
                        markFileComplete(url);
                      }

                      await refreshFolders();
                    } catch (e) {
                      console.error("Error creating file from link:", e);
                      // Also remove the uploading indicator on error
                      markFileComplete(url);
                    } finally {
                      setIsCreatingFileFromLink(false);
                    }
                  }}
                  isUploading={isUploadingFile || isCreatingFileFromLink}
                />
              </div>
            </div>
          </div>
        </div>
        <div className="px-5 pt-4 border-t border-neutral-200 dark:border-neutral-700">
          <div className="flex flex-col items-center justify-center py-2 space-y-4">
            <div className="flex items-center gap-3">
              <span className="text-sm text-neutral-600 dark:text-neutral-400">
                Selected context:
              </span>
              <TokenDisplay
                totalTokens={selectedItems.totalTokens}
                maxTokens={selectedModel.maxTokens}
                tokenPercentage={
                  (selectedItems.totalTokens / selectedModel.maxTokens) * 100
                }
                selectedModel={selectedModel}
              />
            </div>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <div>
                    <Button
                      type="button"
                      onClick={() =>
                        onSave(selectedItems.files, selectedItems.folders)
                      }
                      className="px-8 py-2 w-48"
                      disabled={
                        isUploadingFile ||
                        isCreatingFileFromLink ||
                        uploadingFiles.length > 0
                      }
                    >
                      {buttonContent || "Set Context"}
                    </Button>
                  </div>
                </TooltipTrigger>
                {(isUploadingFile ||
                  isCreatingFileFromLink ||
                  uploadingFiles.length > 0) && (
                  <TooltipContent>
                    <p>Please wait for all files to finish uploading</p>
                  </TooltipContent>
                )}
              </Tooltip>
            </TooltipProvider>
          </div>
        </div>
      </div>
    </Modal>
  );
};
