"use client";

import React, { memo } from "react";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { useAgentsContext } from "@/refresh-components/contexts/AgentsContext";
import { useAppParams, useAppRouter } from "@/hooks/appNavigation";
import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";
import SvgPin from "@/icons/pin";
import { cn, noProp } from "@/lib/utils";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import IconButton from "@/refresh-components/buttons/IconButton";
import { getAgentIcon } from "@/sections/sidebar/utils";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

interface SortableItemProps {
  id: number;
  children?: React.ReactNode;
}

function SortableItem({ id, children }: SortableItemProps) {
  const { attributes, listeners, setNodeRef, transform, isDragging } =
    useSortable({ id });

  return (
    <div
      ref={setNodeRef}
      style={{
        transform: CSS.Transform.toString(transform),
        ...(isDragging && { zIndex: 1000, position: "relative" as const }),
      }}
      {...attributes}
      {...listeners}
      className="flex items-center group"
    >
      {children}
    </div>
  );
}

interface AgentButtonProps {
  agent: MinimalPersonaSnapshot;
}

function AgentButtonInner({ agent }: AgentButtonProps) {
  const route = useAppRouter();
  const params = useAppParams();
  const { pinnedAgents, togglePinnedAgent } = useAgentsContext();
  const pinned = pinnedAgents.some(
    (pinnedAgent) => pinnedAgent.id === agent.id
  );

  return (
    <SortableItem id={agent.id}>
      <div className="flex flex-col w-full h-full">
        <SidebarTab
          key={agent.id}
          leftIcon={getAgentIcon(agent)}
          onClick={() => route({ agentId: agent.id })}
          active={params(SEARCH_PARAM_NAMES.PERSONA_ID) === String(agent.id)}
          rightChildren={
            <IconButton
              icon={SvgPin}
              internal
              onClick={noProp(() => togglePinnedAgent(agent, !pinned))}
              className={cn(!pinned && "hidden group-hover/SidebarTab:flex")}
            />
          }
        >
          {agent.name}
        </SidebarTab>
      </div>
    </SortableItem>
  );
}

const AgentButton = memo(AgentButtonInner);
export default AgentButton;
