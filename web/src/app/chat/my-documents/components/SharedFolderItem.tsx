import React from "react";
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
    <a
      className={`from-[#f2f0e8]/80 to-[#F7F6F0] dark:from-[#1a1a1a] dark:to-[#222222] border-0.5 border-border dark:border-border hover:from-[#f2f0e8] hover:to-[#F7F6F0] dark:hover:from-[#222222] dark:hover:to-[#2a2a2a] hover:border-border-200 dark:hover:border-border-200 text-md group relative flex cursor-pointer ${
        false ? "flex-row items-center" : "flex-col"
      } overflow-x-hidden text-ellipsis rounded-xl bg-gradient-to-b py-4 pl-5 pr-4 transition-all ease-in-out hover:shadow-sm active:scale-[0.99]`}
      onClick={(e) => {
        e.preventDefault();
        onClick(folder.id);
      }}
    >
      <div
        className={`flex ${
          false ? "flex-row items-center" : "flex-col"
        } flex-1`}
      >
        <div className="font-tiempos flex items-center">
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="text-truncate line-clamp-2 text-text-dark dark:text-text-dark inline-block max-w-md">
                  {folder.name}
                </span>
              </TooltipTrigger>
              <TooltipContent>
                <p>{folder.name}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
        {description && (
          <div
            className={`text-text-400 dark:text-neutral-400 ${
              false ? "ml-4" : "mt-1"
            } line-clamp-2 text-xs`}
          >
            {description}
          </div>
        )}
      </div>
      {lastUpdated && (
        <div className="text-text-500 dark:text-text-500 mt-3 flex justify-between text-xs">
          &nbsp;
          <span>
            Updated{" "}
            <span data-state="closed">
              {getTimeAgoString(new Date(lastUpdated))}
            </span>
          </span>
        </div>
      )}
    </a>
  );
};
