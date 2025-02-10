import React from "react";
import { Button } from "@/components/ui/button";

interface DeleteEntityModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  entityType: "file" | "folder";
  entityName: string;
}

export const DeleteEntityModal: React.FC<DeleteEntityModalProps> = ({
  isOpen,
  onClose,
  onConfirm,
  entityType,
  entityName,
}) => {
  if (!isOpen) return null;

  return (
    <div className="fixed z-[10000] inset-0 bg-black bg-opacity-50 flex items-center justify-center">
      <div className="max-w-md w-full bg-white p-6 rounded-lg shadow-lg">
        <h2 className="text-xl font-bold mb-4">Delete {entityType}</h2>
        <p className="mb-6">
          Are you sure you want to delete the {entityType} &quot;{entityName}
          &quot;? This action cannot be undone.
        </p>
        <div className="flex justify-end space-x-4">
          <Button onClick={onClose} variant="outline">
            Cancel
          </Button>
          <Button onClick={onConfirm} variant="destructive">
            Delete
          </Button>
        </div>
      </div>
    </div>
  );
};
