"use client";

import { useNavigation } from "@opal/navigation";
import { createContext, useCallback, useContext, useMemo } from "react";
import { useTranslations } from "next-intl";
import { MinimalAgent } from "@/lib/agents/types";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import { Button, SelectCard, Text, useCreateModal } from "@opal/components";
import { usePinnedAgents } from "@/lib/agents/hooks";
import { noProp } from "@/lib/utils";
import { can } from "@/lib/permissions/resource-actions";
import { useTierAtLeast } from "@/lib/tiers/hooks";
import { Tier } from "@/lib/tiers/types";
import {
  SvgActions,
  SvgBarChart,
  SvgBubbleText,
  SvgEdit,
  SvgPinned,
  SvgShare,
  SvgUser,
} from "@opal/icons";
import { useAppPosition } from "@/lib/navigation/hooks";
import { ShareAgentModal } from "@/lib/agents/components/ShareAgentModal";
import { Content, ContentAction, Section, toast } from "@opal/layouts";
import { Hoverable } from "@opal/core";
import { cn } from "@opal/utils";
import type { IconProps } from "@opal/types";

export interface AgentCardProps {
  agent: MinimalAgent;
  /** Opens this agent's viewer, which the listing renders. */
  onView: () => void;
  /** This agent's viewer is open: the card keeps its focused look under it. */
  viewing?: boolean;
}

// Whether the pin icon below shows the pinned pose. A context, so the icon
// stays one component across both states and its rotation can animate: a
// component per state would remount on every toggle.
const PinnedContext = createContext(false);

/** The upright pin, turned 45° clockwise (slanted) while unpinned. */
function RotatingPinIcon({ className, ...props }: IconProps) {
  const pinned = useContext(PinnedContext);
  return (
    <SvgPinned
      {...props}
      className={cn(
        className,
        "transition-transform duration-200 ease-out motion-reduce:transition-none",
        !pinned && "rotate-45"
      )}
    />
  );
}

export function AgentCard({ agent, onView, viewing = false }: AgentCardProps) {
  const t = useTranslations("agents");
  const appPosition = useAppPosition();
  const navigation = useNavigation();
  const { pinnedAgents, togglePinnedAgent } = usePinnedAgents();
  const pinned = useMemo(
    () => pinnedAgents.some((pinnedAgent) => pinnedAgent.id === agent.id),
    [agent.id, pinnedAgents]
  );
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const shareAgentModal = useCreateModal();

  // A failed pin write reverts the pin; say so rather than fail silently.
  const setPinned = useCallback(
    async (next: boolean) => {
      try {
        await togglePinnedAgent(agent, next);
      } catch {
        toast.error(t("card.pinFailed.message"));
      }
    },
    [togglePinnedAgent, agent, t]
  );

  // Start chat and auto-pin unpinned agents to the sidebar
  const handleStartChat = useCallback(() => {
    if (!pinned) void setPinned(true);
    appPosition.openAgent(agent.id);
  }, [pinned, setPinned, agent, appPosition]);

  const pinButton = (
    <PinnedContext.Provider value={pinned}>
      <Button
        icon={RotatingPinIcon}
        prominence="tertiary"
        size="md"
        onClick={noProp(() => void setPinned(!pinned))}
        tooltip={pinned ? t("card.unpin.tooltip") : t("card.pin.tooltip")}
      />
    </PinnedContext.Provider>
  );

  return (
    <>
      <shareAgentModal.Provider>
        {/* Saved agents persist sharing inside the dialog itself */}
        <ShareAgentModal agentId={agent.id} />
      </shareAgentModal.Provider>

      <SelectCard
        state="filled"
        padding={0}
        onClick={onView}
        interaction={viewing ? "hover" : undefined}
        // Lets the catalog's arrow keys find the cards.
        data-agent-card=""
      >
        <Hoverable.Root group="AgentCard" height="full">
          {/* The card has a fixed height; the footer sits at its bottom. */}
          <Section justifyContent="between" alignItems="stretch" gap={0}>
            <Section gap={1} padding={1} alignItems="stretch" height="fit">
              <ContentAction
                font="main-content-emphasis"
                icon={(props) => <AgentAvatar agent={agent} {...props} />}
                title={agent.name}
                titleMaxLines={1}
                padding={1.5}
                rightChildren={
                  <Section
                    flexDirection="row"
                    width="fit"
                    height="fit"
                    gap={0}
                    padding={1}
                  >
                    {can(agent, "view_stats") && businessTier && (
                      <Hoverable.Item group="AgentCard">
                        <Button
                          icon={SvgBarChart}
                          prominence="tertiary"
                          size="md"
                          onClick={noProp(() =>
                            navigation.go(`/ee/agents/stats/${agent.id}`)
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
                          size="md"
                          onClick={noProp(() =>
                            navigation.go(`/app/agents/edit/${agent.id}`)
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
                          size="md"
                          onClick={noProp(() => shareAgentModal.toggle(true))}
                          tooltip={t("card.share.tooltip")}
                        />
                      </Hoverable.Item>
                    )}
                    {/* A pinned agent shows its pin at rest; an unpinned one only
                        offers the action on hover. One wrapper either way, so the pin
                        keeps its element and its rotation animates. */}
                    <Hoverable.Item group="AgentCard" revealed={pinned}>
                      {pinButton}
                    </Hoverable.Item>
                  </Section>
                }
              />
              {agent.description && (
                <div className="px-2">
                  <Text
                    as="p"
                    font="secondary-body"
                    color="text-03"
                    maxLines={2}
                  >
                    {agent.description}
                  </Text>
                </div>
              )}
            </Section>

            {/* Footer section - bg-background-tint-01 */}
            <Section
              flexDirection="row"
              justifyContent="between"
              alignItems="end"
              height="fit"
              gap={1}
              padding={1}
              className="bg-background-tint-01"
            >
              {/* Left side - creator and actions. Section pads evenly, so
                  the uneven padding sits on a plain wrapper. */}
              <div className="px-2 py-1">
                <Section alignItems="stretch" width="auto" height="fit" gap={1}>
                  <Content
                    font="secondary-body"
                    icon={SvgUser}
                    title={agent.owner?.email || "Onyx"}
                    titleColor="text-03"
                  />
                  <Content
                    font="secondary-body"
                    icon={SvgActions}
                    title={t("card.actionsCount.label", {
                      count: agent.tools.length,
                    })}
                    titleColor="text-03"
                  />
                </Section>
              </div>

              {/* Right side - Start Chat button */}
              <Button
                prominence="tertiary"
                rightIcon={SvgBubbleText}
                onClick={noProp(handleStartChat)}
              >
                {t("card.startChat.label")}
              </Button>
            </Section>
          </Section>
        </Hoverable.Root>
      </SelectCard>
    </>
  );
}
