"use client";

import React, { useMemo, useCallback } from "react";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import Button from "@/refresh-components/buttons/Button";
import { useAppRouter } from "@/hooks/appNavigation";
import IconButton from "@/refresh-components/buttons/IconButton";
import { usePinnedAgents, useAgent } from "@/hooks/useAgents";
import { cn, noProp } from "@/lib/utils";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { checkUserOwnsAssistant, updateAgentSharedStatus } from "@/lib/agents";
import { useUser } from "@/components/user/UserProvider";
import {
  SvgActions,
  SvgBarChart,
  SvgBubbleText,
  SvgEdit,
  SvgPin,
  SvgPinned,
  SvgShare,
  SvgUser,
} from "@opal/icons";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import ShareAgentModal from "@/sections/modals/ShareAgentModal";
import { usePopup } from "@/components/admin/connectors/Popup";
import { LineItemLayout, CardItemLayout } from "@/layouts/general-layouts";
import Hoverable from "@/refresh-components/Hoverable";
import { Card } from "@/refresh-components/cards";

export interface AgentCardProps {
  agent: MinimalPersonaSnapshot;
}

export default function AgentCard({ agent }: AgentCardProps) {
  const route = useAppRouter();
  const router = useRouter();
  const { pinnedAgents, togglePinnedAgent } = usePinnedAgents();
  const pinned = useMemo(
    () => pinnedAgents.some((pinnedAgent) => pinnedAgent.id === agent.id),
    [agent.id, pinnedAgents]
  );
  const { user } = useUser();
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();
  const isOwnedByUser = checkUserOwnsAssistant(user, agent);
  const [hovered, setHovered] = React.useState(false);
  const shareAgentModal = useCreateModal();
  const { agent: fullAgent, refresh: refreshAgent } = useAgent(agent.id);
  const { popup, setPopup } = usePopup();

  // Start chat and auto-pin unpinned agents to the sidebar
  const handleStartChat = useCallback(() => {
    if (!pinned) {
      togglePinnedAgent(agent, true);
    }
    route({ agentId: agent.id });
  }, [pinned, togglePinnedAgent, agent, route]);

  // Handle sharing agent
  const handleShare = useCallback(
    async (userIds: string[], groupIds: number[], isPublic: boolean) => {
      const error = await updateAgentSharedStatus(
        agent.id,
        userIds,
        groupIds,
        isPublic,
        isPaidEnterpriseFeaturesEnabled
      );

      if (error) {
        setPopup({
          type: "error",
          message: `Failed to share agent: ${error}`,
        });
      } else {
        // Revalidate the agent data to reflect the changes
        refreshAgent();
        shareAgentModal.toggle(false);
      }
    },
    [agent.id, isPaidEnterpriseFeaturesEnabled, refreshAgent, setPopup]
  );

  return (
    <>
      {popup}

      <shareAgentModal.Provider>
        <ShareAgentModal
          agentId={agent.id}
          userIds={fullAgent?.users?.map((u) => u.id) ?? []}
          groupIds={fullAgent?.groups ?? []}
          isPublic={fullAgent?.is_public ?? false}
          onShare={handleShare}
        />
      </shareAgentModal.Provider>

      <Hoverable
        asChild
        onClick={handleStartChat}
        group="group/AgentCard"
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        nonInteractive
      >
        <Card padding={0} gap={0} height="full">
          <div className="flex self-stretch h-[6rem]">
            <CardItemLayout
              icon={(props) => <AgentAvatar agent={agent} {...props} />}
              title={agent.name}
              description={agent.description}
              rightChildren={
                <>
                  {isOwnedByUser && isPaidEnterpriseFeaturesEnabled && (
                    <IconButton
                      icon={SvgBarChart}
                      tertiary
                      onClick={noProp(() =>
                        router.push(`/ee/assistants/stats/${agent.id}` as Route)
                      )}
                      tooltip="View Agent Stats"
                      className="hidden group-hover/AgentCard:flex"
                    />
                  )}
                  {isOwnedByUser && (
                    <IconButton
                      icon={SvgEdit}
                      tertiary
                      onClick={noProp(() =>
                        router.push(`/app/agents/edit/${agent.id}` as Route)
                      )}
                      tooltip="Edit Agent"
                      className="hidden group-hover/AgentCard:flex"
                    />
                  )}
                  {isOwnedByUser && (
                    <IconButton
                      icon={SvgShare}
                      tertiary
                      onClick={noProp(() => shareAgentModal.toggle(true))}
                      tooltip="Share Agent"
                      className="hidden group-hover/AgentCard:flex"
                    />
                  )}
                  <IconButton
                    icon={pinned ? SvgPinned : SvgPin}
                    tertiary
                    onClick={noProp(() => togglePinnedAgent(agent, !pinned))}
                    tooltip={pinned ? "Unpin from Sidebar" : "Pin to Sidebar"}
                    transient={hovered && pinned}
                    className={cn(
                      !pinned && "hidden group-hover/AgentCard:flex"
                    )}
                  />
                </>
              }
            />
          </div>

          {/* Footer section - bg-background-tint-01 */}
          <div className="bg-background-tint-01 p-1 flex flex-row items-end justify-between w-full">
            {/* Left side - creator and actions */}
            <div className="flex flex-col gap-1 py-1 px-2">
              <LineItemLayout
                icon={SvgUser}
                title={agent.owner?.email || "Onyx"}
                variant="mini"
              />
              <LineItemLayout
                icon={SvgActions}
                title={
                  agent.tools.length > 0
                    ? `${agent.tools.length} Action${
                        agent.tools.length > 1 ? "s" : ""
                      }`
                    : "No Actions"
                }
                variant="mini"
              />
            </div>

            {/* Right side - Start Chat button */}
            <div className="p-0.5">
              <Button
                tertiary
                rightIcon={SvgBubbleText}
                onClick={noProp(handleStartChat)}
              >
                Start Chat
              </Button>
            </div>
          </div>
        </Card>
      </Hoverable>
    </>
  );
}
