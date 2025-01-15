import React from "react";
import { FiTrash } from "react-icons/fi";
import { Button } from "@/components/ui/button";

interface DeleteAssistantPopoverProps {
  entityName: string;
  onClose: () => void;
  onSubmit: () => void;
}

export function DeleteAssistantPopover({
  entityName,
  onClose,
  onSubmit,
}: DeleteAssistantPopoverProps) {
  return (
    <div className="w-full">
      <p className="text-sm mb-3">
        Are you sure you want to delete assistant <b>{entityName}</b>?
      </p>
      <div className="flex justify-center gap-2">
        <Button variant="secondary" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="destructive" size="sm" onClick={onSubmit}>
          Delete
        </Button>
      </div>
    </div>
  );
}
