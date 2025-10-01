import React from "react";
import { File, Link as LinkIcon, Folder } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface SearchResultItemProps {
  item: {
    id: number;
    name: string;
    document_id: string;
  };
  view: "grid" | "list";
  onClick: (documentId: string, name: string) => void;
  isLink?: boolean;
  lastUpdated?: string;
  onRename: () => void;
  onDelete: () => void;
  onMove: () => void;
  parentFolder?: {
    id: number;
    name: string;
  };
  onParentFolderClick?: (folderId: number) => void;
  fileSize?: FileSize;
}
export enum FileSize {
  SMALL = "Small",
  MEDIUM = "Medium",
  LARGE = "Large",
}
export const fileSizeToDescription = {
  [FileSize.SMALL]: "Small",
  [FileSize.MEDIUM]: "Medium",
  [FileSize.LARGE]: "Large",
};

export const SearchResultItem: React.FC<SearchResultItemProps> = ({
  item,
  view,
  onClick,
  isLink = false,
  lastUpdated,
  onRename,
  onDelete,
  onMove,
  parentFolder,
  onParentFolderClick,
  fileSize = FileSize.SMALL,
}) => {
  const Icon = isLink ? LinkIcon : File;

  return (
    <div className="flex items-center justify-between w-full">
      <a
        className={`flex items-center flex-grow ${
          view === "list" ? "w-full" : "w-4/5"
        } p-3 rounded-lg hover:bg-[#F3F2EA]/60 transition-colors duration-200`}
        href="#"
        onClick={(e) => {
          e.preventDefault();
          onClick(item.document_id, item.name);
        }}
      >
        <Icon className="h-5 w-5 mr-3 text-orange-600 flex-shrink-0" />
        <div className="flex flex-col min-w-0">
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="text-sm font-medium text-text-900 truncate">
                  {item.name}
                </span>
              </TooltipTrigger>
              <TooltipContent>
                <p>{item.name}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <div className="flex items-center w-full justify-start gap-x-1">
            {lastUpdated && (
              <span className="text-xs text-text-500"> {lastUpdated}</span>
            )}
            {fileSize && (
              <>
                <div className="flex items-center justify-center h-1.5 w-1.5  mx-1 rounded-full bg-background-400 transition-colors duration-200"></div>
                <span className="text-xs text-text-500">
                  {fileSizeToDescription[fileSize]}
                </span>
              </>
            )}
            <div className="flex items-center justify-center h-2 w-2 rounded-full hover:bg-background-200 transition-colors duration-200"></div>
          </div>
        </div>
        {parentFolder && (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  className="flex items-center justify-center h-10 w-10 rounded-full hover:bg-background-200 transition-colors duration-200"
                  onClick={() => onParentFolderClick?.(parentFolder.id)}
                >
                  <Folder className="h-5 w-5 text-text-500" />
                </button>
              </TooltipTrigger>
              <TooltipContent>
                <p>Parent Folder: {parentFolder.name}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}
      </a>
    </div>
  );
};
