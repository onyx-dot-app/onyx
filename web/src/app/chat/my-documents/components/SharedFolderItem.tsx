import React, { useState } from "react";
import { FolderIcon, MoreHorizontal } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { getFormattedDateTime } from "@/lib/dateUtils";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { FiTrash } from "react-icons/fi";
import { DeleteEntityModal } from "@/components/DeleteEntityModal";
import { truncateString } from "@/lib/utils";

interface SharedFolderItemProps {
  folder: {
    id: number;
    name: string;
    tokens?: number;
  };
  onClick: (folderId: number) => void;
  description?: string;
  lastUpdated?: string;
  onDelete: () => void;
}

export const SharedFolderItem: React.FC<SharedFolderItemProps> = ({
  folder,
  onClick,
  description,
  lastUpdated,
  onDelete,
}) => {
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);

  const handleDeleteClick = () => {
    setIsDeleteModalOpen(true);
  };

  return (
    <>
      <div
        className="group relative flex cursor-pointer items-center border-b border-border dark:border-border-200 hover:bg-[#f2f0e8]/50 dark:hover:bg-[#1a1a1a]/50 py-3 px-4 transition-all ease-in-out"
        onClick={(e) => {
          if (!(e.target as HTMLElement).closest(".action-menu")) {
            e.preventDefault();
            onClick(folder.id);
          }
        }}
      >
        <div className="flex items-center flex-1 min-w-0">
          <div className="flex items-center gap-3 w-[40%]">
            <FolderIcon className="h-5 w-5 text-black dark:text-black shrink-0 fill-black dark:fill-black" />
            {folder.name.length > 50 ? (
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="truncate text-text-dark dark:text-text-dark">
                      {truncateString(folder.name, 60)}
                    </span>
                  </TooltipTrigger>
                  <TooltipContent side="bottom">
                    <p>{folder.name}</p>
                    {description && (
                      <p className="text-xs text-neutral-500">{description}</p>
                    )}
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            ) : (
              <span className="truncate text-text-dark dark:text-text-dark">
                {folder.name}
              </span>
            )}
          </div>

          <div className="w-[30%] text-sm text-text-400 dark:text-neutral-400">
            {lastUpdated && getFormattedDateTime(new Date(lastUpdated))}
          </div>

          <div className="w-[30%] text-sm text-text-400 dark:text-neutral-400">
            {folder.tokens !== undefined
              ? `${folder.tokens.toLocaleString()} tokens`
              : "-"}
          </div>
        </div>

        <div className="action-menu" onClick={(e) => e.stopPropagation()}>
          <Popover>
            <PopoverTrigger asChild>
              <Button
                variant="ghost"
                className={`group-hover:visible mobile:visible invisible h-8 w-8 p-0 ${
                  folder.id === -1 ? "!invisible pointer-events-none" : ""
                }`}
              >
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="!p-0 w-40">
              <div className="space-y-0">
                <Button variant="menu" onClick={handleDeleteClick}>
                  <FiTrash className="h-4 w-4" />
                  Delete
                </Button>
              </div>
            </PopoverContent>
          </Popover>
        </div>
      </div>

      <DeleteEntityModal
        isOpen={isDeleteModalOpen}
        onClose={() => setIsDeleteModalOpen(false)}
        onConfirm={() => {
          setIsDeleteModalOpen(false);
          onDelete();
        }}
        entityType="folder"
        entityName={folder.name}
      />
    </>
  );
};
