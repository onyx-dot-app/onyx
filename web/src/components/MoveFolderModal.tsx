import React from "react";
import { Button } from "@/components/ui/button";

interface Folder {
  id: number;
  name: string;
}

interface MoveFolderModalProps {
  isOpen: boolean;
  onClose: () => void;
  onMove: (targetFolderId: number) => void;
  folders: Folder[];
  currentFolderId: number;
}

export const MoveFolderModal: React.FC<MoveFolderModalProps> = ({
  isOpen,
  onClose,
  onMove,
  folders,
  currentFolderId,
}) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center">
      <div className="bg-white p-6 rounded-lg shadow-lg w-96">
        <h2 className="text-xl font-bold mb-4">Move Folder</h2>
        <p className="mb-4">Select a destination folder:</p>
        <div className="max-h-60 overflow-y-auto mb-4">
          {folders
            .filter((folder) => folder.id !== currentFolderId)
            .map((folder) => (
              <Button
                key={folder.id}
                onClick={() => onMove(folder.id)}
                variant="outline"
                className="w-full mb-2 justify-start"
              >
                {folder.name}
              </Button>
            ))}
        </div>
        <div className="flex justify-end">
          <Button onClick={onClose} variant="outline">
            Cancel
          </Button>
        </div>
      </div>
    </div>
  );
};
