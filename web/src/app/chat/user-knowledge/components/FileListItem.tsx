import React, { useState, useEffect } from "react";
import { Checkbox } from "@/components/ui/checkbox";
import { File, File as FileIcon, Loader, MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  FileResponse,
  FolderResponse,
  useDocumentsContext,
} from "../DocumentsContext";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { FiArrowDown, FiDownload, FiEdit, FiTrash } from "react-icons/fi";
import { getTimeAgoString } from "@/lib/dateUtils";
import { FileOptionIcon } from "@/components/icons/icons";

interface FileListItemProps {
  file: FileResponse;
  isSelected?: boolean;
  onSelect?: (file: FileResponse) => void;
  view: "grid" | "list";
  onRename: (
    itemId: number,
    currentName: string,
    isFolder: boolean
  ) => Promise<void>;
  onDelete: (itemId: number, isFolder: boolean, itemName: string) => void;
  onDownload: (documentId: string) => Promise<void>;
  onMove: (fileId: number, targetFolderId: number) => Promise<void>;
  folders: FolderResponse[];
  isIndexed: boolean;
}

export const FileListItem: React.FC<FileListItemProps> = ({
  file,
  isSelected,
  onSelect,
  onRename,
  onDelete,
  onDownload,
  onMove,
  folders,
  isIndexed,
}) => {
  const [showMoveOptions, setShowMoveOptions] = useState(false);
  const [indexingStatus, setIndexingStatus] = useState<boolean | null>(null);
  const { getFilesIndexingStatus } = useDocumentsContext();

  useEffect(() => {
    const checkStatus = async () => {
      const status = await getFilesIndexingStatus([file.id]);
      setIndexingStatus(status[file.id]);
    };

    checkStatus();
    const interval = setInterval(() => {
      if (indexingStatus === false) {
        checkStatus();
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [file.id, indexingStatus, getFilesIndexingStatus]);

  const handleDelete = () => {
    onDelete(file.id, false, file.name);
  };

  const handleMove = (targetFolderId: number) => {
    onMove(file.id, targetFolderId);
    setShowMoveOptions(false);
  };

  return (
    <div
      className="group relative flex cursor-pointer items-center border-b border-border dark:border-border-200 hover:bg-[#f2f0e8]/50 dark:hover:bg-[#1a1a1a]/50 py-3 px-4 transition-all ease-in-out"
      onClick={(e) => {
        if (!(e.target as HTMLElement).closest(".action-menu")) {
          onSelect && onSelect(file);
        }
      }}
    >
      <div className="flex items-center flex-1 min-w-0">
        <div className="flex items-center gap-3 w-[40%] min-w-0">
          {isSelected !== undefined && (
            <Checkbox checked={isSelected} className="mr-2 shrink-0" />
          )}
          <FileOptionIcon className="h-4 w-4 text-orange-400 dark:text-blue-300 shrink-0" />
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="truncate text-sm text-text-dark dark:text-text-dark">
                  {file.name}
                </span>
              </TooltipTrigger>
              <TooltipContent>
                <p>{file.name}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          {indexingStatus === false && (
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger>
                  <Loader className="h-4 w-4 animate-spin text-amber-500 shrink-0" />
                </TooltipTrigger>
                <TooltipContent>
                  File is being indexed. Search might not include all content
                  yet.
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          )}
        </div>

        <div className="w-[30%] text-sm text-text-400 dark:text-neutral-400">
          {file.created_at && getTimeAgoString(new Date(file.created_at))}
        </div>

        <div className="w-[30%] text-sm text-text-400 dark:text-neutral-400">
          {file.token_count
            ? `${file.token_count.toLocaleString()} tokens`
            : "-"}
        </div>
      </div>

      <div className="action-menu" onClick={(e) => e.stopPropagation()}>
        <Popover>
          <PopoverTrigger asChild>
            <Button
              variant="ghost"
              className="group-hover:visible invisible h-8 w-8 p-0"
            >
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </PopoverTrigger>
          <PopoverContent
            className={`!p-0 ${showMoveOptions ? "w-52" : "w-40"}`}
          >
            {!showMoveOptions ? (
              <div className="space-y-0">
                <Button variant="menu" onClick={() => setShowMoveOptions(true)}>
                  <FiArrowDown className="h-4 w-4" />
                  Move
                </Button>
                <Button
                  variant="menu"
                  onClick={() => onRename(file.id, file.name, false)}
                >
                  <FiEdit className="h-4 w-4" />
                  Rename
                </Button>
                <Button variant="menu" onClick={handleDelete}>
                  <FiTrash className="h-4 w-4" />
                  Delete
                </Button>
                <Button
                  variant="menu"
                  onClick={() => onDownload(file.document_id)}
                >
                  <FiDownload className="h-4 w-4" />
                  Download
                </Button>
              </div>
            ) : (
              <div className="p-2 text-text-dark space-y-2">
                <div className="flex items-center space-x-2 mb-4">
                  <Button
                    variant="ghost"
                    onClick={() => setShowMoveOptions(false)}
                    className="h-8 w-8 p-0"
                  >
                    <FiArrowDown className="h-4 w-4" />
                  </Button>
                  <h3 className="text-sm font-medium">Move to folder</h3>
                </div>
                <div className="max-h-60 default-scrollbar overflow-y-auto pr-2">
                  <div className="space-y-1">
                    {folders
                      .filter(
                        (folder) =>
                          folder.id !== -1 && folder.id !== file.folder_id
                      )
                      .map((folder) => (
                        <Button
                          key={folder.id}
                          variant="ghost"
                          onClick={() => handleMove(folder.id)}
                          className="w-full justify-start text-sm py-2 px-3"
                        >
                          {folder.name}
                        </Button>
                      ))}
                    {folders.filter(
                      (folder) =>
                        folder.id !== -1 && folder.id !== file.folder_id
                    ).length === 0 && (
                      <div className="text-sm text-gray-500 px-2 text-center">
                        No folders available to move this file to.
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </PopoverContent>
        </Popover>
      </div>
    </div>
  );
};

export const SkeletonFileListItem: React.FC<{ view: "grid" | "list" }> = () => {
  return (
    <div className="group relative flex items-center border-b border-border dark:border-border-200 py-3 px-4">
      <div className="flex items-center flex-1 min-w-0">
        <div className="flex items-center gap-3 w-[40%]">
          <div className="h-5 w-5 bg-neutral-200 dark:bg-neutral-700 rounded animate-pulse" />
          <div className="h-4 w-48 bg-neutral-200 dark:bg-neutral-700 rounded animate-pulse" />
        </div>
        <div className="w-[30%]">
          <div className="h-4 w-24 bg-neutral-200 dark:bg-neutral-700 rounded animate-pulse" />
        </div>
        <div className="w-[30%]">
          <div className="h-4 w-24 bg-neutral-200 dark:bg-neutral-700 rounded animate-pulse" />
        </div>
      </div>
    </div>
  );
};
