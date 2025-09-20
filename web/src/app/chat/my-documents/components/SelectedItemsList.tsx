import React from "react";
import { cn, truncateString } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { X, FolderIcon, Loader2 } from "lucide-react";
import {
  FolderResponse,
  FileResponse,
} from "@/app/chat/my-documents/DocumentsContext";
import { getFileIconFromFileNameAndLink } from "@/lib/assistantIconUtils";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import { UploadingFile } from "@/app/chat/my-documents/components/FilePicker";
import { CircularProgress } from "@/app/chat/my-documents/[id]/components/upload/CircularProgress";

interface SelectedItemsListProps {
  folders: FolderResponse[];
  files: FileResponse[];
  uploadingFiles: UploadingFile[];
  onRemoveFile: (file: FileResponse) => void;
  onRemoveFolder: (folder: FolderResponse) => void;
  setPresentingDocument: (onyxDocument: MinimalOnyxDocument) => void;
}

export function SelectedItemsList({
  folders,
  files,
  uploadingFiles,
  onRemoveFile,
  onRemoveFolder,
  setPresentingDocument,
}: SelectedItemsListProps) {
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
        {/* Folders */}
        {folders.length > 0 && (
          <div className="space-y-2.5">
            {folders.map((folder: FolderResponse) => (
              <div key={folder.id} className="group flex items-center gap-2">
                <div
                  className={cn(
                    "group flex-1 flex items-center rounded-md border p-2.5",
                    "bg-background-tint-01 border hover:bg-background-tint-02",
                    "transition-colors duration-150"
                  )}
                >
                  <div className="flex items-center min-w-0 flex-1">
                    <FolderIcon className="h-5 w-5 mr-2 shrink-0" />

                    <span className="text-sm font-medium truncate">
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
                    "hover:text-text-01",
                    "transition-all duration-150 ease-in-out"
                  )}
                  aria-label={`Remove folder ${folder.name}`}
                >
                  <X className="h-3 w-3 " />
                </Button>
              </div>
            ))}
          </div>
        )}

        {/* Files */}
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
                    "bg-background-tint-01 border hover:bg-background-tint-02",
                    "transition-colors duration-150",
                    "cursor-pointer"
                  )}
                  onClick={() => openFile(file)}
                >
                  <div className="flex items-center min-w-0 flex-1">
                    {getFileIconFromFileNameAndLink(file.name, file.link_url)}
                    <span className="text-sm truncate ml-2.5">
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
                    "hover:text-text-01",
                    "transition-all duration-150 ease-in-out"
                  )}
                  aria-label={`Remove file ${file.name}`}
                >
                  <X className="h-3 w-3 " />
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
                    "bg-background-tint-01 border hover:bg-background-tint-02",
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
                      <span className="truncate text-sm">
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
                      "hover:text-text-01",
                      "transition-all duration-150 ease-in-out"
                    )}
                    // aria-label={`Remove file ${file.name}`}
                  >
                    <X className="h-3 w-3 " />
                  </Button>
                </div>
              </div>
            ))}
        </div>
        {!hasItems && (
          <div className="flex items-center justify-center h-24 text-sm italic bg-background-tint-01 rounded-md border">
            No items selected
          </div>
        )}
      </div>
    </div>
  );
}
