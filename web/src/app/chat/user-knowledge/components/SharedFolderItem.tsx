import React from "react";
import { FolderIcon } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { getTimeAgoString } from "@/lib/dateUtils";

interface SharedFolderItemProps {
  folder: {
    id: number;
    name: string;
    tokens?: number;
  };
  onClick: (folderId: number) => void;
  description?: string;
  lastUpdated?: string;
  onRename: () => void;
  onDelete: () => void;
  onMove: () => void;
}

export const SharedFolderItem: React.FC<SharedFolderItemProps> = ({
  folder,
  onClick,
  description,
  lastUpdated,
  onRename,
  onDelete,
  onMove,
}) => {
  return (
    <div
      className="group relative flex cursor-pointer items-center border-b border-border dark:border-border-200 hover:bg-[#f2f0e8]/50 dark:hover:bg-[#1a1a1a]/50 py-3 px-4 transition-all ease-in-out"
      onClick={(e) => {
        e.preventDefault();
        onClick(folder.id);
      }}
    >
      <div className="flex items-center flex-1 min-w-0">
        <div className="flex items-center gap-3 w-[40%]">
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
                {description && (
                  <p className="text-xs text-neutral-500">{description}</p>
                )}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>

        <div className="w-[30%] text-sm text-text-400 dark:text-neutral-400">
          {lastUpdated && getTimeAgoString(new Date(lastUpdated))}
        </div>

        <div className="w-[30%] text-sm text-text-400 dark:text-neutral-400">
          {folder.tokens !== undefined
            ? `${folder.tokens.toLocaleString()} tokens`
            : "-"}
        </div>
      </div>
    </div>
  );
};
