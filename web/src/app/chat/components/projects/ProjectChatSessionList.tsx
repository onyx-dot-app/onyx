"use client";

import React, { useMemo } from "react";
import Link from "next/link";
import { MessageSquareText } from "lucide-react";
import { ChatSessionMorePopup } from "@/components/sidebar/ChatSessionMorePopup";
import { useProjectsContext } from "../../projects/ProjectsContext";
import { ChatSession } from "@/app/chat/interfaces";
import { InfoIcon } from "@/components/icons/icons";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { formatRelativeTime } from "./project_utils";

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
                  <div className="flex items-center gap-1 min-w-0">
                    <span
                      className="text-sm font-medium text-text-darker truncate"
                      title={chat.name}
                    >
                      {chat.name || "Unnamed Chat"}
                    </span>
                    {(() => {
                      const personaIdToDefault =
                        currentProjectDetails?.persona_id_to_is_default || {};
                      const isDefault = personaIdToDefault[chat.persona_id];
                      if (isDefault === false) {
                        return (
                          <TooltipProvider>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <div className="flex items-center text-amber-600 dark:text-yellow-500 cursor-default flex-shrink-0">
                                  <InfoIcon
                                    size={14}
                                    className="text-amber-600 dark:text-yellow-500"
                                  />
                                </div>
                              </TooltipTrigger>
                              <TooltipContent side="top" align="center">
                                <p className="max-w-[220px] text-sm">
                                  Project files and instructions aren’t applied
                                  here because this chat uses a custom
                                  assistant.
                                </p>
                              </TooltipContent>
                            </Tooltip>
                          </TooltipProvider>
                        );
                      }
                      return null;
                    })()}
                  </div>
                  <span className="text-xs text-text-400 truncate">
                    Last message {formatRelativeTime(chat.time_updated)}
                  </span>
                </div>
              </div>
              <div
                className="flex items-center gap-2"
                onClick={(e) => e.preventDefault()}
              >
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
