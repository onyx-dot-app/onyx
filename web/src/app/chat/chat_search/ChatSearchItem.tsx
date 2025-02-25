import React from "react";
import { MessageSquare } from "lucide-react";
import { ChatSessionSummary } from "./interfaces";

interface ChatSearchItemProps {
  chat: ChatSessionSummary;
  onSelect: (id: string) => void;
}

export function ChatSearchItem({ chat, onSelect }: ChatSearchItemProps) {
  return (
    <li>
      <div className="cursor-pointer" onClick={() => onSelect(chat.id)}>
        <div className="group relative flex flex-col rounded-lg px-4 py-3 hover:bg-neutral-100 dark:hover:bg-neutral-800">
          <div className="flex items-center">
            <MessageSquare className="h-5 w-5 text-neutral-600 dark:text-neutral-400" />
            <div className="relative grow overflow-hidden whitespace-nowrap pl-4">
              <div className="text-sm dark:text-neutral-200">
                {chat.name || "Untitled Chat"}
              </div>
            </div>
            <div className="opacity-0 group-hover:opacity-100 transition-opacity text-xs text-neutral-500 dark:text-neutral-400">
              {new Date(chat.time_created).toLocaleDateString()}
            </div>
          </div>
        </div>
      </div>
    </li>
  );
}
