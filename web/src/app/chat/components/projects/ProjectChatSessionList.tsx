"use client";

import React, { useMemo } from "react";
import Link from "next/link";
import { MessageSquareText } from "lucide-react";
import { ChatSessionMorePopup } from "@/components/sidebar/ChatSessionMorePopup";
import { useProjectsContext } from "../../projects/ProjectsContext";
import { ChatSession } from "@/app/chat/interfaces";

function formatRelativeTime(isoDate: string): string {
  const date = new Date(isoDate);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();

  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 45) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} day${days === 1 ? "" : "s"} ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months} month${months === 1 ? "" : "s"} ago`;
  const years = Math.floor(months / 12);
  return `${years} year${years === 1 ? "" : "s"} ago`;
}

export default function ProjectChatSessionList() {
  const {
    currentProjectDetails,
    currentProjectId,
    refreshCurrentProjectDetails,
  } = useProjectsContext();
  const [isRenamingChat, setIsRenamingChat] = React.useState<string | null>(
    null
  );

  const projectChats: ChatSession[] = useMemo(() => {
    console.log("currentProjectDetails", currentProjectDetails);
    const sessions = currentProjectDetails?.project?.chat_sessions || [];
    console.log("sessions", sessions.length);
    return [...sessions].sort(
      (a, b) =>
        new Date(b.time_updated).getTime() - new Date(a.time_updated).getTime()
    );
  }, [currentProjectDetails?.project?.chat_sessions]);

  if (!currentProjectId) return null;

  return (
    <div className="flex flex-col gap-2 p-4 w-[800px] mx-auto mt-6">
      <div className="flex items-center gap-2">
        <h2 className="text-md font-light">Recent Chats</h2>
      </div>

      {projectChats.length === 0 ? (
        <p className="text-sm text-text-400">No chats yet.</p>
      ) : (
        <div className="flex flex-col gap-2 max-h-[46vh] overflow-y-auto overscroll-y-none pr-1">
          {projectChats.map((chat) => (
            <Link
              key={chat.id}
              href={`/chat?chatId=${encodeURIComponent(chat.id)}`}
              className="flex items-center justify-between rounded-xl bg-background-background px-3 py-2 shadow-sm hover:bg-accent-background-hovered transition-colors"
            >
              <div className="flex items-center gap-3 min-w-0">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-background-dark/60 flex-none">
                  <MessageSquareText className="h-5 w-5 text-text-400" />
                </div>
                <div className="flex flex-col overflow-hidden">
                  <span
                    className="text-sm font-medium text-text-darker truncate"
                    title={chat.name}
                  >
                    {chat.name || "Unnamed Chat"}
                  </span>
                  <span className="text-xs text-text-400 truncate">
                    Last message {formatRelativeTime(chat.time_updated)}
                  </span>
                </div>
              </div>
              <div onClick={(e) => e.preventDefault()}>
                <ChatSessionMorePopup
                  chatSession={chat}
                  projectId={currentProjectId}
                  isRenamingChat={isRenamingChat === chat.id}
                  setIsRenamingChat={(value) =>
                    setIsRenamingChat(value ? chat.id : null)
                  }
                  search={false}
                  afterDelete={() => {
                    refreshCurrentProjectDetails();
                  }}
                  afterMove={() => {
                    refreshCurrentProjectDetails();
                  }}
                  afterRemoveFromProject={() => {
                    refreshCurrentProjectDetails();
                  }}
                />
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
