import React from "react";
import { MessageSquare } from "lucide-react";
import { ChatSessionSummary } from "./api/models";

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
            <MessageSquare className="h-6 w-6 text-neutral-600 dark:text-neutral-400" />
            <div className="relative grow overflow-hidden whitespace-nowrap pl-4">
              <div className="text-sm dark:text-neutral-200">
                {chat.name || "Untitled Chat"}
              </div>
            </div>
          </div>

          {/* Display search highlights if available */}
          {chat.highlights && chat.highlights.length > 0 && (
            <div className="mt-2 pl-10 text-xs text-neutral-500 dark:text-neutral-400">
              {chat.highlights.map((highlight, index) => (
                <div
                  key={index}
                  className="mb-1 overflow-hidden text-ellipsis line-clamp-2 bg-neutral-50 dark:bg-neutral-900 p-1 rounded [&_mark]:bg-yellow-200 [&_mark]:dark:bg-yellow-700 [&_mark]:dark:text-neutral-100 [&_mark]:px-0.5 [&_mark]:rounded"
                  dangerouslySetInnerHTML={{ __html: highlight }}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </li>
  );
}
