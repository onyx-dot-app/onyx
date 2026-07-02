"use client";

import { useMemo, useCallback } from "react";
import { MinimalAgent } from "@/lib/agents/types";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import { Button } from "@opal/components";
import { useAppRouter } from "@/hooks/appNavigation";
import IconButton from "@/refresh-components/buttons/IconButton";
import { usePinnedAgents, useAgent } from "@/lib/agents/hooks";
import { noProp } from "@/lib/utils";
import { cn } from "@opal/utils";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { checkUserCanEditAgent, checkUserOwnsAgent } from "@/lib/agents/utils";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";
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
import { CardItemLayout } from "@/layouts/general-layouts";
import { Content } from "@opal/layouts";
import { Interactive } from "@opal/core";
import { Card } from "@/refresh-components/cards";

export interface AgentCardProps {
  agent: MinimalAgent;
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
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const isOwnedByUser = checkUserOwnsAgent(user, agent);
  const canEditAgent = checkUserCanEditAgent(user, agent);
  const shareAgentModal = useCreateModal();
  const agentViewerModal = useCreateModal();
  const { agent: fullAgent } = useAgent(agent.id);

  // Start chat and auto-pin unpinned agents to the sidebar
  const handleStartChat = useCallback(() => {
    if (!pinned) {
      togglePinnedAgent(agent, true);
    }
    route({ agentId: agent.id });
  }, [pinned, togglePinnedAgent, agent, route]);

  return (
    <>
      <shareAgentModal.Provider>
        {/* Saved agents persist sharing inside the dialog itself */}
        <ShareAgentModal agentId={agent.id} />
      </shareAgentModal.Provider>

      <agentViewerModal.Provider>
        {fullAgent && <AgentViewerModal agent={fullAgent} />}
      </agentViewerModal.Provider>

      <Interactive.Simple
        onClick={() => agentViewerModal.toggle(true)}
        group="group/AgentCard"
      >
        <Card
          padding={0}
          gap={0}
          height="full"
          className="radial-00 hover:shadow-box-00"
        >
          <div className="flex self-stretch h-24">
            <CardItemLayout
              icon={(props) => <AgentAvatar agent={agent} {...props} />}
              title={agent.name}
              description={agent.description}
              rightChildren={
                <>
                  {isOwnedByUser &&
                    businessTier && (
                      // TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved
                      <IconButton
                        icon={SvgBarChart}
                        tertiary
                        onClick={noProp(() =>
                          router.push(`/ee/agents/stats/${agent.id}` as Route)
                        )}
                        tooltip="View Agent Stats"
                        className="hidden group-hover/AgentCard:flex"
                      />
                    )}
                  {canEditAgent && (
                    // TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved
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
                  {canEditAgent && (
                    // TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved
                    <IconButton
                      icon={SvgShare}
                      tertiary
                      onClick={noProp(() => shareAgentModal.toggle(true))}
                      tooltip="Share Agent"
                      className="hidden group-hover/AgentCard:flex"
                    />
                  )}
                  {/* TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved */}
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
              <Content
                icon={SvgUser}
                title={agent.owner?.email || "Onyx"}
                sizePreset="secondary"
                variant="body"
                color="muted"
              />
              <Content
                icon={SvgActions}
                title={
                  agent.tools.length > 0
                    ? `${agent.tools.length} Action${
                        agent.tools.length > 1 ? "s" : ""
                      }`
                    : "No Actions"
                }
                sizePreset="secondary"
                variant="body"
                color="muted"
              />
            </div>

            {/* Right side - Start Chat button */}
            <div className="p-0.5">
              <Button
                prominence="tertiary"
                rightIcon={SvgBubbleText}
                onClick={noProp(handleStartChat)}
              >
                Start Chat
              </Button>
            </div>
          </div>
        </Card>
      </Interactive.Simple>
    </>
  );
}
