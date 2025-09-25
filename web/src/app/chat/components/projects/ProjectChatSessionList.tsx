"use client";

import React, { useMemo } from "react";
import Link from "next/link";
import { ChatBubbleIcon } from "@/components/icons/CustomIcons";
import { ChatSessionMorePopup } from "@/components/sidebar/ChatSessionMorePopup";
import { useProjectsContext } from "../../projects/ProjectsContext";
import { ChatSession } from "@/app/chat/interfaces";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { useAssistantsContext } from "@/components/context/AssistantsContext";
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
  const { assistants } = useAssistantsContext();
  const [isRenamingChat, setIsRenamingChat] = React.useState<string | null>(
    null
  );
  const [hoveredChatId, setHoveredChatId] = React.useState<string | null>(null);

  const projectChats: ChatSession[] = useMemo(() => {
    const sessions = currentProjectDetails?.project?.chat_sessions || [];
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
              className="relative flex w-full"
              onMouseEnter={() => setHoveredChatId(chat.id)}
              onMouseLeave={() => setHoveredChatId(null)}
            >
              <div
                className={`w-full rounded-xl bg-background-background px-1 py-2 transition-colors ${hoveredChatId === chat.id ? "bg-accent-background-hovered" : ""}`}
              >
                <div className="flex gap-3 min-w-0 w-full">
                  <div className="flex h-full w-fit pt-1 pl-1">
                    {(() => {
                      const personaIdToDefault =
                        currentProjectDetails?.persona_id_to_is_default || {};
                      const isDefault = personaIdToDefault[chat.persona_id];
                      if (isDefault === false) {
                        const assistant = assistants.find(
                          (a) => a.id === chat.persona_id
                        );
                        if (assistant) {
                          return (
                            <div className="h-full pt-1">
                              <AssistantIcon
                                assistant={assistant}
                                size={18}
                                disableToolip
                              />
                            </div>
                          );
                        }
                      }
                      return (
                        <ChatBubbleIcon className="h-5 w-5 text-onyx-medium" />
                      );
                    })()}
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
                      </div>
                      <div className="flex items-center">
                        {hoveredChatId === chat.id && (
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
                            iconSize={20}
                          />
                        )}
                      </div>
                    </div>
                    <span className="text-base text-onyx-muted truncate">
                      Last message {formatRelativeTime(chat.time_updated)}
                    </span>
                  </div>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
