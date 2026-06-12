"use client";

import React, { useMemo } from "react";
import Link from "next/link";
import { ChatSessionMorePopup } from "@/components/sidebar/ChatSessionMorePopup";
import { useProjectsContext } from "@/providers/ProjectsContext";
import { ChatSession } from "@/app/app/interfaces";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import { useAgents } from "@/lib/agents/hooks";
import { formatRelativeTime } from "@/app/app/components/projects/project_utils";
import { Card, Text } from "@opal/components";
import { cn } from "@opal/utils";
import { UNNAMED_CHAT } from "@/lib/constants";
import { SvgBubbleText, SvgSimpleLoader } from "@opal/icons";

export default function ProjectChatSessionList() {
  const {
    currentProjectDetails,
    currentProjectId,
    refreshCurrentProjectDetails,
    isLoadingProjectDetails,
  } = useProjectsContext();
  const { agents } = useAgents();
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
    <div className="flex flex-col gap-6 mx-auto">
      <div />

      <div>
        <div className="px-3 py-2">
          <Text as="p" font="secondary-body" color="text-02">
            Recent Chats
          </Text>
        </div>

        {isLoadingProjectDetails && !currentProjectDetails ? (
          <SvgSimpleLoader className="mx-4" />
        ) : projectChats.length === 0 ? (
          <Card rounding="md" border="dashed" background="none" padding="sm">
            <div className="p-1">
              <Text as="p" font="secondary-body" color="text-02">
                No chats yet.
              </Text>
            </div>
          </Card>
        ) : (
          <div className="flex flex-col gap-2">
            {projectChats.map((chat) => (
              <Link
                key={chat.id}
                href={{ pathname: "/app", query: { chatId: chat.id } }}
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
                        const personaIdToFeatured =
                          currentProjectDetails?.persona_id_to_is_featured ||
                          {};
                        const isFeatured = personaIdToFeatured[chat.persona_id];
                        if (isFeatured === false) {
                          const agent = agents.find(
                            (a) => a.id === chat.persona_id
                          );
                          if (agent) {
                            return (
                              <div className="h-full pt-1">
                                <AgentAvatar agent={agent} size={18} />
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
                            font="main-ui-body"
                            color="text-03"
                            nowrap
                            maxLines={1}
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
                        font="secondary-body"
                        color="text-03"
                        nowrap
                        maxLines={1}
                      >
                        {`Last message ${formatRelativeTime(chat.time_updated)}`}
                      </Text>
                    </div>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
