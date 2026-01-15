"use client";

import React, { useMemo, useCallback } from "react";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { Card } from "@/components/ui/card";
import { useAppRouter } from "@/hooks/appNavigation";
import IconButton from "@/refresh-components/buttons/IconButton";
import Truncated from "@/refresh-components/texts/Truncated";
import type { IconProps } from "@opal/types";
import { usePinnedAgents } from "@/hooks/useAgents";
import { cn, noProp } from "@/lib/utils";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { checkUserOwnsAssistant } from "@/lib/assistants/utils";
import { useUser } from "@/components/user/UserProvider";
import {
  SvgActions,
  SvgBarChart,
  SvgBubbleText,
  SvgEdit,
  SvgPin,
  SvgPinned,
  SvgUser,
} from "@opal/icons";
interface IconLabelProps {
  icon: React.FunctionComponent<IconProps>;
  children: string;
}

function IconLabel({ icon: Icon, children }: IconLabelProps) {
  return (
    <div className="flex flex-row items-center gap-1">
      <Icon className="stroke-text-03 w-3 h-3" />
      <Text as="p" text03 secondaryBody>
        {children}
      </Text>
    </div>
  );
}

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

  // Start chat and auto-pin unpinned agents to the sidebar
  const handleStartChat = useCallback(() => {
    if (!pinned) {
      togglePinnedAgent(agent, true);
    }
    route({ agentId: agent.id });
  }, [pinned, togglePinnedAgent, agent, route]);

  return (
    <Card
      className="group/AgentCard"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div
        className="flex flex-col w-full text-left cursor-pointer"
        onClick={handleStartChat}
      >
        {/* Main Body */}
        <div className="flex flex-col items-center gap-1 p-1">
          <div className="flex flex-row items-center w-full gap-1">
            <div className="flex flex-row items-center w-full p-1.5 gap-1.5">
              <div className="px-0.5">
                <AgentAvatar agent={agent} size={18} />
              </div>
              <Truncated mainContentBody className="flex-1">
                {agent.name}
              </Truncated>
            </div>
            <div className={cn("flex flex-row p-0.5 items-center")}>
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
                    router.push(`/chat/agents/edit/${agent.id}` as Route)
                  )}
                  tooltip="Edit Agent"
                  className="hidden group-hover/AgentCard:flex"
                />
              )}
              <IconButton
                icon={pinned ? SvgPinned : SvgPin}
                tertiary
                onClick={noProp(() => togglePinnedAgent(agent, !pinned))}
                tooltip={pinned ? "Unpin from Sidebar" : "Pin to Sidebar"}
                transient={hovered && pinned}
                className={cn(!pinned && "hidden group-hover/AgentCard:flex")}
              />
            </div>
          </div>
          <Text
            as="p"
            secondaryBody
            text03
            className="pb-1 px-2 w-full line-clamp-2 truncate whitespace-normal h-[2.2rem] break-words"
          >
            {agent.description}
          </Text>
        </div>

        {/* Footer section - bg-background-tint-01 */}
        <div className="bg-background-tint-01 p-1 flex flex-row items-end justify-between">
          {/* Left side - creator and actions */}
          <div className="flex flex-col gap-1 py-1 px-2">
            <IconLabel icon={SvgUser}>{agent.owner?.email || "Onyx"}</IconLabel>
            <IconLabel icon={SvgActions}>
              {agent.tools.length > 0
                ? `${agent.tools.length} Action${
                    agent.tools.length > 1 ? "s" : ""
                  }`
                : "No Actions"}
            </IconLabel>
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
      </div>
    </Card>
  );
}
