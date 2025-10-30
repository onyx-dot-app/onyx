"use client";

import React, { memo } from "react";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { useAgentsContext } from "@/refresh-components/contexts/AgentsContext";
import { useAppRouter } from "@/hooks/appNavigation";
import SvgPin from "@/icons/pin";
import { cn, noProp } from "@/lib/utils";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import IconButton from "@/refresh-components/buttons/IconButton";
import { getAgentIcon } from "@/sections/sidebar/utils";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import SvgX from "@/icons/x";
import { useActiveSidebarTab } from "@/lib/hooks";

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
  const activeSidebarTab = useActiveSidebarTab();
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
          active={
            typeof activeSidebarTab === "object" &&
            activeSidebarTab.type === "agent" &&
            activeSidebarTab.id === String(agent.id)
          }
          rightChildren={
            <IconButton
              icon={pinned ? SvgX : SvgPin}
              internal
              onClick={noProp(() => togglePinnedAgent(agent, !pinned))}
              className={cn("hidden group-hover/SidebarTab:flex")}
              tooltip={pinned ? "Unpin Agent" : "Pin Agent"}
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
