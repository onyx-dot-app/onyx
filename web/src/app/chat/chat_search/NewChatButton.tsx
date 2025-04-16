import React from "react";
import { NewChatIcon } from "@/components/icons/icons";

interface NewChatButtonProps {
  onClick: () => void;
}

export function NewChatButton({ onClick }: NewChatButtonProps) {
  return (
    <div className="mb-2">
      <div className="cursor-pointer" onClick={onClick}>
        <div className="group relative flex items-center rounded-lg px-4 py-3 hover:bg-neutral-100 dark:bg-neutral-800 dark:hover:bg-neutral-700">
          <NewChatIcon className="h-5 w-5 text-neutral-600 dark:text-neutral-400" />
          <div className="relative grow overflow-hidden whitespace-nowrap pl-4">
            <div className="text-sm dark:text-neutral-200">New Chat</div>
          </div>
        </div>
      </div>
    </div>
  );
}
