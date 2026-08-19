"use client";

import React, { memo, useEffect, useRef } from "react";
import { MinimalAgent } from "@/lib/agents/types";
import { usePinnedAgents, useActiveAgent } from "@/lib/agents/hooks";
import { noProp } from "@/lib/utils";
import { cn } from "@opal/utils";
import { SidebarTab } from "@opal/components";
import IconButton from "@/refresh-components/buttons/IconButton";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import useOnMount from "@/hooks/useOnMount";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import { SvgX } from "@opal/icons";

interface SortableItemProps {
  id: number;
  children?: React.ReactNode;
}

function SortableItem({ id, children }: SortableItemProps) {
  const isMounted = useOnMount();
  const { attributes, listeners, setNodeRef, transform, isDragging } =
    useSortable({ id });

  // Releasing a drag still fires a click, and the tab underneath is a link, so
  // the drop navigated. Remember that a drag happened and swallow that one
  // click; the flag clears on the next press, which leaves plain clicks alone.
  const dragged = useRef(false);
  useEffect(() => {
    if (isDragging) dragged.current = true;
  }, [isDragging]);

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
      // Capture phase: these run before the listeners spread above, so dnd-kit
      // still sees the press, and the click never reaches the link.
      onPointerDownCapture={() => {
        dragged.current = false;
      }}
      onClickCapture={(event) => {
        if (!dragged.current) return;
        event.preventDefault();
        event.stopPropagation();
      }}
      className="flex items-center group"
    >
      {children}
    </div>
  );
}

export interface AgentButtonProps {
  agent: MinimalAgent;
}

const AgentButton = memo(({ agent }: AgentButtonProps) => {
  const activeAgent = useActiveAgent();
  const { pinnedAgents, togglePinnedAgent } = usePinnedAgents();
  const isActuallyPinned = pinnedAgents.some((a) => a.id === agent.id);
  const isCurrentAgent = activeAgent?.id === agent.id;

  const handleClick = async () => {
    if (!isActuallyPinned) {
      await togglePinnedAgent(agent, true);
    }
  };

  return (
    <SortableItem id={agent.id}>
      <div className="flex flex-col w-full h-full">
        <SidebarTab
          key={agent.id}
          icon={() => <AgentAvatar agent={agent} />}
          href={`/app?agentId=${agent.id}`}
          onClick={handleClick}
          selected={isCurrentAgent}
          rightChildren={
            // Hide unpin button for current agent since auto-pin would immediately re-pin
            isCurrentAgent ? null : (
              // TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved
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
