"use client";

import React, { useMemo } from "react";
import Link from "next/link";
import { ChatSessionMorePopup } from "@/components/sidebar/ChatSessionMorePopup";
import { useProjectsContext } from "../../projects/ProjectsContext";
import { ChatSession } from "@/app/chat/interfaces";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import { useAgents } from "@/hooks/useAgents";
import { formatRelativeTime } from "./project_utils";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";
import { UNNAMED_CHAT } from "@/lib/constants";
import ChatSessionSkeleton from "@/refresh-components/skeletons/ChatSessionSkeleton";
import { SvgBubbleText } from "@opal/icons";

export default function ProjectChatSessionList() {
  const {
    currentProjectDetails,
    currentProjectId,
    refreshCurrentProjectDetails,
    isLoadingProjectDetails,
  } = useProjectsContext();
  const { agents: assistants } = useAgents();
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
    <div className="flex flex-col gap-2 px-2 w-full max-w-[800px] mx-auto mt-6">
      <div className="flex items-center pl-2">
        <Text as="p" text02 secondaryBody>
          Recent Chats
        </Text>
      </div>

      {isLoadingProjectDetails && !currentProjectDetails ? (
        <div className="flex flex-col gap-2">
          <ChatSessionSkeleton />
          <ChatSessionSkeleton />
          <ChatSessionSkeleton />
        </div>
      ) : projectChats.length === 0 ? (
        <Text as="p" text02 secondaryBody className="p-2">
          No chats yet.
        </Text>
      ) : (
        <div className="flex flex-col gap-2 max-h-[46vh] overflow-y-auto overscroll-y-none">
          {projectChats.map((chat) => (
            <Link
              key={chat.id}
              href={{ pathname: "/chat", query: { chatId: chat.id } }}
              className="relative flex w-full"
              onMouseEnter={() => setHoveredChatId(chat.id)}
              onMouseLeave={() => setHoveredChatId(null)}
            >
              <div
                className={cn(
                  "w-full rounded-08 py-2 transition-colors p-1.5",
                  hoveredChatId === chat.id && "bg-background-tint-02"
                )}
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
                              <AgentAvatar agent={assistant} size={18} />
                            </div>
                          );
                        }
                      }
                      return (
                        <SvgBubbleText className="h-4 w-4 stroke-text-02" />
                      );
                    })()}
                  </div>
                  <div className="flex flex-col w-full">
                    <div className="flex items-center gap-1 w-full justify-between">
                      <div className="flex items-center gap-1">
                        <Text
                          as="p"
                          text03
                          mainUiBody
                          nowrap
                          className="truncate"
                          title={chat.name}
                        >
                          {chat.name || UNNAMED_CHAT}
                        </Text>
                      </div>
                      <div className="flex items-center">
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
                          isVisible={hoveredChatId === chat.id}
                        />
                      </div>
                    </div>
                    <Text
                      as="p"
                      text03
                      secondaryBody
                      nowrap
                      className="truncate"
                    >
                      Last message {formatRelativeTime(chat.time_updated)}
                    </Text>
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
