import React, { useState } from "react";
import { FileResponse, FolderResponse } from "../../DocumentsContext";
import {
  FileListItem,
  SkeletonFileListItem,
} from "../../components/FileListItem";
import { Button } from "@/components/ui/button";
import { Grid, List, Loader2 } from "lucide-react";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import TextView from "@/components/chat/TextView";
import { Input } from "@/components/ui/input";
import { FileUploadSection } from "./upload/FileUploadSection";

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
}) => {
  const [presentingDocument, setPresentingDocument] =
    useState<MinimalOnyxDocument | null>(null);
  const [view, setView] = useState<"grid" | "list">("list");

  const toggleView = () => {
    setView(view === "grid" ? "list" : "grid");
  };

  return (
    <div className="space-y-4">
      {presentingDocument && (
        <TextView
          presentingDocument={presentingDocument}
          onClose={() => setPresentingDocument(null)}
        />
      )}

      <div className="flex justify-between items-center">
        <h2 className="text-sm font-semibold text-neutral-800 dark:text-neutral-200">
          Documents in this Project
        </h2>
        <Button onClick={toggleView} variant="outline" size="sm">
          {view === "grid" ? <List size={16} /> : <Grid size={16} />}
        </Button>
      </div>
      <FileUploadSection
        disabled={disabled}
        disabledMessage={
          disabled
            ? "This folder cannot be edited. It contains your recent documents."
            : undefined
        }
        onUpload={onUpload}
      />

      <div className={view === "grid" ? "grid grid-cols-4 gap-4" : "space-y-2"}>
        {files.map((file) => (
          <div key={file.id}>
            {editingItemId === file.id ? (
              <div className="flex items-center">
                <Input
                  value={newItemName}
                  onChange={(e) => setNewItemName(e.target.value)}
                  className="mr-2"
                />
                <Button
                  onClick={() => onSaveRename(file.id, false)}
                  className="mr-2"
                >
                  Save
                </Button>
                <Button onClick={onCancelRename} variant="outline">
                  Cancel
                </Button>
              </div>
            ) : (
              <FileListItem
                file={file}
                view={view}
                onRename={onRename}
                onDelete={onDelete}
                onDownload={onDownload}
                onMove={onMove}
                folders={folders}
                onSelect={() =>
                  setPresentingDocument({
                    semantic_identifier: file.name,
                    document_id: file.document_id,
                  })
                }
                isIndexed={file.indexed || false}
              />
            )}
          </div>
        ))}
        {isLoading && <SkeletonFileListItem view={view} />}
      </div>
    </div>
  );
};
