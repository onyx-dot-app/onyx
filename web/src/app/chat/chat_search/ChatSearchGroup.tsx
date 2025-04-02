import React from "react";
import { ChatSearchItem } from "./ChatSearchItem";
import { ChatSessionSummary } from "./interfaces";

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
      <div className="sticky -top-1 mt-1 z-10 bg-[#fff]/90 dark:bg-neutral-800/90  py-2 px-4  px-4">
        <div className="text-xs font-medium leading-4 text-neutral-600 dark:text-neutral-400">
          {title}
        </div>
      </div>

      <ol>
        {chats.map((chat) => (
          <ChatSearchItem key={chat.id} chat={chat} onSelect={onSelectChat} />
        ))}
      </ol>
    </div>
  );
}
