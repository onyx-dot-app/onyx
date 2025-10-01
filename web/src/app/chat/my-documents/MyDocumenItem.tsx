import React, { useEffect, useRef, useState } from "react";
import { FolderIcon, FileIcon, CheckIcon, XIcon } from "lucide-react";

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

export function FolderItem({
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
  const [showMenu, setShowMenu] = useState<undefined | number>(undefined);
  const [newName, setNewName] = useState(folder.name);

  const isEditing =
    editingItem && editingItem.id === folder.id && editingItem.isFolder;

  const folderItemRef = useRef<HTMLDivElement>(null);

  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    const xPos =
      e.clientX - folderItemRef.current?.getBoundingClientRect().left! - 40;
    setShowMenu(xPos);
  };

  const startEditing = () => {
    setEditingItem({ id: folder.id, name: folder.name, isFolder: true });
    setNewName(folder.name);
    setShowMenu(undefined);
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

  useEffect(() => {
    document.addEventListener("click", (e) => {
      setShowMenu(undefined);
    });
    return () => {
      document.removeEventListener("click", () => {});
    };
  }, [showMenu]);

  return (
    <div
      ref={folderItemRef}
      className="flex items-center justify-between p-2 hover:bg-background-100 cursor-pointer relative"
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
        <FolderIcon className="h-5 w-5 text-black dark:text-black shrink-0 fill-black dark:fill-black" />
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
        <div
          className="absolute bg-white border rounded shadow py-1 right-0 top-full mt-1 z-50"
          style={{ left: showMenu }}
        >
          <button
            className="block w-full text-left px-4 py-2 hover:bg-background-100 text-sm"
            onClick={(e) => {
              e.stopPropagation();
              startEditing();
            }}
          >
            Rename
          </button>
          <button
            className="block w-full text-left px-4 py-2 hover:bg-background-100 text-sm"
            onClick={(e) => {
              e.stopPropagation();
              onMoveItem(folder.id);
              setShowMenu(undefined);
            }}
          >
            Move
          </button>
          <button
            className="block w-full text-left px-4 py-2 hover:bg-background-100 text-sm text-red-600"
            onClick={(e) => {
              e.stopPropagation();
              onDeleteItem(folder.id, true);
              setShowMenu(undefined);
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

export function FileItem({
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
  const [showMenu, setShowMenu] = useState<undefined | number>();
  const [newFileName, setNewFileName] = useState(file.name);

  const isEditing =
    editingItem && editingItem.id === file.id && !editingItem.isFolder;

  const fileItemRef = useRef<HTMLDivElement>(null);
  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    const xPos =
      e.clientX - fileItemRef.current?.getBoundingClientRect().left! - 40;
    setShowMenu(xPos);
  };

  useEffect(() => {
    document.addEventListener("click", (e) => {
      if (fileItemRef.current?.contains(e.target as Node)) {
        return;
      }
      setShowMenu(undefined);
    });
    document.addEventListener("contextmenu", (e) => {
      if (fileItemRef.current?.contains(e.target as Node)) {
        return;
      }
      setShowMenu(undefined);
    });
    return () => {
      document.removeEventListener("click", () => {});
      document.removeEventListener("contextmenu", () => {});
    };
  }, [showMenu]);

  const startEditing = () => {
    setEditingItem({ id: file.id, name: file.name, isFolder: false });
    setNewFileName(file.name);
    setShowMenu(undefined);
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
      ref={fileItemRef}
      key={file.id}
      className="flex items-center w-full justify-between p-2 hover:bg-background-100 cursor-pointer relative"
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
        <div
          className="absolute bg-white max-w-40 border rounded shadow py-1 right-0 top-full mt-1 z-50"
          style={{ left: showMenu }}
        >
          <button
            className="block w-full text-left px-4 py-2 hover:bg-background-100 text-sm"
            onClick={(e) => {
              e.stopPropagation();
              onDownloadItem(file.document_id);
              setShowMenu(undefined);
            }}
          >
            Download
          </button>
          <button
            className="block w-full text-left px-4 py-2 hover:bg-background-100 text-sm"
            onClick={(e) => {
              e.stopPropagation();
              startEditing();
            }}
          >
            Rename
          </button>
          <button
            className="block w-full text-left px-4 py-2 hover:bg-background-100 text-sm"
            onClick={(e) => {
              e.stopPropagation();
              onMoveItem(file.id);
              setShowMenu(undefined);
            }}
          >
            Moveewsd
          </button>
          <button
            className="block w-full text-left px-4 py-2 hover:bg-background-100 text-sm text-red-600"
            onClick={(e) => {
              e.stopPropagation();
              onDeleteItem(file.id, false);
              setShowMenu(undefined);
            }}
          >
            Delete
          </button>
        </div>
      )}
    </div>
  );
}
