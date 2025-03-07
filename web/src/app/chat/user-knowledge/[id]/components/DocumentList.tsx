import React, { useState, useEffect } from "react";
import {
  FileResponse,
  FolderResponse,
  useDocumentsContext,
} from "../../DocumentsContext";
import {
  FileListItem,
  SkeletonFileListItem,
} from "../../components/FileListItem";
import { Button } from "@/components/ui/button";
import { Loader2 } from "lucide-react";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import TextView from "@/components/chat/TextView";
import { Input } from "@/components/ui/input";
import { FileUploadSection } from "./upload/FileUploadSection";
import { useDocumentSelection } from "@/app/chat/useDocumentSelection";
import { getDisplayNameForModel } from "@/lib/hooks";

interface DocumentListProps {
  files: FileResponse[];
  onRename: (
    itemId: number,
    currentName: string,
    isFolder: boolean
  ) => Promise<void>;
  onDelete: (itemId: number, isFolder: boolean, itemName: string) => void;
  onDownload: (documentId: string) => Promise<void>;
  onUpload: (files: File[]) => void;
  onMove: (fileId: number, targetFolderId: number) => Promise<void>;
  folders: FolderResponse[];
  isLoading: boolean;
  disabled?: boolean;
  editingItemId: number | null;
  onSaveRename: (itemId: number, isFolder: boolean) => Promise<void>;
  onCancelRename: () => void;
  newItemName: string;
  setNewItemName: React.Dispatch<React.SetStateAction<string>>;
  folderId: number;
  tokenPercentage?: number;
  totalTokens?: number;
  maxTokens?: number;
  selectedModelName?: string;
}

export const DocumentList: React.FC<DocumentListProps> = ({
  files,
  onRename,
  onDelete,
  onDownload,
  onUpload,
  onMove,
  folders,
  isLoading,
  disabled,
  editingItemId,
  onSaveRename,
  onCancelRename,
  newItemName,
  setNewItemName,
  folderId,
  tokenPercentage,
  totalTokens,
  maxTokens,
  selectedModelName,
}) => {
  const [presentingDocument, setPresentingDocument] =
    useState<FileResponse | null>(null);
  const [uploadingFiles, setUploadingFiles] = useState<string[]>([]);
  const [refreshInterval, setRefreshInterval] = useState<NodeJS.Timeout | null>(
    null
  );

  const { createFileFromLink } = useDocumentsContext();

  const handleCreateFileFromLink = async (url: string) => {
    setUploadingFiles((prev) => [...prev, url]);

    try {
      await createFileFromLink(url, folderId);
      startRefreshInterval();
    } catch (error) {
      console.error("Error creating file from link:", error);
    }
  };

  const handleFileUpload = (files: File[]) => {
    const fileNames = files.map((file) => file.name);
    setUploadingFiles((prev) => [...prev, ...fileNames]);

    onUpload(files);

    startRefreshInterval();
  };

  const startRefreshInterval = () => {
    if (refreshInterval) {
      clearInterval(refreshInterval);
    }

    const interval = setInterval(() => {
      const allFilesUploaded = uploadingFiles.every((uploadingFile) => {
        if (uploadingFile.startsWith("http")) {
          return files.length > 0;
        }
        return files.some((file) => file.name === uploadingFile);
      });

      if (allFilesUploaded && uploadingFiles.length > 0) {
        setUploadingFiles([]);
        clearInterval(interval);
        setRefreshInterval(null);
      }
    }, 2000);

    setRefreshInterval(interval);
  };

  useEffect(() => {
    return () => {
      if (refreshInterval) {
        clearInterval(refreshInterval);
      }
    };
  }, [refreshInterval]);

  const handleUploadComplete = () => {
    startRefreshInterval();
  };

  return (
    <div className="w-full">
      {presentingDocument && (
        <TextView
          presentingDocument={{
            semantic_identifier: presentingDocument.name,
            document_id: presentingDocument.document_id,
          }}
          onClose={() => setPresentingDocument(null)}
        />
      )}

      <div className="flex justify-between items-center">
        <h2 className="text-sm font-semibold text-neutral-800 dark:text-neutral-200">
          Documents in this Folder
        </h2>
      </div>

      <div className="mb-6">
        <FileUploadSection
          disabled={disabled}
          disabledMessage={
            disabled
              ? "This folder cannot be edited. It contains your recent documents."
              : undefined
          }
          onUpload={handleFileUpload}
          onUrlUpload={handleCreateFileFromLink}
          isUploading={uploadingFiles.length > 0}
          onUploadComplete={handleUploadComplete}
        />
      </div>

      <div className="flex items-center gap-6 my-2 border-neutral-200 dark:border-neutral-700 pb-4">
        {/* Context Limit */}
        <div className="flex items-center gap-3">
          <div className="flex flex-col">
            <span className="text-xs text-neutral-500 dark:text-neutral-400 mb-1">
              Context usage for {getDisplayNameForModel(selectedModelName)}
            </span>

            <div className="flex items-center gap-2 px-3 py-1.5 bg-neutral-100 dark:bg-neutral-800 rounded-lg shadow-sm">
              <div className="h-2 w-16 bg-neutral-200 dark:bg-neutral-700 rounded-full overflow-hidden">
                <div
                  className={`h-full transition-all duration-300 ${
                    tokenPercentage > 75
                      ? "bg-red-500"
                      : tokenPercentage > 50
                        ? "bg-amber-500"
                        : "bg-emerald-500"
                  }`}
                  style={{ width: `${Math.min(tokenPercentage, 100)}%` }}
                />
              </div>
              <span className="text-xs font-medium text-neutral-700 dark:text-neutral-300">
                {totalTokens?.toLocaleString() || "0"} /{" "}
                {maxTokens?.toLocaleString() || "0"} tokens
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="space-y-2">
        {isLoading ? (
          Array.from({ length: 3 }).map((_, index) => (
            <div
              key={`skeleton-${index}`}
              className="flex items-center p-3 rounded-lg border border-neutral-200 dark:border-neutral-700 animate-pulse"
            >
              <div className="w-5 h-5 bg-neutral-200 dark:bg-neutral-700 rounded mr-3"></div>
              <div className="flex-1">
                <div className="h-4 bg-neutral-200 dark:bg-neutral-700 rounded w-1/3 mb-2"></div>
                <div className="h-3 bg-neutral-200 dark:bg-neutral-700 rounded w-1/4"></div>
              </div>
            </div>
          ))
        ) : (
          <>
            {uploadingFiles.map((fileName, index) => (
              <div
                key={`uploading-${index}`}
                className="flex items-center p-3 rounded-lg border border-neutral-200 dark:border-neutral-700"
              >
                <div className="w-5 h-5 mr-3 text-blue-500 dark:text-blue-400 animate-spin">
                  <Loader2 className="w-5 h-5" />
                </div>
                <div className="flex-1">
                  <div className="text-sm font-medium text-neutral-800 dark:text-neutral-200">
                    {fileName.startsWith("http")
                      ? `Processing URL: ${fileName.substring(0, 30)}${
                          fileName.length > 30 ? "..." : ""
                        }`
                      : fileName}
                  </div>
                  <div className="text-xs text-blue-500 dark:text-blue-400">
                    Uploading...
                  </div>
                </div>
              </div>
            ))}

            <div className="flex mr-8 items-center border-b border-border dark:border-border-200 py-2 px-4 text-sm font-medium text-text-400 dark:text-neutral-400">
              <div className="w-[40%]">Name</div>
              <div className="w-[30%]">Created</div>
              <div className="w-[30%]">Total Tokens</div>
            </div>

            {files.map((file) => (
              <div key={file.id}>
                {editingItemId === file.id ? (
                  <div className="flex items-center p-3 rounded-lg border border-neutral-200 dark:border-neutral-700">
                    <div className="flex-1 flex items-center gap-3">
                      <Input
                        value={newItemName}
                        onChange={(e) => setNewItemName(e.target.value)}
                        className="mr-2"
                        autoFocus
                      />
                      <Button
                        onClick={() => onSaveRename(file.id, false)}
                        className="mr-2"
                        size="sm"
                      >
                        Save
                      </Button>
                      <Button
                        onClick={onCancelRename}
                        variant="outline"
                        size="sm"
                      >
                        Cancel
                      </Button>
                    </div>
                  </div>
                ) : (
                  <FileListItem
                    file={file}
                    view="list"
                    onRename={onRename}
                    onDelete={onDelete}
                    onDownload={onDownload}
                    onMove={onMove}
                    folders={folders}
                    onSelect={() => setPresentingDocument(file)}
                    isIndexed={file.indexed || false}
                  />
                )}
              </div>
            ))}

            {files.length === 0 && uploadingFiles.length === 0 && (
              <div className="text-center py-8 text-neutral-500 dark:text-neutral-400">
                No documents in this folder yet. Upload files or add from URL to
                get started.
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};
