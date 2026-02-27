"use client";

import { useMemo, useCallback } from "react";
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
import {
  checkUserOwnsAssistant,
  updateAgentSharedStatus,
  updateAgentFeaturedStatus,
} from "@/lib/agents";
import { useUser } from "@/providers/UserProvider";
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
import AgentViewerModal from "@/sections/modals/AgentViewerModal";
import { toast } from "@/hooks/useToast";
import { LineItemLayout, CardItemLayout } from "@/layouts/general-layouts";
import { Interactive } from "@opal/core";
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
  const { user, isAdmin, isCurator } = useUser();
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();
  const canUpdateFeaturedStatus = isAdmin || isCurator;
  const isOwnedByUser = checkUserOwnsAssistant(user, agent);
  const shareAgentModal = useCreateModal();
  const agentViewerModal = useCreateModal();
  const { agent: fullAgent, refresh: refreshAgent } = useAgent(agent.id);

  // Start chat and auto-pin unpinned agents to the sidebar
  const handleStartChat = useCallback(() => {
    if (!pinned) {
      togglePinnedAgent(agent, true);
    }
    route({ agentId: agent.id });
  }, [pinned, togglePinnedAgent, agent, route]);

  const handleShare = useCallback(
    async (
      userIds: string[],
      groupIds: number[],
      isPublic: boolean,
      isFeatured: boolean,
      labelIds: number[]
    ) => {
      const shareError = await updateAgentSharedStatus(
        agent.id,
        userIds,
        groupIds,
        isPublic,
        isPaidEnterpriseFeaturesEnabled,
        labelIds
      );

      if (shareError) {
        toast.error(`Failed to share agent: ${shareError}`);
        return;
      }

      if (canUpdateFeaturedStatus) {
        const featuredError = await updateAgentFeaturedStatus(
          agent.id,
          isFeatured
        );
        if (featuredError) {
          toast.error(`Failed to update featured status: ${featuredError}`);
          refreshAgent();
          return;
        }
      }

      refreshAgent();
      shareAgentModal.toggle(false);
    },
    [
      agent.id,
      canUpdateFeaturedStatus,
      isPaidEnterpriseFeaturesEnabled,
      refreshAgent,
    ]
  );

  return (
    <>
      <shareAgentModal.Provider>
        <ShareAgentModal
          agentId={agent.id}
          userIds={fullAgent?.users?.map((u) => u.id) ?? []}
          groupIds={fullAgent?.groups ?? []}
          isPublic={fullAgent?.is_public ?? false}
          isFeatured={fullAgent?.is_default_persona ?? false}
          labelIds={fullAgent?.labels?.map((l) => l.id) ?? []}
          onShare={handleShare}
        />
      </shareAgentModal.Provider>

      <agentViewerModal.Provider>
        {fullAgent && <AgentViewerModal agent={fullAgent} />}
      </agentViewerModal.Provider>

      <Interactive.Base
        onClick={() => agentViewerModal.toggle(true)}
        group="group/AgentCard"
        variant="none"
      >
        <Card
          padding={0}
          gap={0}
          height="full"
          className="radial-00 hover:shadow-00"
        >
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
      </Interactive.Base>
    </>
  );
}
