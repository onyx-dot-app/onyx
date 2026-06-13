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
import { checkUserOwnsAgent } from "@/lib/agents/utils";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/interfaces/settings";
import {
  updateAgentSharedStatus,
  updateAgentFeaturedStatus,
} from "@/lib/agents/svc";
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
import { CardItemLayout } from "@/layouts/general-layouts";
import { Content } from "@opal/layouts";
import { Interactive } from "@opal/core";
import { Card } from "@/refresh-components/cards";
import { APP_NAME } from "@/lib/brand";
import { useTranslations } from "next-intl";

export interface AgentCardProps {
  agent: MinimalAgent;
}

export default function AgentCard({ agent }: AgentCardProps) {
  const t = useTranslations("appShell.agents");
  const route = useAppRouter();
  const router = useRouter();
  const { pinnedAgents, togglePinnedAgent } = usePinnedAgents();
  const pinned = useMemo(
    () => pinnedAgents.some((pinnedAgent) => pinnedAgent.id === agent.id),
    [agent.id, pinnedAgents]
  );
  const { user, isAdmin, isCurator } = useUser();
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const canUpdateFeaturedStatus = isAdmin || isCurator;
  const isOwnedByUser = checkUserOwnsAgent(user, agent);
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
        businessTier,
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
    [agent.id, canUpdateFeaturedStatus, businessTier, refreshAgent]
  );

  return (
    <>
      <shareAgentModal.Provider>
        <ShareAgentModal
          agentId={agent.id}
          userIds={fullAgent?.users?.map((u) => u.id) ?? []}
          groupIds={fullAgent?.groups ?? []}
          isPublic={fullAgent?.is_public ?? false}
          isFeatured={fullAgent?.is_featured ?? false}
          labelIds={fullAgent?.labels?.map((l) => l.id) ?? []}
          onShare={handleShare}
        />
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
          className="radial-00 hover:shadow-00"
        >
          <div className="flex self-stretch h-24">
            <CardItemLayout
              icon={(props) => <AgentAvatar agent={agent} {...props} />}
              title={agent.name}
              description={agent.description}
              rightChildren={
                <>
                  {isOwnedByUser && businessTier && (
                    // TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved
                    <IconButton
                      icon={SvgBarChart}
                      tertiary
                      onClick={noProp(() =>
                        router.push(`/ee/agents/stats/${agent.id}` as Route)
                      )}
                      tooltip={t("viewStats")}
                      className="hidden group-hover/AgentCard:flex"
                    />
                  )}
                  {isOwnedByUser && (
                    // TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved
                    <IconButton
                      icon={SvgEdit}
                      tertiary
                      onClick={noProp(() =>
                        router.push(`/app/agents/edit/${agent.id}` as Route)
                      )}
                      tooltip={t("editAgent")}
                      className="hidden group-hover/AgentCard:flex"
                    />
                  )}
                  {isOwnedByUser && (
                    // TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved
                    <IconButton
                      icon={SvgShare}
                      tertiary
                      onClick={noProp(() => shareAgentModal.toggle(true))}
                      tooltip={t("shareAgent")}
                      className="hidden group-hover/AgentCard:flex"
                    />
                  )}
                  {/* TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved */}
                  <IconButton
                    icon={pinned ? SvgPinned : SvgPin}
                    tertiary
                    onClick={noProp(() => togglePinnedAgent(agent, !pinned))}
                    tooltip={
                      pinned ? t("unpinFromSidebar") : t("pinToSidebar")
                    }
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
                title={agent.owner?.email || APP_NAME}
                sizePreset="secondary"
                variant="body"
                color="muted"
              />
              <Content
                icon={SvgActions}
                title={
                  agent.tools.length > 0
                    ? t("actionCount", { count: agent.tools.length })
                    : t("noActions")
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
                {t("startChat")}
              </Button>
            </div>
          </div>
        </Card>
      </Interactive.Simple>
    </>
  );
}
