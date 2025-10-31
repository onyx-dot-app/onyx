"use client";

import React, { useMemo } from "react";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import AgentIcon from "@/refresh-components/AgentIcon";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import SvgBubbleText from "@/icons/bubble-text";
import { Card } from "@/components/ui/card";
import { useAppRouter } from "@/hooks/appNavigation";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgPin from "@/icons/pin";
import Truncated from "@/refresh-components/texts/Truncated";
import { SvgProps } from "@/icons";
import SvgUser from "@/icons/user";
import SvgActions from "@/icons/actions";
import { useAgentsContext } from "./contexts/AgentsContext";
import { cn } from "@/lib/utils";
import SvgEdit from "@/icons/edit";
import { useRouter } from "next/navigation";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { checkUserOwnsAssistant } from "@/lib/assistants/utils";
import { useUser } from "@/components/user/UserProvider";
import SvgBarChart from "@/icons/bar-chart";

interface IconLabelProps {
  icon: React.FunctionComponent<SvgProps>;
  children: string;
}

function IconLabel({ icon: Icon, children }: IconLabelProps) {
  return (
    <div className="flex flex-row items-center gap-1">
      <Icon className="stroke-text-03 w-3 h-3" />
      <Text text03 secondaryBody>
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
  const { pinnedAgents, togglePinnedAgent } = useAgentsContext();
  const pinned = useMemo(
    () => pinnedAgents.some((pinnedAgent) => pinnedAgent.id === agent.id),
    [agent.id, pinnedAgents]
  );
  const { user } = useUser();
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();
  const isOwnedByUser = checkUserOwnsAssistant(user, agent);

  return (
    <Card className="flex flex-col group/AgentCard">
      {/* Main Body */}
      <div className="flex flex-col items-center gap-1 p-1">
        <div className="flex flex-row items-center w-full gap-1">
          <div className="flex flex-row items-center w-full p-1.5 gap-1.5">
            <div className="px-0.5">
              <AgentIcon agent={agent} size={18} />
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
                onClick={() => router.push(`/assistants/stats/${agent.id}`)}
                tooltip="View Agent Stats"
                className="hidden group-hover/AgentCard:flex"
              />
            )}
            {isOwnedByUser && (
              <IconButton
                icon={SvgEdit}
                tertiary
                onClick={() => router.push(`/assistants/edit/${agent.id}`)}
                tooltip="Edit Agent"
                className="hidden group-hover/AgentCard:flex"
              />
            )}
            <IconButton
              icon={SvgPin}
              tertiary
              onClick={() => togglePinnedAgent(agent, !pinned)}
              tooltip={pinned ? "Unpin Agent" : "Pin Agent"}
              transient={pinned}
              className={cn(!pinned && "hidden group-hover/AgentCard:flex")}
            />
          </div>
        </div>
        <Text text03 className="pb-1 px-2 w-full">
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
            onClick={() => route({ agentId: agent.id })}
          >
            Start Chat
          </Button>
        </div>
      </div>
    </Card>
  );
}
