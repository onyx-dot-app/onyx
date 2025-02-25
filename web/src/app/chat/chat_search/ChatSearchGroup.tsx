import React from "react";
import { ChatSearchItem } from "./ChatSearchItem";
import { ChatSessionSummary } from "./api/interfaces";

interface ChatSearchGroupProps {
  title: string;
  chats: ChatSessionSummary[];
  onSelectChat: (id: string) => void;
}

export function ChatSearchGroup({
  title,
  chats,
  onSelectChat,
}: ChatSearchGroupProps) {
  return (
    <div className="mb-4">
      {/* Sticky date header */}
      <div className="sticky -top-1 mt-1 z-10 bg-[#fff]/90 dark:bg-gray-800/90  py-2 px-4  px-4">
        <div className="text-xs font-medium leading-4 text-gray-600 dark:text-gray-400">
          {title}
        </div>
      </div>

      {/* Chat items */}
      <ol>
        {chats.map((chat) => (
          <ChatSearchItem key={chat.id} chat={chat} onSelect={onSelectChat} />
        ))}
      </ol>
    </div>
  );
}
