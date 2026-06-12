"use client";

import React, { useMemo } from "react";
import { ProjectChatMorePopup } from "@/sections/projects/ProjectChatMorePopup";
import { useProjectsContext } from "@/providers/ProjectsContext";
import { ChatSession } from "@/app/app/interfaces";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import { useAgents } from "@/lib/agents/hooks";
import { Card, LineItemButton, Text } from "@opal/components";
import { Hoverable, Interactive } from "@opal/core";
import { UNNAMED_CHAT } from "@/lib/constants";
import { SvgBubbleText, SvgSimpleLoader } from "@opal/icons";
import { timeAgo } from "@opal/time";
import { Content } from "@opal/layouts";

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
          projectChats.map((chat) => {
            const personaIdToFeatured =
              currentProjectDetails?.persona_id_to_is_featured || {};
            const isFeatured = personaIdToFeatured[chat.persona_id];
            const agent =
              isFeatured === false
                ? agents.find((a) => a.id === chat.persona_id)
                : undefined;
            const icon = agent
              ? () => <AgentAvatar agent={agent} size={18} />
              : SvgBubbleText;

            return (
              <div key={chat.id} className="px-1">
                <Hoverable.Root group={chat.id} width="full">
                  <LineItemButton
                    href={`/app?chatId=${chat.id}`}
                    group={chat.id}
                    icon={icon}
                    title={chat.name || UNNAMED_CHAT}
                    description={`Last message ${timeAgo(chat.time_updated) ?? ""}`}
                    sizePreset="main-ui"
                    rightChildren={
                      <Hoverable.Item group={chat.id} variant="appear-on-hover">
                        <ProjectChatMorePopup
                          chatSession={chat}
                          projectId={currentProjectId}
                          isRenamingChat={isRenamingChat === chat.id}
                          setIsRenamingChat={(value) =>
                            setIsRenamingChat(value ? chat.id : null)
                          }
                          search={false}
                          afterDelete={refreshCurrentProjectDetails}
                          afterMove={refreshCurrentProjectDetails}
                          afterRemoveFromProject={refreshCurrentProjectDetails}
                          iconSize={20}
                          isVisible
                        />
                      </Hoverable.Item>
                    }
                  />
                </Hoverable.Root>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
