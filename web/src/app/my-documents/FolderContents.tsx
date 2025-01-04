import React, { useEffect, useRef, useState } from "react";
import {
  FolderIcon,
  FileIcon,
  DownloadIcon,
  TrashIcon,
  PencilIcon,
  InfoIcon,
  CheckIcon,
  XIcon,
} from "lucide-react";
import { Popover } from "@headlessui/react";
import { MoveFileModal } from "./MoveFileModal";

interface FolderContentsProps {
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
    destinationFolderId: number,
    isFolder: boolean
  ) => void;
  setPresentingDocument: (
    document_id: string,
    semantic_identifier: string
  ) => void;
  onRenameItem: (itemId: number, newName: string, isFolder: boolean) => void;
}

export function FolderContents({
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

  const handleMove = (destinationFolderId: number) => {
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

  return (
    <div className="flex-grow" onDragOver={(e) => e.preventDefault()}>
      {contents.children.map((folder) => (
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
      {contents.files.map((file) => (
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
      {itemToMove && (
        <MoveFileModal
          isOpen={isMoveModalOpen}
          onClose={() => setIsMoveModalOpen(false)}
          onMove={handleMove}
          currentLocation={{ id: currentFolder, name: "Current Folder" }}
          fileName={itemToMove.name}
        />
      )}
    </div>
  );
}

interface FolderItemProps {
  folder: { name: string; id: number };
  onFolderClick: (folderId: number) => void;
  onDeleteItem: (itemId: number, isFolder: boolean) => void;
  onMoveItem: (folderId: number) => void;
  editingItem: { id: number; name: string; isFolder: boolean } | null;
  setEditingItem: React.Dispatch<
    React.SetStateAction<{ id: number; name: string; isFolder: boolean } | null>
  >;
  handleRename: (id: number, newName: string, isFolder: boolean) => void;
  onDragStart: (
    e: React.DragEvent<HTMLDivElement>,
    item: { id: number; isFolder: boolean; name: string }
  ) => void;
  onDrop: (e: React.DragEvent<HTMLDivElement>, targetFolderId: number) => void;
}

function FolderItem({
  folder,
  onFolderClick,
  onDeleteItem,
  onMoveItem,
  editingItem,
  setEditingItem,
  handleRename,
  onDragStart,
  onDrop,
}: FolderItemProps) {
  const [showMenu, setShowMenu] = useState(false);
  const [newName, setNewName] = useState(folder.name);

  const isEditing =
    editingItem && editingItem.id === folder.id && editingItem.isFolder;

  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    setShowMenu(!showMenu);
  };

  const startEditing = () => {
    setEditingItem({ id: folder.id, name: folder.name, isFolder: true });
    setNewName(folder.name);
    setShowMenu(false);
  };

  const submitRename = (e: React.MouseEvent) => {
    e.stopPropagation();
    handleRename(folder.id, newName, true);
  };

  const cancelEditing = (e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingItem(null);
    setNewName(folder.name);
  };

  return (
    <div
      className="flex items-center justify-between p-2 hover:bg-gray-100 cursor-pointer"
      onClick={() => !isEditing && onFolderClick(folder.id)}
      onContextMenu={handleContextMenu}
      draggable={!isEditing}
      onDragStart={(e) =>
        onDragStart(e, { id: folder.id, isFolder: true, name: folder.name })
      }
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => onDrop(e, folder.id)}
    >
      <div className="flex items-center">
        <FolderIcon className="mr-2" />
        {isEditing ? (
          <div className="flex items-center">
            <input
              onClick={(e) => e.stopPropagation()}
              type="text"
              value={newName}
              onChange={(e) => {
                e.stopPropagation();
                setNewName(e.target.value);
              }}
              className="border rounded px-2 py-1 mr-2"
              autoFocus
            />
            <button
              onClick={submitRename}
              className="text-green-500 hover:text-green-700 mr-2"
            >
              <CheckIcon className="h-4 w-4" />
            </button>
            <button
              onClick={cancelEditing}
              className="text-red-500 hover:text-red-700"
            >
              <XIcon className="h-4 w-4" />
            </button>
          </div>
        ) : (
          <span>{folder.name}</span>
        )}
      </div>
      {showMenu && !isEditing && (
        <div className="absolute bg-white border rounded shadow py-1 right-10 z-50">
          <button
            className="block w-full text-left px-4 py-2 hover:bg-gray-100 text-sm"
            onClick={(e) => {
              e.stopPropagation();
              startEditing();
            }}
          >
            Rename
          </button>
          <button
            className="block w-full text-left px-4 py-2 hover:bg-gray-100 text-sm"
            onClick={(e) => {
              e.stopPropagation();
              onMoveItem(folder.id);
              setShowMenu(false);
            }}
          >
            Move
          </button>
          <button
            className="block w-full text-left px-4 py-2 hover:bg-gray-100 text-sm text-red-600"
            onClick={(e) => {
              e.stopPropagation();
              onDeleteItem(folder.id, true);
              setShowMenu(false);
            }}
          >
            Delete
          </button>
        </div>
      )}
    </div>
  );
}

interface FileItemProps {
  file: { name: string; id: number; document_id: string };
  onDeleteItem: (itemId: number, isFolder: boolean) => void;
  onDownloadItem: (documentId: string) => void;
  onMoveItem: (fileId: number) => void;
  editingItem: { id: number; name: string; isFolder: boolean } | null;
  setEditingItem: React.Dispatch<
    React.SetStateAction<{ id: number; name: string; isFolder: boolean } | null>
  >;
  setPresentingDocument: (
    document_id: string,
    semantic_identifier: string
  ) => void;
  handleRename: (fileId: number, newName: string, isFolder: boolean) => void;
  onDragStart: (
    e: React.DragEvent<HTMLDivElement>,
    item: { id: number; isFolder: boolean; name: string }
  ) => void;
}

function FileItem({
  setPresentingDocument,
  file,
  onDeleteItem,
  onDownloadItem,
  onMoveItem,
  editingItem,
  setEditingItem,
  handleRename,
  onDragStart,
}: FileItemProps) {
  const [showMenu, setShowMenu] = useState(false);
  const [newFileName, setNewFileName] = useState(file.name);

  const isEditing =
    editingItem && editingItem.id === file.id && !editingItem.isFolder;

  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    setShowMenu(!showMenu);
  };

  const startEditing = () => {
    setEditingItem({ id: file.id, name: file.name, isFolder: false });
    setNewFileName(file.name);
    setShowMenu(false);
  };

  const submitRename = (e: React.MouseEvent) => {
    e.stopPropagation();
    handleRename(file.id, newFileName, false);
  };

  const cancelEditing = (e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingItem(null);
    setNewFileName(file.name);
  };

  return (
    <div
      key={file.id}
      className="flex items-center w-full justify-between p-2 hover:bg-gray-100 cursor-pointer"
      onContextMenu={handleContextMenu}
      draggable={!isEditing}
      onDragStart={(e) =>
        onDragStart(e, { id: file.id, isFolder: false, name: file.name })
      }
    >
      <button
        onClick={() => setPresentingDocument(file.document_id, file.name)}
        className="flex items-center flex-grow"
      >
        <FileIcon className="mr-2" />
        {isEditing ? (
          <div className="flex items-center">
            <input
              onClick={(e) => e.stopPropagation()}
              type="text"
              value={newFileName}
              onChange={(e) => {
                e.stopPropagation();
                setNewFileName(e.target.value);
              }}
              className="border rounded px-2 py-1 mr-2"
              autoFocus
            />
            <button
              onClick={submitRename}
              className="text-green-500 hover:text-green-700 mr-2"
            >
              <CheckIcon className="h-4 w-4" />
            </button>
            <button
              onClick={cancelEditing}
              className="text-red-500 hover:text-red-700"
            >
              <XIcon className="h-4 w-4" />
            </button>
          </div>
        ) : (
          <p className="flex text-wrap text-left line-clamp-2">{file.name}</p>
        )}
      </button>
      {showMenu && !isEditing && (
        <div className="absolute bg-white border rounded shadow py-1 right-10 z-50">
          <button
            className="block w-full text-left px-4 py-2 hover:bg-gray-100 text-sm"
            onClick={(e) => {
              e.stopPropagation();
              onDownloadItem(file.document_id);
              setShowMenu(false);
            }}
          >
            Download
          </button>
          <button
            className="block w-full text-left px-4 py-2 hover:bg-gray-100 text-sm"
            onClick={(e) => {
              e.stopPropagation();
              startEditing();
            }}
          >
            Rename
          </button>
          <button
            className="block w-full text-left px-4 py-2 hover:bg-gray-100 text-sm"
            onClick={(e) => {
              e.stopPropagation();
              onMoveItem(file.id);
              setShowMenu(false);
            }}
          >
            Move
          </button>
          <button
            className="block w-full text-left px-4 py-2 hover:bg-gray-100 text-sm text-red-600"
            onClick={(e) => {
              e.stopPropagation();
              onDeleteItem(file.id, false);
              setShowMenu(false);
            }}
          >
            Delete
          </button>
        </div>
      )}
    </div>
  );
}
