"use client";

import { useCallback, useMemo } from "react";
import { useTranslations } from "next-intl";
import {
  DndContext,
  closestCenter,
  type DragEndEvent,
  type SensorDescriptor,
  type SensorOptions,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { SidebarTab } from "@opal/components";
import { SidebarLayouts } from "@opal/layouts";
import { SidebarLoader } from "@opal/loaders";
import { useNavigation } from "@opal/navigation";
import { SvgOnyxOctagon } from "@opal/icons";
import type { MinimalAgent } from "@/lib/agents/types";
import { AgentButton } from "@/lib/agents/components";
import { useAgents, useActiveAgent, usePinnedAgents } from "@/lib/agents/hooks";
import { useAppPosition } from "@/lib/navigation/hooks";
import { DEFAULT_AGENT_ID } from "@/lib/constants";

// Visible-agents = pinned-agents + current-agent (if current-agent not in pinned-agents)
// OR Visible-agents = pinned-agents (if current-agent in pinned-agents)
function buildVisibleAgents(
  pinnedAgents: MinimalAgent[],
  activeAgent: MinimalAgent | undefined
): [MinimalAgent[], boolean] {
  /* NOTE: The unified agent (id = 0) is not visible in the sidebar,
  so we filter it out. */
  if (!activeAgent)
    return [pinnedAgents.filter((agent) => agent.id !== 0), false];
  const currentAgentIsPinned = pinnedAgents.some(
    (pinnedAgent) => pinnedAgent.id === activeAgent.id
  );
  const visibleAgents = (
    currentAgentIsPinned ? pinnedAgents : [...pinnedAgents, activeAgent]
  ).filter((agent) => agent.id !== 0);

  return [visibleAgents, currentAgentIsPinned];
}

interface AgentsSidebarContentProps {
  sensors: SensorDescriptor<SensorOptions>[];
}

/** The Agents window: the agent gallery link, then pinned agents to reorder. */
export default function AgentsSidebarContent({
  sensors,
}: AgentsSidebarContentProps) {
  const t = useTranslations("sidebar");
  const navigation = useNavigation();
  const appPosition = useAppPosition();
  const { isLoading: isLoadingAgents } = useAgents();
  const activeAgent = useActiveAgent();
  const {
    pinnedAgents,
    updatePinnedAgents,
    isLoading: isLoadingPinnedAgents,
  } = usePinnedAgents();
  const isLoadingAgentList = isLoadingAgents || isLoadingPinnedAgents;

  const [visibleAgents, currentAgentIsPinned] = useMemo(
    () => buildVisibleAgents(pinnedAgents, activeAgent),
    [pinnedAgents, activeAgent]
  );
  const visibleAgentIds = useMemo(
    () => visibleAgents.map((agent) => agent.id),
    [visibleAgents]
  );

  const handleAgentDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over) return;
      if (active.id === over.id) return;

      const activeIndex = visibleAgentIds.findIndex(
        (agentId) => agentId === active.id
      );
      const overIndex = visibleAgentIds.findIndex(
        (agentId) => agentId === over.id
      );

      let newPinnedAgents: MinimalAgent[];

      // The Assistant is excluded: it is the active agent in plain chat but is
      // never in `visibleAgents`, so pinning it here would persist an agent the
      // sidebar cannot show.
      if (
        activeAgent &&
        activeAgent.id !== DEFAULT_AGENT_ID &&
        !currentAgentIsPinned
      ) {
        // Dragging the unpinned current agent into the list pins it.
        if (activeIndex === visibleAgentIds.length - 1) {
          const pinnedWithCurrent = [...pinnedAgents, activeAgent];
          newPinnedAgents = arrayMove(
            pinnedWithCurrent,
            activeIndex,
            overIndex
          );
        } else {
          newPinnedAgents = arrayMove(visibleAgents, activeIndex, overIndex);
        }
      } else {
        newPinnedAgents = arrayMove(visibleAgents, activeIndex, overIndex);
      }

      updatePinnedAgents(newPinnedAgents);
    },
    [
      visibleAgentIds,
      visibleAgents,
      pinnedAgents,
      updatePinnedAgents,
      activeAgent,
      currentAgentIsPinned,
    ]
  );

  return (
    <SidebarLayouts.Body scrollKey="agents-sidebar">
      <SidebarLayouts.Section>
        <SidebarTab
          icon={SvgOnyxOctagon}
          {...navigation.linkTo("/app/agents", { scroll: false })}
          selected={appPosition.isMoreAgents()}
        >
          {t("appSidebar.exploreAgents.label")}
        </SidebarTab>
      </SidebarLayouts.Section>
      {(isLoadingAgentList || visibleAgents.length > 0) && (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={handleAgentDragEnd}
        >
          <SidebarLayouts.Section title={t("appSidebar.agents.title")}>
            <SortableContext
              items={visibleAgentIds}
              strategy={verticalListSortingStrategy}
            >
              {isLoadingAgentList ? (
                <SidebarLoader count={3} />
              ) : (
                visibleAgents.map((visibleAgent) => (
                  <AgentButton key={visibleAgent.id} agent={visibleAgent} />
                ))
              )}
            </SortableContext>
          </SidebarLayouts.Section>
        </DndContext>
      )}
    </SidebarLayouts.Body>
  );
}
