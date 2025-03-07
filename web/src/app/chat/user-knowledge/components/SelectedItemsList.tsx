import React from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { X, Folder, File } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import {
  FolderResponse,
  FileResponse,
  useDocumentsContext,
} from "../DocumentsContext";
import { useDocumentSelection } from "../../useDocumentSelection";

interface SelectedItemsListProps {
  folders: FolderResponse[];
  files: FileResponse[];
  onRemoveFile: (file: FileResponse) => void;
  onRemoveFolder: (folder: FolderResponse) => void;
}

export const SelectedItemsList: React.FC<SelectedItemsListProps> = ({
  folders,
  files,
  onRemoveFile,
  onRemoveFolder,
}) => {
  const hasItems = folders.length > 0 || files.length > 0;

  return (
    <div className="h-full w-full flex flex-col">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-neutral-800 dark:text-neutral-100">
          Selected Items
        </h3>
        {hasItems && (
          <Badge
            variant="outline"
            size="xs"
            className="ml-2 dark:border-neutral-600 dark:text-neutral-200 dark:bg-neutral-800/50"
          >
            {folders.length + files.length} item
            {folders.length + files.length !== 1 ? "s" : ""}
          </Badge>
        )}
      </div>

      <Separator className="mb-3 dark:bg-neutral-700" />

      <ScrollArea className="flex-grow pr-1">
        <div className="space-y-2.5">
          {folders.length > 0 && (
            <div className="space-y-2.5">
              {folders.map((folder: FolderResponse) => (
                <div
                  key={folder.id}
                  className={cn(
                    "group flex items-center justify-between rounded-md border p-2.5",
                    "bg-neutral-100/80 border-neutral-200 hover:bg-neutral-200/60",
                    "dark:bg-neutral-800/80 dark:border-neutral-700 dark:hover:bg-neutral-750",
                    "dark:focus:ring-1 dark:focus:ring-neutral-500 dark:focus:border-neutral-600",
                    "dark:active:bg-neutral-700 dark:active:border-neutral-600",
                    "transition-colors duration-150"
                  )}
                >
                  <div className="flex items-center min-w-0 flex-1">
                    <Folder className="h-4 w-4 mr-2.5 flex-shrink-0 text-neutral-600 dark:text-neutral-300" />
                    <span className="text-sm font-medium truncate text-neutral-800 dark:text-neutral-100">
                      {folder.name}
                    </span>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => onRemoveFolder(folder)}
                    className={cn(
                      "h-6 w-6 p-0 ml-1.5 rounded-full",
                      "opacity-0 group-hover:opacity-100",
                      "bg-neutral-200/70 hover:bg-neutral-300 hover:text-neutral-700",
                      "dark:bg-neutral-700 dark:hover:bg-neutral-600 dark:text-neutral-300 dark:hover:text-neutral-100",
                      "dark:focus:ring-1 dark:focus:ring-neutral-500",
                      "dark:active:bg-neutral-500 dark:active:text-white",
                      "transition-all duration-150 ease-in-out"
                    )}
                    aria-label={`Remove folder ${folder.name}`}
                  >
                    <X className="h-3 w-3 dark:text-neutral-200" />
                  </Button>
                </div>
              ))}
            </div>
          )}

          {files.length > 0 && (
            <div className="space-y-2.5">
              {files.map((file: FileResponse) => (
                <div
                  key={file.id}
                  className={cn(
                    "group flex items-center justify-between rounded-md border p-2.5",
                    "bg-neutral-50 border-neutral-200 hover:bg-neutral-100",
                    "dark:bg-neutral-800/70 dark:border-neutral-700 dark:hover:bg-neutral-750",
                    "dark:focus:ring-1 dark:focus:ring-neutral-500 dark:focus:border-neutral-600",
                    "dark:active:bg-neutral-700 dark:active:border-neutral-600",
                    "transition-colors duration-150"
                  )}
                >
                  <div className="flex items-center min-w-0 flex-1">
                    <File className="h-4 w-4 mr-2.5 flex-shrink-0 text-neutral-500 dark:text-neutral-300" />
                    <span className="text-sm truncate text-neutral-700 dark:text-neutral-200">
                      {file.name}
                    </span>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => onRemoveFile(file)}
                    className={cn(
                      "h-6 w-6 p-0 ml-1.5 rounded-full",
                      "opacity-0 group-hover:opacity-100",
                      "bg-neutral-200/70 hover:bg-neutral-300 hover:text-neutral-700",
                      "dark:bg-neutral-700 dark:hover:bg-neutral-600 dark:text-neutral-300 dark:hover:text-neutral-100",
                      "dark:focus:ring-1 dark:focus:ring-neutral-500",
                      "dark:active:bg-neutral-500 dark:active:text-white",
                      "transition-all duration-150 ease-in-out"
                    )}
                    aria-label={`Remove file ${file.name}`}
                  >
                    <X className="h-3 w-3 dark:text-neutral-200" />
                  </Button>
                </div>
              ))}
            </div>
          )}

          {!hasItems && (
            <div className="flex items-center justify-center h-24 text-sm text-neutral-500 dark:text-neutral-400 italic bg-neutral-50/50 dark:bg-neutral-800/30 rounded-md border border-neutral-200/50 dark:border-neutral-700/50">
              No items selected
            </div>
          )}
        </div>
      </ScrollArea>
    </div>
  );
};
