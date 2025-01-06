import React, { useState, useEffect } from "react";
import { Folder } from "lucide-react";

interface Folder {
  id: number | null;
  name: string;
}

interface MoveFileModalProps {
  isOpen: boolean;
  onClose: () => void;
  onMove: (destinationFolderId: number | null) => void;
  fileName: string;
  currentFolderId: number | null;
}

export function MoveFileModal({
  isOpen,
  onClose,
  onMove,
  fileName,
  currentFolderId,
}: MoveFileModalProps) {
  const [folders, setFolders] = useState<Folder[]>([]);
  const [selectedFolder, setSelectedFolder] = useState<Folder | null>(null);

  useEffect(() => {
    if (isOpen) {
      const loadFolders = async () => {
        const res = await fetch("/api/user/folder");
        const data = await res.json();
        setFolders(data);
      };
      loadFolders();
    }
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 w-96">
        <h2 className="text-xl font-semibold mb-4">
          Move &quot;{fileName}&quot;
        </h2>
        <div className="mb-4">
          <span className="font-medium">Choose a folder:</span>
          <div className="max-h-60 overflow-y-auto mt-2 border rounded">
            {folders.map((folder) => (
              <div
                key={folder.id}
                className="flex items-center justify-between py-2 px-3 hover:bg-background-100 cursor-pointer"
                onClick={() => setSelectedFolder(folder)}
              >
                <div className="flex items-center">
                  <Folder className="mr-2 h-5 w-5" />
                  <span>{folder.name}</span>
                  {folder.id === currentFolderId && (
                    <span className="text-sm my-auto ml-2 text-text-500">
                      (Current folder)
                    </span>
                  )}
                </div>
                <div
                  className={`w-4 h-4 rounded-full border ${
                    selectedFolder?.id === folder.id
                      ? "bg-blue-600 border-blue-600"
                      : "border-blue-300 border-2"
                  }`}
                />
              </div>
            ))}
            <div
              className="flex items-center justify-between py-2 px-3 hover:bg-background-100 cursor-pointer"
              onClick={() => setSelectedFolder({ id: null, name: "Root" })}
            >
              <div className="flex items-center">
                <Folder className="mr-2 h-5 w-5" />
                <span>Root</span>
              </div>
              <div
                className={`w-4 h-4 rounded-full border ${
                  selectedFolder?.id === null
                    ? "bg-blue-600 border-blue-600"
                    : "border-blue-300 border-2"
                }`}
              />
            </div>
          </div>
        </div>
        <div className="flex justify-end space-x-2">
          <button
            className="px-4 py-2 cursor-pointer text-text-600 hover:bg-background-100 rounded"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            className={`px-4 py-2 text-white rounded ${
              selectedFolder
                ? "bg-blue-600 hover:bg-blue-700 cursor-pointer"
                : "bg-blue-400 cursor-not-allowed"
            }`}
            onClick={() => selectedFolder && onMove(selectedFolder.id)}
            disabled={!selectedFolder}
          >
            Move
          </button>
        </div>
      </div>
    </div>
  );
}
