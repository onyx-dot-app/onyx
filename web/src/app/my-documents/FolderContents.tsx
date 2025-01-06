import React, { useState } from "react";
import { MoveFileModal } from "./MoveFileModal";
import { FileItem, FolderItem } from "./MyDocumenItem";

interface FolderContentsProps {
  pageLimit: number;
  currentPage: number;
  contents: {
    children: { name: string; id: number }[];
    files: { name: string; id: number; document_id: string }[];
  };
  onFolderClick: (folderId: number) => void;
  currentFolder: number;
  onDeleteItem: (itemId: number, isFolder: boolean) => void;
  onDownloadItem: (documentId: string) => void;
  onMoveItem: (
    itemId: number,
    destinationFolderId: number | null,
    isFolder: boolean
  ) => void;
  setPresentingDocument: (
    document_id: string,
    semantic_identifier: string
  ) => void;
  onRenameItem: (itemId: number, newName: string, isFolder: boolean) => void;
}

export function FolderContents({
  pageLimit,
  currentPage,
  setPresentingDocument,
  contents,
  onFolderClick,
  currentFolder,
  onDeleteItem,
  onDownloadItem,
  onMoveItem,
  onRenameItem,
}: FolderContentsProps) {
  const [isMoveModalOpen, setIsMoveModalOpen] = useState(false);
  const [itemToMove, setItemToMove] = useState<{
    id: number;
    name: string;
    isFolder: boolean;
  } | null>(null);

  const [editingItem, setEditingItem] = useState<{
    id: number;
    name: string;
    isFolder: boolean;
  } | null>(null);

  const handleMove = (destinationFolderId: number | null) => {
    if (itemToMove) {
      onMoveItem(itemToMove.id, destinationFolderId, itemToMove.isFolder);
      setIsMoveModalOpen(false);
      setItemToMove(null);
    }
  };

  const handleRename = (itemId: number, newName: string, isFolder: boolean) => {
    onRenameItem(itemId, newName, isFolder);
    setEditingItem(null);
  };

  const handleDragStart = (
    e: React.DragEvent<HTMLDivElement>,
    item: { id: number; isFolder: boolean; name: string }
  ) => {
    e.dataTransfer.setData("application/json", JSON.stringify(item));
  };

  const handleDrop = (
    e: React.DragEvent<HTMLDivElement>,
    targetFolderId: number
  ) => {
    e.preventDefault();
    const item = JSON.parse(e.dataTransfer.getData("application/json"));
    if (item && typeof item.id === "number") {
      // Move the dragged item to the target folder
      onMoveItem(item.id, targetFolderId, item.isFolder);
    }
  };

  // we need the logic to ben let's show all the files firs then folders (ie if we have 4 files and 10 foldres and page size of 3,

  //   First index: first 3 files,
  //   nexte index; lat fileand first two folders, etc.

  return (
    <div className="flex-grow" onDragOver={(e) => e.preventDefault()}>
      {contents.files
        .slice(pageLimit * (currentPage - 1), pageLimit * currentPage)
        .map((file) => (
          <FileItem
            setPresentingDocument={setPresentingDocument}
            key={file.id}
            file={file}
            onDeleteItem={onDeleteItem}
            onDownloadItem={onDownloadItem}
            onMoveItem={(id) => {
              setItemToMove({ id, name: file.name, isFolder: false });
              setIsMoveModalOpen(true);
            }}
            editingItem={editingItem}
            setEditingItem={setEditingItem}
            handleRename={handleRename}
            onDragStart={handleDragStart}
          />
        ))}

      {contents.children
        .slice(pageLimit * (currentPage - 1), pageLimit * currentPage)
        .map((folder) => (
          <FolderItem
            key={folder.id}
            folder={folder}
            onFolderClick={onFolderClick}
            onDeleteItem={onDeleteItem}
            onMoveItem={(id) => {
              setItemToMove({ id, name: folder.name, isFolder: true });
              setIsMoveModalOpen(true);
            }}
            editingItem={editingItem}
            setEditingItem={setEditingItem}
            handleRename={handleRename}
            onDragStart={handleDragStart}
            onDrop={handleDrop}
          />
        ))}

      {itemToMove && (
        <MoveFileModal
          isOpen={isMoveModalOpen}
          onClose={() => setIsMoveModalOpen(false)}
          onMove={handleMove}
          fileName={itemToMove.name}
          currentFolderId={currentFolder}
        />
      )}
    </div>
  );
}
