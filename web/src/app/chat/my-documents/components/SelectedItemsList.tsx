import React from "react";
import { cn, truncateString } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { X, FolderIcon, Loader2 } from "lucide-react";
import { FolderResponse, FileResponse } from "../DocumentsContext";
import { getFileIconFromFileNameAndLink } from "@/lib/assistantIconUtils";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import { UploadingFile } from "./FilePicker";
import { CircularProgress } from "../[id]/components/upload/CircularProgress";

interface SelectedItemsListProps {
  folders: FolderResponse[];
  files: FileResponse[];
  uploadingFiles: UploadingFile[];
  onRemoveFile: (file: FileResponse) => void;
  onRemoveFolder: (folder: FolderResponse) => void;
  setPresentingDocument: (onyxDocument: MinimalOnyxDocument) => void;
}

export const SelectedItemsList: React.FC<SelectedItemsListProps> = ({
  folders,
  files,
  uploadingFiles,
  onRemoveFile,
  onRemoveFolder,
  setPresentingDocument,
}) => {
  const hasItems =
    folders.length > 0 || files.length > 0 || uploadingFiles.length > 0;
  const openFile = (file: FileResponse) => {
    if (file.link_url) {
      window.open(file.link_url, "_blank");
    } else {
      setPresentingDocument({
        semantic_identifier: file.name,
        document_id: file.document_id,
      });
    }
  };

  return (
    <div className="h-full w-full flex flex-col">
      <div className="space-y-2.5 pb-2">
        {folders.length > 0 && (
          <div className="space-y-2.5">
            {folders.map((folder: FolderResponse) => (
              <div key={folder.id} className="group flex items-center gap-2">
                <div
                  className={cn(
                    "group flex-1 flex items-center rounded-md border p-2.5",
                    "bg-neutral-100/80 border-neutral-200 hover:bg-neutral-200/60",
                    "dark:bg-neutral-800/80 dark:border-neutral-700 dark:hover:bg-neutral-750",
                    "dark:focus:ring-1 dark:focus:ring-neutral-500 dark:focus:border-neutral-600",
                    "dark:active:bg-neutral-700 dark:active:border-neutral-600",
                    "transition-colors duration-150"
                  )}
                >
                  <div className="flex items-center min-w-0 flex-1">
                    <FolderIcon className="h-5 w-5 mr-2 text-black dark:text-black shrink-0 fill-black dark:fill-black" />

                    <span className="text-sm font-medium truncate text-neutral-800 dark:text-neutral-100">
                      {truncateString(folder.name, 34)}
                    </span>
                  </div>
                </div>

                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onRemoveFolder(folder)}
                  className={cn(
                    "bg-transparent hover:bg-transparent opacity-0 group-hover:opacity-100",
                    "h-6 w-6 p-0 rounded-full shrink-0",
                    "hover:text-neutral-700",
                    "dark:text-neutral-300 dark:hover:text-neutral-100",
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
          <div className="space-y-2.5 ">
            {files.map((file: FileResponse) => (
              <div
                key={file.id}
                className="group w-full flex items-center gap-2"
              >
                <div
                  className={cn(
                    "group flex-1 flex items-center rounded-md border p-2.5",
                    "bg-neutral-50 border-neutral-200 hover:bg-neutral-100",
                    "dark:bg-neutral-800/70 dark:border-neutral-700 dark:hover:bg-neutral-750",
                    "dark:focus:ring-1 dark:focus:ring-neutral-500 dark:focus:border-neutral-600",
                    "dark:active:bg-neutral-700 dark:active:border-neutral-600",
                    "transition-colors duration-150",
                    "cursor-pointer"
                  )}
                  onClick={() => openFile(file)}
                >
                  <div className="flex items-center min-w-0 flex-1">
                    {getFileIconFromFileNameAndLink(file.name, file.link_url)}
                    <span className="text-sm truncate text-neutral-700 dark:text-neutral-200 ml-2.5">
                      {truncateString(file.name, 34)}
                    </span>
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onRemoveFile(file)}
                  className={cn(
                    "bg-transparent hover:bg-transparent opacity-0 group-hover:opacity-100",
                    "h-6 w-6 p-0 rounded-full shrink-0",
                    "hover:text-neutral-700",
                    "dark:text-neutral-300 dark:hover:text-neutral-100",
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
        <div className="max-w-full space-y-2.5">
          {uploadingFiles
            .filter(
              (uploadingFile) =>
                !files.map((file) => file.name).includes(uploadingFile.name)
            )
            .map((uploadingFile, index) => (
              <div key={index} className="mr-8 flex items-center gap-2">
                <div
                  key={`uploading-${index}`}
                  className={cn(
                    "group flex-1 flex items-center rounded-md border p-2.5",
                    "bg-neutral-50 border-neutral-200 hover:bg-neutral-100",
                    "dark:bg-neutral-800/70 dark:border-neutral-700 dark:hover:bg-neutral-750",
                    "dark:focus:ring-1 dark:focus:ring-neutral-500 dark:focus:border-neutral-600",
                    "dark:active:bg-neutral-700 dark:active:border-neutral-600",
                    "transition-colors duration-150",
                    "cursor-pointer"
                  )}
                >
                  <div className="flex items-center min-w-0 flex-1">
                    <div className="flex items-center gap-2 min-w-0">
                      {uploadingFile.name.startsWith("http") ? (
                        <Loader2 className="w-4 h-4 animate-spin text-blue-500" />
                      ) : (
                        <CircularProgress
                          progress={uploadingFile.progress}
                          size={18}
                          showPercentage={false}
                        />
                      )}
                      <span className="truncate text-sm text-text-dark dark:text-text-dark">
                        {uploadingFile.name.startsWith("http")
                          ? `${uploadingFile.name.substring(0, 30)}${
                              uploadingFile.name.length > 30 ? "..." : ""
                            }`
                          : truncateString(uploadingFile.name, 34)}
                      </span>
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    // onClick={() => onRemoveFile(file)}
                    className={cn(
                      "bg-transparent hover:bg-transparent opacity-0 group-hover:opacity-100",
                      "h-6 w-6 p-0 rounded-full shrink-0",
                      "hover:text-neutral-700",
                      "dark:text-neutral-300 dark:hover:text-neutral-100",
                      "dark:focus:ring-1 dark:focus:ring-neutral-500",
                      "dark:active:bg-neutral-500 dark:active:text-white",
                      "transition-all duration-150 ease-in-out"
                    )}
                    // aria-label={`Remove file ${file.name}`}
                  >
                    <X className="h-3 w-3 dark:text-neutral-200" />
                  </Button>
                </div>
              </div>
            ))}
        </div>
        {!hasItems && (
          <div className="flex items-center justify-center h-24 text-sm text-neutral-500 dark:text-neutral-400 italic bg-neutral-50/50 dark:bg-neutral-800/30 rounded-md border border-neutral-200/50 dark:border-neutral-700/50">
            No items selected
          </div>
        )}
      </div>
    </div>
  );
};
