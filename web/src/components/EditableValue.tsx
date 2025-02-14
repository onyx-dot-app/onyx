"use client";

import { useState } from "react";
import { FiEdit2 } from "react-icons/fi";
import { CheckmarkIcon } from "./icons/icons";

export function EditableValue({
  initialValue,
  onSubmit,
  emptyDisplay,
  consistentWidth = true,
}: {
  initialValue: string;
  onSubmit: (value: string) => Promise<boolean>;
  emptyDisplay?: string;
  consistentWidth?: boolean;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [editedValue, setEditedValue] = useState(initialValue);

  if (isOpen) {
    return (
      <div className="my-auto h-full flex">
        <input
          value={editedValue}
          onChange={(e) => {
            setEditedValue(e.target.value);
          }}
          onKeyDown={async (e) => {
            if (e.key === "Enter") {
              const success = await onSubmit(editedValue);
              if (success) {
                setIsOpen(false);
              }
            }
            if (e.key === "Escape") {
              setIsOpen(false);
              onSubmit(initialValue);
            }
          }}
          className="border bg-background-200 border-background-300 rounded py-1 px-1 w-12 h-4 my-auto"
        />
        <div
          onClick={async () => {
            const success = await onSubmit(editedValue);
            if (success) {
              setIsOpen(false);
            }
          }}
          className="cursor-pointer my-auto ml-2"
        >
          <CheckmarkIcon size={16} className="text-green-700" />
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <div
        className="flex my-auto cursor-pointer hover:bg-accent-background-hovered rounded"
        onClick={() => setIsOpen(true)}
      >
        <div className={"flex " + (consistentWidth && " w-6")}>
          <div className="ml-auto my-auto">{initialValue || emptyDisplay}</div>
        </div>
        <div className="cursor-pointer ml-2 my-auto h-4">
          <FiEdit2 size={16} />
        </div>
      </div>
    </div>
  );
}
