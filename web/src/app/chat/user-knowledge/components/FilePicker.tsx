import React, { useState, useEffect, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/Modal";
import {
  Grid,
  List,
  UploadIcon,
  FolderIcon,
  FileIcon,
  PlusIcon,
  Router,
  X,
} from "lucide-react";
import { ContextUsage } from "./ContextUsage";
import { SelectedItemsList } from "./SelectedItemsList";
import { Separator } from "@/components/ui/separator";
import {
  useDocumentsContext,
  FolderResponse,
  FileResponse,
  FileUploadResponse,
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
import { useRouter } from "next/navigation";
import { usePopup } from "@/components/admin/connectors/Popup";
import { getTimeAgoString } from "@/lib/dateUtils";
import { FileOptionIcon } from "@/components/icons/icons";
import { FileUploadSection } from "../[id]/components/upload/FileUploadSection";

const DraggableItem: React.FC<{
  id: string;
  type: "folder" | "file";
  item: FolderResponse | FileResponse;
  onClick?: () => void;
  isSelected: boolean;
}> = ({ id, type, item, onClick, isSelected }) => {
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
    ? "bg-[#f2f0e8]/50 dark:bg-[#1a1a1a]/50"
    : "hover:bg-[#f2f0e8]/50 dark:hover:bg-[#1a1a1a]/50";

  if (type === "folder") {
    return (
      <div ref={setNodeRef} style={style} {...attributes} {...listeners}>
        <FilePickerFolderItem
          folder={item as FolderResponse}
          onClick={onClick || (() => {})}
          onSelect={() => {}}
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
      className={`group relative flex cursor-pointer items-center border-b border-border dark:border-border-200 ${selectedClassName} py-2 px-3 transition-all ease-in-out`}
      onClick={onClick}
    >
      <div className="flex items-center flex-1 min-w-0">
        <div className="flex text-sm items-center gap-3 w-[80%] mr-2 min-w-0">
          <FileOptionIcon className="h-4 w-4 text-orange-400 dark:text-blue-300 shrink-0" />
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="truncate text-text-dark dark:text-text-dark">
                  {file.name}
                </span>
              </TooltipTrigger>
              <TooltipContent>
                <p>{file.name}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>

        <div className="w-[20%] text-sm text-text-400 dark:text-neutral-400">
          {file.lastModified && getTimeAgoString(new Date(file.lastModified))}
        </div>
      </div>
    </div>
  );
};

const FilePickerFolderItem: React.FC<{
  folder: FolderResponse;
  onClick: () => void;
  onSelect: () => void;
  isSelected: boolean;
  allFilesSelected: boolean;
}> = ({ folder, onClick, onSelect, isSelected, allFilesSelected }) => {
  const selectedClassName =
    isSelected || allFilesSelected
      ? "bg-[#f2f0e8]/50 dark:bg-[#1a1a1a]/50"
      : "hover:bg-[#f2f0e8]/50 dark:hover:bg-[#1a1a1a]/50";

  return (
    <div
      className={`group relative flex cursor-pointer items-center border-b border-border dark:border-border-200 ${selectedClassName} py-2 px-3 transition-all ease-in-out`}
      onClick={onClick}
    >
      <div className="flex items-center flex-1 min-w-0">
        <div className="flex  text-sm items-center gap-3 w-[60%] min-w-0">
          <FolderIcon className="h-5 w-5 text-orange-400 dark:text-orange-300 shrink-0 fill-orange-400 dark:fill-orange-300" />
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="truncate text-text-dark dark:text-text-dark">
                  {folder.name}
                </span>
              </TooltipTrigger>
              <TooltipContent>
                <p>{folder.name}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>

        <div className="w-[40%] pl-3 text-sm text-text-400 dark:text-neutral-400">
          {folder.files.length} {folder.files.length === 1 ? "file" : "files"}
        </div>
      </div>

      <Button
        variant="ghost"
        size="sm"
        className="ml-2 h-6 w-6 p-0 rounded-full opacity-80 hover:opacity-100 text-neutral-500 dark:text-neutral-400 hover:bg-neutral-200 dark:hover:bg-neutral-700"
        onClick={(e) => {
          e.stopPropagation();
          onSelect();
        }}
      >
        {isSelected || allFilesSelected ? (
          <X size={14} />
        ) : (
          <PlusIcon size={14} />
        )}
      </Button>
    </div>
  );
};

export interface FilePickerModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: () => void;
  title: string;
  buttonContent: string;
}

// Define a model descriptor interface
interface LLMModelDescriptor {
  modelName: string;
  maxTokens: number;
}

export const FilePickerModal: React.FC<FilePickerModalProps> = ({
  isOpen,
  onClose,
  onSave,
  title,
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

  const router = useRouter();
  const [uploadedFiles, setUploadedFiles] = useState<File[]>([]);
  const [linkUrl, setLinkUrl] = useState("");
  const [isCreatingFileFromLink, setIsCreatingFileFromLink] = useState(false);
  const [isUploadingFile, setIsUploadingFile] = useState(false);

  const [view, setView] = useState<"grid" | "list">("list");
  const [searchQuery, setSearchQuery] = useState("");
  const [currentFolderFiles, setCurrentFolderFiles] = useState<FileResponse[]>(
    []
  );
  const [activeId, setActiveId] = useState<string | null>(null);
  const [isHoveringRight, setIsHoveringRight] = useState(false);

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
  const modelDescriptors: LLMModelDescriptor[] = [
    { modelName: "Claude 3 Opus", maxTokens: 200000 },
    { modelName: "Claude 3 Sonnet", maxTokens: 180000 },
    { modelName: "GPT-4", maxTokens: 128000 },
  ];

  const [selectedModel, setSelectedModel] = useState(modelDescriptors[0]);

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
    if (isOpen) {
      refreshFolders();
    }
  }, [isOpen, refreshFolders]);

  useEffect(() => {
    if (currentFolder) {
      const folder = folders.find((f) => f.id === currentFolder);
      setCurrentFolderFiles(folder?.files || []);
    } else {
      setCurrentFolderFiles([]);
    }
  }, [currentFolder, folders]);

  useEffect(() => {
    if (searchQuery) {
      setCurrentFolder(null);
    }
  }, [searchQuery]);

  const handleFolderClick = (folderId: number) => {
    setCurrentFolder(folderId);
    const clickedFolder = folders.find((f) => f.id === folderId);
    if (clickedFolder) {
      setCurrentFolderFiles(clickedFolder.files || []);
    } else {
      setCurrentFolderFiles([]);
    }
  };

  const handleFileSelect = (file: FileResponse) => {
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

  const addUploadedFileToContext = async (files: FileList) => {
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      const formData = new FormData();
      formData.append("files", file);
      const response: FileUploadResponse = await uploadFile(formData, null);

      if (response.file_paths && response.file_paths.length > 0) {
        const uploadedFile: FileResponse = {
          id: Date.now(),
          name: file.name,
          document_id: response.file_paths[0],
          folder_id: null,
          size: file.size,
          type: file.type,
          lastModified: new Date().toISOString(),
          token_count: 0,
        };
        addSelectedFile(uploadedFile);
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

  const handleCreateFileFromLink = async () => {
    if (!linkUrl) return;
    setIsCreatingFileFromLink(true);
    try {
      const response: FileUploadResponse = await createFileFromLink(
        linkUrl,
        currentFolder
      );
      setLinkUrl("");

      if (response.file_paths && response.file_paths.length > 0) {
        const createdFile: FileResponse = {
          id: Date.now(),
          name: new URL(linkUrl).hostname,
          document_id: response.file_paths[0],
          folder_id: currentFolder || null,
          size: 0,
          type: "link",
          lastModified: new Date().toISOString(),
          token_count: 0,
        };
        addSelectedFile(createdFile);
      }

      await refreshFolders();
    } catch (error) {
      console.error("Error creating file from link:", error);
    } finally {
      setIsCreatingFileFromLink(false);
    }
  };

  const filteredFolders = folders.filter(function (folder) {
    return folder.name.toLowerCase().includes(searchQuery.toLowerCase());
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
          Back to Folders
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
      hideDividerForTitle
      onOutsideClick={onClose}
      className="max-w-4xl flex flex-col w-full !overflow-hidden h-[70vh]"
      title={title}
    >
      <div className="flex flex-col h-full">
        <div className="grid flex-1 overflow-y-hidden w-full divide-x divide-neutral-200 dark:divide-neutral-700 grid-cols-2">
          <div className="w-full h-full pb-4 overflow-y-auto">
            <div className="sticky flex flex-col gap-y-2  bg-background dark:bg-transparent z-[1000] top-0 mb-2 flex gap-x-2 w-full pr-4">
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
              <div className="flex-grow pr-4">
                <div className="flex items-center border-b border-border dark:border-border-200 py-2 px-3 text-sm font-medium text-text-400 dark:text-neutral-400">
                  <div className="flex items-center gap-3 w-[80%]  min-w-0">
                    <span>Name</span>
                  </div>
                  <div className="w-[20%] ">
                    {currentFolder === null ? "Files" : "Created"}
                  </div>
                </div>

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
                              onClick={() => handleFileSelect(file)}
                              isSelected={selectedFileIds.has(file.id)}
                            />
                          ))}
                    </div>
                  </SortableContext>

                  <DragOverlay>
                    {activeId ? (
                      <DraggableItem
                        id={activeId}
                        type={activeId.startsWith("folder") ? "folder" : "file"}
                        item={
                          activeId.startsWith("folder")
                            ? folders.find(
                                (f) =>
                                  f.id === parseInt(activeId.split("-")[1], 10)
                              )!
                            : currentFolderFiles.find(
                                (f) =>
                                  f.id === parseInt(activeId.split("-")[1], 10)
                              )!
                        }
                        isSelected={
                          activeId.startsWith("folder")
                            ? selectedFolderIds.has(
                                parseInt(activeId.split("-")[1], 10)
                              )
                            : selectedFileIds.has(
                                parseInt(activeId.split("-")[1], 10)
                              )
                        }
                      />
                    ) : null}
                  </DragOverlay>
                </DndContext>
              </div>
            ) : folders.length > 0 ? (
              <div className="flex-grow overflow-y-auto px-4">
                <p className="text-text-subtle dark:text-neutral-400">
                  No groups found
                </p>
              </div>
            ) : (
              <div className="flex-grow flex-col overflow-y-auto px-4 flex items-start justify-start gap-y-2">
                <p className="text-sm text-muted-foreground dark:text-neutral-400">
                  No groups found
                </p>
                <a
                  href="/chat/user-knowledge"
                  className="inline-flex items-center text-sm justify-center text-neutral-600 dark:text-neutral-400 hover:underline"
                >
                  <FolderIcon className="mr-2 h-4 w-4" />
                  Create folder in My Documents
                </a>
              </div>
            )}
          </div>
          <div
            className={`w-full h-full flex flex-col ${
              isHoveringRight ? "bg-neutral-100 dark:bg-neutral-800/30" : ""
            }`}
            onDragEnter={() => setIsHoveringRight(true)}
            onDragLeave={() => setIsHoveringRight(false)}
          >
            <div className="px-5 pb-5 flex-1 flex flex-col">
              <div className="shrink flex h-full overflow-y-auto mb-3">
                <SelectedItemsList
                  folders={selectedItems.folders}
                  files={selectedItems.files}
                  onRemoveFile={handleRemoveFile}
                  onRemoveFolder={handleRemoveFolder}
                />
              </div>

              <div className="flex flex-col space-y-3">
                <Separator className="dark:bg-neutral-700" />

                <div className="flex flex-col space-y-2">
                  <FileUploadSection
                    disabled={isUploadingFile || isCreatingFileFromLink}
                    onUpload={(files: File[]) => {
                      setIsUploadingFile(true);
                      // Convert File[] to FileList for addUploadedFileToContext
                      const dataTransfer = new DataTransfer();
                      files.forEach((file) => dataTransfer.items.add(file));
                      const fileList = dataTransfer.files;

                      addUploadedFileToContext(fileList)
                        .then(() => refreshFolders())
                        .finally(() => setIsUploadingFile(false));
                    }}
                    onUrlUpload={async (url: string) => {
                      setIsCreatingFileFromLink(true);
                      try {
                        const response: FileUploadResponse =
                          await createFileFromLink(url, currentFolder);

                        if (
                          response.file_paths &&
                          response.file_paths.length > 0
                        ) {
                          const createdFile: FileResponse = {
                            id: Date.now(),
                            name: new URL(url).hostname,
                            document_id: response.file_paths[0],
                            folder_id: currentFolder || null,
                            size: 0,
                            type: "link",
                            lastModified: new Date().toISOString(),
                            token_count: 0,
                          };
                          addSelectedFile(createdFile);
                        }

                        await refreshFolders();
                      } catch (error) {
                        console.error("Error creating file from link:", error);
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
        </div>
        <div className="px-5 py-4 border-t border-neutral-200 dark:border-neutral-700">
          <div className="flex flex-col items-center justify-center space-y-4">
            <div className="flex items-center gap-3">
              <span className="text-sm text-neutral-600 dark:text-neutral-400">
                Selected context:
              </span>
              <div className="flex items-center gap-2 px-3 py-1.5 bg-neutral-100 dark:bg-neutral-800 rounded-lg shadow-sm">
                <div className="h-2 w-20 bg-neutral-200 dark:bg-neutral-700 rounded-full overflow-hidden">
                  <div
                    className={`h-full transition-all duration-300 ${
                      (selectedItems.totalTokens / selectedModel.maxTokens) *
                        100 >
                      75
                        ? "bg-red-500"
                        : (selectedItems.totalTokens /
                              selectedModel.maxTokens) *
                              100 >
                            50
                          ? "bg-amber-500"
                          : "bg-emerald-500"
                    }`}
                    style={{
                      width: `${Math.min(
                        (selectedItems.totalTokens / selectedModel.maxTokens) *
                          100,
                        100
                      )}%`,
                    }}
                  />
                </div>
                <span className="text-xs font-medium text-neutral-700 dark:text-neutral-300">
                  {selectedItems.totalTokens.toLocaleString()} /{" "}
                  {selectedModel.maxTokens.toLocaleString()} tokens
                </span>
              </div>
            </div>
            <Button onClick={onSave} className="px-8 py-2 w-48">
              Set Context
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
};
