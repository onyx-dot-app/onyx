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
    ? "bg-blue-100 border-blue-300 shadow-sm"
    : "hover:bg-gray-100";

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

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      className={`flex items-center p-2 cursor-pointer rounded-md ${
        isDragging ? "bg-gray-200" : ""
      } ${selectedClassName}`}
      onClick={onClick}
    >
      <FileIcon className="mr-2 text-gray-500" />
      <span className="text-sm font-medium">{(item as FileResponse).name}</span>
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
      ? "from-blue-100 to-blue-50 border-blue-300 shadow-sm dark:from-blue-900 dark:to-blue-800 dark:border-blue-700"
      : "from-[#f2f0e8]/80 to-[#F7F6F0] hover:from-[#f2f0e8] hover:to-[#F7F6F0] dark:from-neutral-800 dark:to-neutral-900 dark:hover:from-neutral-700 dark:hover:to-neutral-800";

  return (
    <div
      className={`${selectedClassName} border-0.5 border-border hover:border-border-200 dark:border-neutral-700 dark:hover:border-neutral-600 text-md group relative flex cursor-pointer flex-col overflow-x-hidden text-ellipsis rounded-xl bg-gradient-to-b py-4 pl-5 pr-4 transition-all ease-in-out hover:shadow-sm active:scale-[0.99]`}
      onClick={onClick}
    >
      <div className="flex flex-col flex-1">
        <div className="font-tiempos flex items-center justify-between">
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="text-truncate text-text-dark dark:text-neutral-200 inline-block max-w-md">
                  {folder.name}
                </span>
              </TooltipTrigger>
              <TooltipContent>
                <p>{folder.name}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <Button
            variant="ghost"
            size="sm"
            className={`ml-2 ${
              isSelected || allFilesSelected
                ? "text-blue-500 dark:text-blue-400"
                : "text-gray-500 dark:text-neutral-400"
            }`}
            onClick={(e) => {
              e.stopPropagation();
              onSelect();
            }}
          >
            {isSelected || allFilesSelected ? (
              <X size={16} />
            ) : (
              <PlusIcon size={16} />
            )}
          </Button>
        </div>
        {folder.description && (
          <div className="text-text-400 dark:text-neutral-400 mt-1 line-clamp-2 text-xs">
            {folder.description}
          </div>
        )}
      </div>
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

  // Initialize selectedFileIds and selectedFolderIds based on props
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

  const handleSave = () => {
    // onSave(selectedItems);
    onClose();
  };

  const handleFolderClick = (folderId: number) => {
    console.log(`Folder clicked: ${folderId}`);
    setCurrentFolder(folderId);
    const clickedFolder = folders.find((f) => f.id === folderId);
    if (clickedFolder) {
      console.log(`Found folder: ${clickedFolder.name}`);
      setCurrentFolderFiles(clickedFolder.files || []);
    } else {
      console.log(`Folder not found for id: ${folderId}`);
      setCurrentFolderFiles([]);
    }
  };

  const handleFileSelect = (file: FileResponse) => {
    console.log(`File select triggered for file: ${file.id} - ${file.name}`);

    setSelectedFileIds((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(file.id)) {
        console.log(`Removing file ${file.id} from selection`);
        newSet.delete(file.id);
        removeSelectedFile(file);
      } else {
        console.log(`Adding file ${file.id} to selection`);
        newSet.add(file.id);
        addSelectedFile(file);
      }
      return newSet;
    });

    // Check if the file's folder should be unselected
    if (file.folder_id) {
      console.log(
        `Checking folder ${file.folder_id} status for file ${file.id}`
      );

      setSelectedFolderIds((prev) => {
        const newSet = new Set(prev);
        if (newSet.has(file.folder_id!)) {
          console.log(`Folder ${file.folder_id} is currently selected`);

          const folder = folders.find((f) => f.id === file.folder_id);
          if (folder) {
            const allFilesSelected = folder.files.every(
              (f) => selectedFileIds.has(f.id) || f.id === file.id
            );
            console.log(
              `All files in folder ${folder.id} selected: ${allFilesSelected}`
            );

            if (!allFilesSelected) {
              console.log(
                `Unselecting folder ${folder.id} as not all files are selected`
              );
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
    const items: { folders: FolderResponse[]; files: FileResponse[] } = {
      folders: [],
      files: [],
    };

    // First handle selected files that are not in any folder
    selectedFiles.forEach((file) => {
      if (!folders.some((f) => f.id === file.folder_id)) {
        items.files.push(file);
      }
    });

    // Then handle folders and their files
    folders.forEach((folder) => {
      // For the recent folder, only include it if explicitly selected
      if (isRecentFolder(folder.id)) {
        if (selectedFolderIds.has(folder.id)) {
          items.folders.push(folder);
        } else {
          // For the recent folder, include individually selected files
          const selectedFilesInFolder = folder.files.filter((file) =>
            selectedFileIds.has(file.id)
          );
          items.files.push(...selectedFilesInFolder);
        }
        return;
      }

      // For regular folders
      if (selectedFolderIds.has(folder.id)) {
        items.folders.push(folder);
      } else {
        const selectedFilesInFolder = folder.files.filter((file) =>
          selectedFileIds.has(file.id)
        );
        if (
          selectedFilesInFolder.length === folder.files.length &&
          folder.files.length > 0
        ) {
          items.folders.push(folder);
        } else {
          items.files.push(...selectedFilesInFolder);
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
    console.log("File upload started");
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
    console.log("Drag started:", event);
    setActiveId(event.active.id.toString());
  };

  const handleDragMove = (event: DragMoveEvent) => {
    console.log("Drag move:", event);
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    console.log("Drag ended:", { active, over, isHoveringRight });

    if (active.id !== over?.id && isHoveringRight) {
      const activeType = active.id.toString().startsWith("folder")
        ? "folders"
        : "files";
      const activeId = parseInt(active.id.toString().split("-")[1], 10);

      console.log(`Added ${activeType} with id ${activeId} to selected items`);
    } else {
      console.log("Item not added to selection");
    }

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
    return (
      folder.name.toLowerCase().includes(searchQuery.toLowerCase()) &&
      folder.files &&
      folder.files.length > 0
    );
  });

  const renderNavigation = () => {
    if (currentFolder !== null) {
      return (
        <div
          className="flex items-center mb-2 text-sm text-gray-600 cursor-pointer hover:text-gray-800"
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
      console.log("Removing recent folder");

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
      <div className="grid h-full grid-cols-2 overflow-y-hidden w-full divide-x divide-gray-200 dark:divide-neutral-700">
        <div className="w-full h-full pb-4 overflow-y-auto">
          <div className="sticky flex flex-col gap-y-2 border-b bg-background dark:bg-transparent z-[1000] top-0 mb-2 flex gap-x-2 w-full pr-4">
            <div className="w-full relative">
              <input
                type="text"
                placeholder="Search groups..."
                className="w-full pl-10 pr-4 py-2 border border-gray-300 dark:border-neutral-600 rounded-md focus:border-transparent dark:bg-neutral-800 dark:text-neutral-100"
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
                  <div className="overflow-y-auto space-y-3">
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
                href="/chat/my-documents"
                className="inline-flex items-center text-sm justify-center text-blue-600 dark:text-blue-400 hover:underline"
              >
                <FolderIcon className="mr-2 h-4 w-4" />
                Create folder in My Documents
              </a>
            </div>
          )}
        </div>
        <div
          className={`w-full h-full px-4 pb-4 flex flex-col h-[450px] ${
            isHoveringRight ? "bg-blue-50 dark:bg-blue-900/20" : ""
          }`}
          onDragEnter={() => setIsHoveringRight(true)}
          onDragLeave={() => setIsHoveringRight(false)}
        >
          <div className="shrink flex h-full overflow-y-auto mb-1">
            <SelectedItemsList
              folders={selectedItems.folders}
              files={selectedItems.files}
              onRemoveFile={handleRemoveFile}
              onRemoveFolder={handleRemoveFolder}
            />
          </div>

          <div className="flex flex-col">
            <div className="p-4 flex-none border rounded-lg bg-neutral-50 dark:bg-neutral-800 dark:border-neutral-700">
              <label
                htmlFor="file-upload"
                className="cursor-pointer flex items-center justify-center space-x-2"
              >
                <UploadIcon className="w-5 h-5 text-gray-600 dark:text-neutral-300" />
                <span className="text-sm font-medium text-gray-700 dark:text-neutral-200">
                  {isUploadingFile ? "Uploading..." : "Upload files"}
                </span>
              </label>
              <input
                id="file-upload"
                type="file"
                multiple
                className="hidden"
                onChange={handleFileUpload}
                disabled={isUploadingFile}
              />
            </div>

            <Separator className="my-2 dark:bg-neutral-700" />

            <div className="flex flex-col">
              <div className="flex flex-col gap-y-2">
                <p className="text-sm text-text-subtle dark:text-neutral-400">
                  Add links to the context
                </p>
              </div>
              <form
                className="flex gap-x-4 mt-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  handleCreateFileFromLink();
                }}
              >
                <div className="w-full gap-x-2 flex">
                  <input
                    type="text"
                    value={linkUrl}
                    onChange={(e) => setLinkUrl(e.target.value)}
                    placeholder="Enter URL"
                    className="flex-grow !text-sm mr-2 px-2 py-1 border border-gray-300 dark:border-neutral-600 rounded dark:bg-neutral-800 dark:text-neutral-100"
                  />
                  <Button
                    variant="default"
                    className="!text-sm"
                    size="xs"
                    onClick={handleCreateFileFromLink}
                    disabled={isCreatingFileFromLink || !linkUrl}
                  >
                    {isCreatingFileFromLink ? "Creating..." : "Create"}
                  </Button>
                </div>
              </form>
            </div>
          </div>
        </div>
      </div>
    </Modal>
  );
};
