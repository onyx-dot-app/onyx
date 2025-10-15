"use client";

import React, { useCallback, memo, useMemo } from "react";
import { useSettingsContext } from "@/components/settings/SettingsProvider";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import Text from "@/refresh-components/texts/Text";
import ChatButton from "@/sections/sidebar/ChatButton";
import AgentButton from "@/sections/sidebar/AgentButton";
import { DragEndEvent } from "@dnd-kit/core";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import SvgEditBig from "@/icons/edit-big";
import SvgMoreHorizontal from "@/icons/more-horizontal";
import Settings from "@/sections/sidebar/Settings";
import { SidebarSection } from "@/sections/sidebar/SidebarSection";
import AgentsModal from "@/sections/AgentsModal";
import { useChatContext } from "@/refresh-components/contexts/ChatContext";
import { useAgentsContext } from "@/refresh-components/contexts/AgentsContext";
import { useAppSidebarContext } from "@/refresh-components/contexts/AppSidebarContext";
import {
  ModalIds,
  useChatModal,
} from "@/refresh-components/contexts/ChatModalContext";
import SvgFolderPlus from "@/icons/folder-plus";
import SvgOnyxOctagon from "@/icons/onyx-octagon";
import ProjectFolderButton from "@/sections/sidebar/ProjectFolderButton";
import CreateProjectModal from "@/components/modals/CreateProjectModal";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import { useAppRouter } from "@/hooks/appNavigation";
import { useSearchParams } from "next/navigation";
import SidebarWrapper from "@/sections/sidebar/SidebarWrapper";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import VerticalShadowScroller from "@/refresh-components/VerticalShadowScroller";

// Visible-agents = pinned-agents + current-agent (if current-agent not in pinned-agents)
// OR Visible-agents = pinned-agents (if current-agent in pinned-agents)
function buildVisibleAgents(
  pinnedAgents: MinimalPersonaSnapshot[],
  currentAgent: MinimalPersonaSnapshot | null
): [MinimalPersonaSnapshot[], boolean] {
  if (!currentAgent) return [pinnedAgents, false];
  const currentAgentIsPinned = pinnedAgents.some(
    (pinnedAgent) => pinnedAgent.id === currentAgent.id
  );
  const visibleAgents = currentAgentIsPinned
    ? pinnedAgents
    : [...pinnedAgents, currentAgent];
  return [visibleAgents, currentAgentIsPinned];
}

function AppSidebarInner() {
  const route = useAppRouter();
  const searchParams = useSearchParams();
  const { pinnedAgents, setPinnedAgents, currentAgent } = useAgentsContext();
  const { folded, setFolded } = useAppSidebarContext();
  const { isOpen, toggleModal } = useChatModal();
  const { chatSessions } = useChatContext();
  const combinedSettings = useSettingsContext();
  const { projects } = useProjectsContext();

  const [visibleAgents, currentAgentIsPinned] = useMemo(
    () => buildVisibleAgents(pinnedAgents, currentAgent),
    [pinnedAgents, currentAgent]
  );
  const visibleAgentIds = useMemo(
    () => visibleAgents.map((agent) => agent.id),
    [visibleAgents]
  );

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over) return;
      if (active.id === over.id) return;

      setPinnedAgents((prev) => {
        const activeIndex = visibleAgentIds.findIndex(
          (agentId) => agentId === active.id
        );
        const overIndex = visibleAgentIds.findIndex(
          (agentId) => agentId === over.id
        );

        if (currentAgent && !currentAgentIsPinned) {
          // This is the case in which the user is dragging the UNPINNED agent and moving it to somewhere else in the list.
          // This is an indication that we WANT to pin this agent!
          if (activeIndex === visibleAgentIds.length - 1) {
            const prevWithVisible = [...prev, currentAgent];
            return arrayMove(prevWithVisible, activeIndex, overIndex);
          }
        }

        return arrayMove(prev, activeIndex, overIndex);
      });
    },
    [visibleAgentIds, setPinnedAgents, currentAgent, currentAgentIsPinned]
  );

  const isHistoryEmpty = useMemo(
    () => !chatSessions || chatSessions.length === 0,
    [chatSessions]
  );

  if (!combinedSettings) {
    return null;
  }

  return (
    <>
      <AgentsModal />
      <CreateProjectModal />

      <SidebarWrapper folded={folded} setFolded={setFolded}>
        <div className="flex flex-col px-spacing-interline gap-spacing-interline">
          <div data-testid="AppSidebar/new-session">
            <SidebarTab
              leftIcon={SvgEditBig}
              folded={folded}
              onClick={() => route({})}
              active={Array.from(searchParams).length === 0}
            >
              New Session
            </SidebarTab>
          </div>

          {folded && (
            <>
              <SidebarTab
                leftIcon={SvgOnyxOctagon}
                onClick={() => toggleModal(ModalIds.AgentsModal, true)}
                active={isOpen(ModalIds.AgentsModal)}
                folded
              >
                Agents
              </SidebarTab>
              <SidebarTab
                leftIcon={SvgFolderPlus}
                onClick={() => toggleModal(ModalIds.CreateProjectModal, true)}
                active={isOpen(ModalIds.CreateProjectModal)}
                folded
              >
                New Project
              </SidebarTab>
            </>
          )}
        </div>

        {/* This is the main scrollable body. It should have top + bottom shadows on overflow */}
        <VerticalShadowScroller className="gap-padding-content px-spacing-interline">
          {!folded && (
            <>
              {/* Agents */}
              <SidebarSection title="Agents">
                <DndContext
                  sensors={sensors}
                  collisionDetection={closestCenter}
                  onDragEnd={handleDragEnd}
                >
                  <SortableContext
                    items={visibleAgentIds}
                    strategy={verticalListSortingStrategy}
                  >
                    {visibleAgents.map((visibleAgent) => (
                      <AgentButton key={visibleAgent.id} agent={visibleAgent} />
                    ))}
                  </SortableContext>
                </DndContext>
                <div data-testid="AppSidebar/more-agents">
                  <SidebarTab
                    leftIcon={SvgMoreHorizontal}
                    onClick={() => toggleModal(ModalIds.AgentsModal, true)}
                    lowlight
                  >
                    More Agents
                  </SidebarTab>
                </div>
              </SidebarSection>

              <SidebarSection title="Projects">
                {projects.map((project) => (
                  <ProjectFolderButton key={project.id} project={project} />
                ))}

                <SidebarTab
                  leftIcon={SvgFolderPlus}
                  onClick={() => toggleModal(ModalIds.CreateProjectModal, true)}
                  lowlight
                >
                  New Project
                </SidebarTab>
              </SidebarSection>

              {/* Recents */}
              <SidebarSection title="Recents">
                {isHistoryEmpty ? (
                  <Text text03 className="px-spacing-interline">
                    Try sending a message! Your chat history will appear here.
                  </Text>
                ) : (
                  chatSessions.map((chatSession) => (
                    <ChatButton
                      key={chatSession.id}
                      chatSession={chatSession}
                    />
                  ))
                )}
              </SidebarSection>
            </>
          )}
        </VerticalShadowScroller>

        <div className="px-spacing-interline">
          <Settings folded={folded} />
        </div>
      </SidebarWrapper>
    </>
  );
}

const AppSidebar = memo(AppSidebarInner);
AppSidebar.displayName = "AppSidebar";

export default AppSidebar;
