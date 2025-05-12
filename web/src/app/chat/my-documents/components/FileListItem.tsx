import React, { useState, useEffect, useCallback } from "react";
import { Checkbox } from "@/components/ui/checkbox";
import { MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  FileResponse,
  FileStatus,
  FolderResponse,
  useDocumentsContext,
} from "../DocumentsContext";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  FiAlertTriangle,
  FiDownload,
  FiEdit,
  FiRefreshCw,
  FiTrash,
  FiTrash2,
} from "react-icons/fi";
import { getFormattedDateTime } from "@/lib/dateUtils";
import { getFileIconFromFileNameAndLink } from "@/lib/assistantIconUtils";
import { AnimatedDots } from "../[id]/components/DocumentList";
import { FolderMoveIcon } from "@/components/icons/icons";
import { truncateString } from "@/lib/utils";
import { usePopup } from "@/components/admin/connectors/Popup";

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

  status: FileStatus;
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
  status,
}) => {
  const { setPopup, popup } = usePopup();
  const [showMoveOptions, setShowMoveOptions] = useState(false);
  const [indexingStatus, setIndexingStatus] = useState<boolean | null>(null);
  const [isPopoverOpen, setIsPopoverOpen] = useState(false);
  const { getFilesIndexingStatus, refreshFolderDetails } =
    useDocumentsContext();

  useEffect(() => {
    const checkStatus = async () => {
      const status = await getFilesIndexingStatus([file.id]);
      setIndexingStatus(status[file.id]);
    };

    checkStatus();
    const interval = setInterval(() => {
      refreshFolderDetails();
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
  const FailureWithPopover = useCallback(() => {
    return (
      <Popover open={isPopoverOpen} onOpenChange={setIsPopoverOpen}>
        <PopoverTrigger onClick={(e) => e.stopPropagation()} asChild>
          <div className="text-red-500 cursor-pointer">
            <FiAlertTriangle className="h-4 w-4" />
          </div>
        </PopoverTrigger>
        <PopoverContent className="w-56 p-3 shadow-lg rounded-md border border-neutral-200 dark:border-neutral-800">
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
              <p className="text-xs font-medium text-red-500">
                Indexing failed.
                <br />
                You can attempt a reindex to continue using this file, or delete
                the file.
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
                  setIsPopoverOpen(false);
                  fetch(`/api/user/file/reindex`, {
                    method: "POST",
                    headers: {
                      "Content-Type": "application/json",
                    },
                    body: JSON.stringify({ file_id: file.id }),
                  })
                    .then((response) => {
                      if (!response.ok) {
                        throw new Error("Failed to reindex file");
                      }
                      setIndexingStatus(false);
                      refreshFolderDetails();
                      setPopup({
                        type: "success",
                        message: "Reindexing will start shortly.",
                      });
                    })
                    .catch((error) => {
                      console.error("Error reindexing file:", error);
                      setPopup({
                        type: "error",
                        message: "Failed to reindex file",
                      });
                    });
                }}
              >
                <FiRefreshCw className="mr-2 h-3.5 w-3.5" />
                Reindex
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="w-full justify-start text-sm font-medium text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 hover:text-red-600 transition-colors"
                onClick={(e) => {
                  e.stopPropagation();
                  setIsPopoverOpen(false);
                  handleDelete();
                }}
              >
                <FiTrash2 className="mr-2 h-3.5 w-3.5" />
                Delete
              </Button>
            </div>
          </div>
        </PopoverContent>
      </Popover>
    );
  }, [
    file.id,
    handleDelete,
    isPopoverOpen,
    refreshFolderDetails,
    setIndexingStatus,
    setIsPopoverOpen,
    setPopup,
  ]);

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
          {status === FileStatus.FAILED ? (
            <FailureWithPopover />
          ) : (
            getFileIconFromFileNameAndLink(file.name, file.link_url)
          )}
          {file.name.length > 50 ? (
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="truncate text-sm text-text-dark dark:text-text-dark">
                    {truncateString(file.name, 50)}
                  </span>
                </TooltipTrigger>
                <TooltipContent>
                  <p>{file.name}</p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          ) : (
            <span className="truncate text-sm text-text-dark dark:text-text-dark">
              {file.name}
            </span>
          )}
        </div>

        <div className="w-[30%] text-sm text-text-400 dark:text-neutral-400">
          {file.created_at &&
            getFormattedDateTime(
              new Date(new Date(file.created_at).getTime() - 8 * 60 * 60 * 1000)
            )}
        </div>

        <div className="w-[30%] text-sm text-text-400 dark:text-neutral-400">
          {file.status == FileStatus.INDEXING ||
          file.status == FileStatus.REINDEXING ? (
            <>
              N/A, indexing
              <AnimatedDots />
            </>
          ) : file.status == FileStatus.FAILED ? (
            <>Failed</>
          ) : file.token_count !== undefined ? (
            `${file.token_count?.toLocaleString()} tokens`
          ) : (
            "N/A"
          )}
        </div>
      </div>
      {popup}

      <div className="action-menu" onClick={(e) => e.stopPropagation()}>
        <Popover
          onOpenChange={(open) => {
            if (!open) {
              setShowMoveOptions(false);
            }
          }}
        >
          <PopoverTrigger asChild>
            <Button
              variant="ghost"
              className="group-hover:visible mobile:visible invisible h-8 w-8 p-0"
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
                  <FolderMoveIcon size={16} className="h-4 w-4" />
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
                  <h3 className="text-sm  px-2 font-semibold">Move to </h3>
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
