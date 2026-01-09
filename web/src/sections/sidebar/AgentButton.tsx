"use client";

import React, { memo } from "react";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { usePinnedAgents, useCurrentAgent } from "@/hooks/useAgents";
import { useAppRouter } from "@/hooks/appNavigation";
import { cn, noProp } from "@/lib/utils";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import IconButton from "@/refresh-components/buttons/IconButton";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import useOnMount from "@/hooks/useOnMount";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import { SvgPin, SvgX } from "@opal/icons";

interface SortableItemProps {
  id: number;
  children?: React.ReactNode;
}

function SortableItem({ id, children }: SortableItemProps) {
  const isMounted = useOnMount();
  const { attributes, listeners, setNodeRef, transform, isDragging } =
    useSortable({ id });

  if (!isMounted) {
    return <div className="flex items-center group">{children}</div>;
  }

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

export interface AgentButtonProps {
  agent: MinimalPersonaSnapshot;
}

const AgentButton = memo(({ agent }: AgentButtonProps) => {
  const route = useAppRouter();
  const currentAgent = useCurrentAgent();
  const { pinnedAgents, togglePinnedAgent } = usePinnedAgents();
  const isActuallyPinned = pinnedAgents.some((a) => a.id === agent.id);
  const isCurrentAgent = currentAgent?.id === agent.id;

  const handleClick = async () => {
    if (!isActuallyPinned) {
      await togglePinnedAgent(agent, true);
    }
    route({ agentId: agent.id });
  };

  return (
    <SortableItem id={agent.id}>
      <div className="flex flex-col w-full h-full">
        <SidebarTab
          key={agent.id}
          leftIcon={() => <AgentAvatar agent={agent} />}
          onClick={handleClick}
          transient={isCurrentAgent}
          rightChildren={
            // Hide unpin button for current agent since auto-pin would immediately re-pin
            isCurrentAgent ? null : (
              <IconButton
                icon={
                  SvgX /* We only show the unpin button for pinned agents */
                }
                internal
                onClick={noProp(() => togglePinnedAgent(agent, false))}
                className={cn("hidden group-hover/SidebarTab:flex")}
                tooltip={"Unpin Agent"}
              />
            )
          }
        >
          {agent.name}
        </SidebarTab>
      </div>
    </SortableItem>
  );
});
AgentButton.displayName = "AgentButton";

export default AgentButton;
