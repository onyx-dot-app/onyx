"use client";

import React, { useEffect, useRef } from "react";
import { MinimalAgent } from "@/lib/agents/types";
import { usePinnedAgents, useActiveAgent } from "@/lib/agents/hooks";
import { noProp } from "@/lib/utils";
import { SidebarTab, Button, Modal, Text } from "@opal/components";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import useOnMount from "@/hooks/useOnMount";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import { SvgX, SvgOnyxOctagon } from "@opal/icons";
import { Hoverable } from "@opal/core";
import useAppFocus from "@/hooks/useAppFocus";
import { useUser } from "@/providers/UserProvider";

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

export function AgentButton({ agent }: AgentButtonProps) {
  const activeAgent = useActiveAgent();
  const { pinnedAgents, togglePinnedAgent } = usePinnedAgents();
  const isActuallyPinned = pinnedAgents.some((a) => a.id === agent.id);
  const isCurrentAgent = activeAgent?.id === agent.id;
  const appFocus = useAppFocus();

  // # NOTE (@raunakab):
  //
  // The agent-tab should be highlighted in many cases, even in cases in which the agent-tab was not explicitly clicked.
  //
  // For example, say you're in a chat-session that was started with `Agent XYZ`.
  // In that situation, the chat-tab *AND* the `Agent XYZ`-tab should be highlighted.
  //
  // Another example, say you have the "Always Start with an Agent" setting enabled (via Admin -> Chat Preferences -> Advanced Options -> Always Start with an Agent).
  // If you then navigate to "New Session" (`/app`), the new-session-tab *AND* the `Agent XYZ`-tab should both be highlighted.
  const agentButtonShouldBeHighlighted =
    appFocus.isAgent() ||
    appFocus.isNewSession() ||
    appFocus.isChat() ||
    appFocus.isSharedChat();

  async function handleClick() {
    if (isActuallyPinned) return;
    await togglePinnedAgent(agent, true);
  }

  return (
    <SortableItem id={agent.id}>
      <Hoverable.Root group="AgentButton/unpin-agent">
        <SidebarTab
          key={agent.id}
          icon={() => <AgentAvatar agent={agent} />}
          href={`/app?agentId=${agent.id}`}
          onClick={handleClick}
          selected={agentButtonShouldBeHighlighted && isCurrentAgent}
          rightChildren={
            // Hide unpin button for current agent since auto-pin would immediately re-pin
            !isCurrentAgent && (
              <Hoverable.Item group="AgentButton/unpin-agent">
                <Button
                  icon={SvgX}
                  prominence="internal"
                  size="sm"
                  onClick={noProp(() => togglePinnedAgent(agent, false))}
                  tooltip="Unpin Agent"
                />
              </Hoverable.Item>
            )
          }
        >
          {agent.name}
        </SidebarTab>
      </Hoverable.Root>
    </SortableItem>
  );
}

export function NoAgentModal() {
  const { isAdmin } = useUser();

  return (
    <Modal open>
      <Modal.Content width="sm" height="sm">
        <Modal.Header icon={SvgOnyxOctagon} title="No Agent Available" />
        <Modal.Body gap={2}>
          <Text as="p" color="text-03">
            You currently have no agent configured.
          </Text>
          {isAdmin ? (
            <Text as="p" color="text-03">
              As an administrator, you can create a new agent by visiting the
              admin panel.
            </Text>
          ) : (
            <Text as="p" color="text-03">
              Please contact your administrator to configure an agent for you.
            </Text>
          )}
        </Modal.Body>
        {isAdmin && (
          <Modal.Footer>
            <Button href="/admin/agents" prominence="secondary">
              Go to Admin Panel
            </Button>
          </Modal.Footer>
        )}
      </Modal.Content>
    </Modal>
  );
}
