import React from "react";
import { PlusCircle } from "lucide-react";

interface NewChatButtonProps {
  onClick: () => void;
}

export function NewChatButton({ onClick }: NewChatButtonProps) {
  return (
    <div className="mb-4">
      <div className="cursor-pointer" onClick={onClick}>
        <div className="group relative flex items-center rounded-lg px-4 py-3 bg-gray-50 hover:bg-gray-100 dark:bg-gray-800 dark:hover:bg-gray-700">
          <PlusCircle className="h-6 w-6 text-gray-600 dark:text-gray-400" />
          <div className="relative grow overflow-hidden whitespace-nowrap pl-4">
            <div className="text-sm font-medium dark:text-gray-200">
              New chat
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
