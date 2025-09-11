"use client";

import React, { useMemo } from "react";
import Link from "next/link";
import { ChatBubbleIcon } from "@/components/icons/CustomIcons";
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
    <div className="flex flex-col gap-2 p-4 w-full max-w-[800px] mx-auto mt-4">
      <div className="flex items-center gap-2">
        <h2 className="text-base text-onyx-muted">Recent Chats</h2>
      </div>

      {projectChats.length === 0 ? (
        <p className="text-sm text-onyx-muted">No chats yet.</p>
      ) : (
        <div className="flex flex-col gap-2 max-h-[46vh] overflow-y-auto overscroll-y-none pr-1">
          {projectChats.map((chat) => (
            <Link
              key={chat.id}
              href={`/chat?chatId=${encodeURIComponent(chat.id)}`}
              className="group flex justify-between rounded-xl bg-background-background px-1 py-2 hover:bg-accent-background-hovered transition-colors"
            >
              <div className="flex items-center gap-3 min-w-0 w-full">
                <div className="flex h-full w-fit items-start pt-1 pl-1">
                  <ChatBubbleIcon className="h-5 w-5 text-onyx-medium" />
                </div>
                <div className="flex flex-col w-full">
                  <div className="flex items-center gap-1 w-full justify-between">
                    <div className="flex items-center gap-1">
                      <span
                        className="text-lg text-onyx-emphasis truncate"
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
                                    Project files and instructions aren’t
                                    applied here because this chat uses a custom
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
                    <div className="hidden group-hover:block">
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
                  </div>
                  <span className="text-base text-onyx-muted truncate">
                    Last message {formatRelativeTime(chat.time_updated)}
                  </span>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
