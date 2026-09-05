"use client";

import { useMemo, useCallback } from "react";
import { useTranslations } from "next-intl";
import { MinimalAgent } from "@/lib/agents/types";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import { Button } from "@opal/components";
import { usePinnedAgents } from "@/lib/agents/hooks";
import { noProp } from "@/lib/utils";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { can } from "@/lib/permissions/resource-actions";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";
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
import { useCreateModal } from "@opal/components";
import { useAppPosition } from "@/lib/position/hooks";
import { ShareAgentModal } from "@/lib/agents/components";
import { CardItemLayout } from "@/layouts/general-layouts";
import { Content } from "@opal/layouts";
import { Hoverable, Interactive } from "@opal/core";
import { Card } from "@/refresh-components/cards";

export interface AgentCardProps {
  agent: MinimalAgent;
  /** Opens this agent's viewer, which the listing renders. */
  onView: () => void;
}

export default function AgentCard({ agent, onView }: AgentCardProps) {
  const t = useTranslations("agents");
  const appPosition = useAppPosition();
  const router = useRouter();
  const { pinnedAgents, togglePinnedAgent } = usePinnedAgents();
  const pinned = useMemo(
    () => pinnedAgents.some((pinnedAgent) => pinnedAgent.id === agent.id),
    [agent.id, pinnedAgents]
  );
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const shareAgentModal = useCreateModal();

  // Start chat and auto-pin unpinned agents to the sidebar
  const handleStartChat = useCallback(() => {
    if (!pinned) {
      togglePinnedAgent(agent, true);
    }
    appPosition.openAgent(agent.id);
  }, [pinned, togglePinnedAgent, agent, appPosition]);

  // Declared once because it renders both bare and wrapped, depending on `pinned`.
  const pinButton = (
    <Button
      icon={pinned ? SvgPinned : SvgPin}
      prominence="tertiary"
      onClick={noProp(() => togglePinnedAgent(agent, !pinned))}
      tooltip={pinned ? t("card.unpin.tooltip") : t("card.pin.tooltip")}
    />
  );

  return (
    <>
      <shareAgentModal.Provider>
        {/* Saved agents persist sharing inside the dialog itself */}
        <ShareAgentModal agentId={agent.id} />
      </shareAgentModal.Provider>

      <Interactive.Simple onClick={onView} group="group/AgentCard">
        <Hoverable.Root group="AgentCard" height="full">
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
                    {can(agent, "view_stats") && businessTier && (
                      <Hoverable.Item group="AgentCard">
                        <Button
                          icon={SvgBarChart}
                          prominence="tertiary"
                          onClick={noProp(() =>
                            router.push(`/ee/agents/stats/${agent.id}` as Route)
                          )}
                          tooltip={t("card.viewStats.tooltip")}
                        />
                      </Hoverable.Item>
                    )}
                    {can(agent, "edit") && (
                      <Hoverable.Item group="AgentCard">
                        <Button
                          icon={SvgEdit}
                          prominence="tertiary"
                          onClick={noProp(() =>
                            router.push(`/app/agents/edit/${agent.id}` as Route)
                          )}
                          tooltip={t("card.edit.tooltip")}
                        />
                      </Hoverable.Item>
                    )}
                    {can(agent, "share") && (
                      <Hoverable.Item group="AgentCard">
                        <Button
                          icon={SvgShare}
                          prominence="tertiary"
                          onClick={noProp(() => shareAgentModal.toggle(true))}
                          tooltip={t("card.share.tooltip")}
                        />
                      </Hoverable.Item>
                    )}
                    {/* A pinned agent shows its pin at rest; an unpinned one
                      only offers the action on hover. */}
                    {pinned ? (
                      pinButton
                    ) : (
                      <Hoverable.Item group="AgentCard">
                        {pinButton}
                      </Hoverable.Item>
                    )}
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
                  title={t("card.actionsCount.label", {
                    count: agent.tools.length,
                  })}
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
                  {t("card.startChat.label")}
                </Button>
              </div>
            </div>
          </Card>
        </Hoverable.Root>
      </Interactive.Simple>
    </>
  );
}
