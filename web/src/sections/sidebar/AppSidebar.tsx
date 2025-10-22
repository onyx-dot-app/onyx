"use client";

import React, { useCallback, memo, useMemo, useState } from "react";
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
  pointerWithin,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { useDroppable } from "@dnd-kit/core";
import {
  restrictToFirstScrollableAncestor,
  restrictToVerticalAxis,
} from "@dnd-kit/modifiers";
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
import MoveCustomAgentChatModal from "@/components/modals/MoveCustomAgentChatModal";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import { removeChatSessionFromProject } from "@/app/chat/projects/projectsService";
import type { Project } from "@/app/chat/projects/projectsService";
import { useAppRouter } from "@/hooks/appNavigation";
import { useSearchParams } from "next/navigation";
import SidebarWrapper from "@/sections/sidebar/SidebarWrapper";
import { usePopup } from "@/components/admin/connectors/Popup";
import IconButton from "@/refresh-components/buttons/IconButton";
import { cn } from "@/lib/utils";
import {
  DRAG_TYPES,
  DEFAULT_PERSONA_ID,
  LOCAL_STORAGE_KEYS,
} from "@/sections/sidebar/constants";
import { showErrorNotification, handleMoveOperation } from "./sidebarUtils";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import { ChatSession } from "@/app/chat/interfaces";
import { SidebarBody } from "@/sections/sidebar/utils";
import { useUser } from "@/components/user/UserProvider";
import SvgSettings from "@/icons/settings";

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

interface RecentsSectionProps {
  isHistoryEmpty: boolean;
  chatSessions: ChatSession[];
}

function RecentsSection({ isHistoryEmpty, chatSessions }: RecentsSectionProps) {
  const { setNodeRef, isOver } = useDroppable({
    id: DRAG_TYPES.RECENTS,
    data: {
      type: DRAG_TYPES.RECENTS,
    },
  });

  return (
    <div
      ref={setNodeRef}
      className={cn(
        "transition-colors duration-200 rounded-08 h-full",
        isOver && "bg-background-tint-03"
      )}
    >
      <SidebarSection title="Recents">
        {isHistoryEmpty ? (
          <Text text01 className="px-padding-button">
            Try sending a message! Your chat history will appear here.
          </Text>
        ) : (
          chatSessions.map((chatSession) => (
            <ChatButton
              key={chatSession.id}
              chatSession={chatSession}
              draggable
            />
          ))
        )}
      </SidebarSection>
    </div>
  );
}

function AppSidebarInner() {
  const route = useAppRouter();
  const searchParams = useSearchParams();
  const { pinnedAgents, setPinnedAgents, currentAgent } = useAgentsContext();
  const { folded, setFolded } = useAppSidebarContext();
  const { chatSessions, refreshChatSessions } = useChatContext();
  const combinedSettings = useSettingsContext();
  const { refreshCurrentProjectDetails, fetchProjects, currentProjectId } =
    useProjectsContext();
  const { popup, setPopup } = usePopup();

  // State for custom agent modal
  const [pendingMoveChatSession, setPendingMoveChatSession] =
    useState<ChatSession | null>(null);
  const [pendingMoveProjectId, setPendingMoveProjectId] = useState<
    number | null
  >(null);
  const [showMoveCustomAgentModal, setShowMoveCustomAgentModal] =
    useState(false);
  const { isOpen, toggleModal } = useChatModal();
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

  // Handle agent drag and drop
  const handleAgentDragEnd = useCallback(
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

  // Perform the actual move
  async function performChatMove(
    targetProjectId: number,
    chatSession: ChatSession
  ) {
    try {
      await handleMoveOperation(
        {
          chatSession,
          targetProjectId,
          refreshChatSessions,
          refreshCurrentProjectDetails,
          fetchProjects,
          currentProjectId,
        },
        setPopup
      );
      const projectRefreshPromise = currentProjectId
        ? refreshCurrentProjectDetails()
        : fetchProjects();
      await Promise.all([refreshChatSessions(), projectRefreshPromise]);
    } catch (error) {
      console.error("Failed to move chat:", error);
      throw error;
    }
  }

  // Handle chat to project drag and drop
  const handleChatProjectDragEnd = useCallback(
    async (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over) return;

      const activeData = active.data.current;
      const overData = over.data.current;

      if (!activeData || !overData) {
        return;
      }

      // Check if we're dragging a chat onto a project
      if (
        activeData?.type === DRAG_TYPES.CHAT &&
        overData?.type === DRAG_TYPES.PROJECT
      ) {
        const chatSession = activeData.chatSession as ChatSession;
        const targetProject = overData.project as Project;
        const sourceProjectId = activeData.projectId;

        // Don't do anything if dropping on the same project
        if (sourceProjectId === targetProject.id) {
          return;
        }

        const hideModal =
          typeof window !== "undefined" &&
          window.localStorage.getItem(
            LOCAL_STORAGE_KEYS.HIDE_MOVE_CUSTOM_AGENT_MODAL
          ) === "true";

        const isChatUsingDefaultAssistant =
          chatSession.persona_id === DEFAULT_PERSONA_ID;

        if (!isChatUsingDefaultAssistant && !hideModal) {
          setPendingMoveChatSession(chatSession);
          setPendingMoveProjectId(targetProject.id);
          setShowMoveCustomAgentModal(true);
          return;
        }

        try {
          await performChatMove(targetProject.id, chatSession);
        } catch (error) {
          showErrorNotification(
            setPopup,
            "Failed to move chat. Please try again."
          );
        }
      }

      // Check if we're dragging a chat from a project to the Recents section
      if (
        activeData?.type === DRAG_TYPES.CHAT &&
        overData?.type === DRAG_TYPES.RECENTS
      ) {
        const chatSession = activeData.chatSession as ChatSession;
        const sourceProjectId = activeData.projectId;

        // Only remove from project if it was in a project
        if (sourceProjectId) {
          try {
            await removeChatSessionFromProject(chatSession.id);
            const projectRefreshPromise = currentProjectId
              ? refreshCurrentProjectDetails()
              : fetchProjects();
            await Promise.all([refreshChatSessions(), projectRefreshPromise]);
          } catch (error) {
            console.error("Failed to remove chat from project:", error);
          }
        }
      }
    },
    [
      currentProjectId,
      refreshChatSessions,
      refreshCurrentProjectDetails,
      fetchProjects,
    ]
  );

  const isHistoryEmpty = useMemo(
    () => !chatSessions || chatSessions.length === 0,
    [chatSessions]
  );

  const newSessionButton = useMemo(
    () => (
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
    ),
    [folded, route, searchParams]
  );

  const { isAdmin, isCurator } = useUser();

  const settingsButton = useMemo(
    () => (
      <div className="px-spacing-interline">
        {(isAdmin || isCurator) && (
          <SidebarTab
            href="/admin/indexing/status"
            leftIcon={SvgSettings}
            folded={folded}
          >
            {isAdmin ? "Admin Panel" : "Curator Panel"}
          </SidebarTab>
        )}
        <Settings folded={folded} />
      </div>
    ),
    [folded, isAdmin, isCurator]
  );

  if (!combinedSettings) {
    return null;
  }

  return (
    <>
      {popup}
      <AgentsModal />
      <CreateProjectModal />

      {showMoveCustomAgentModal && (
        <MoveCustomAgentChatModal
          onCancel={() => {
            setShowMoveCustomAgentModal(false);
            setPendingMoveChatSession(null);
            setPendingMoveProjectId(null);
          }}
          onConfirm={async (doNotShowAgain: boolean) => {
            if (doNotShowAgain && typeof window !== "undefined") {
              window.localStorage.setItem(
                LOCAL_STORAGE_KEYS.HIDE_MOVE_CUSTOM_AGENT_MODAL,
                "true"
              );
            }
            const chat = pendingMoveChatSession;
            const target = pendingMoveProjectId;
            setShowMoveCustomAgentModal(false);
            setPendingMoveChatSession(null);
            setPendingMoveProjectId(null);
            if (chat && target != null) {
              try {
                await performChatMove(target, chat);
              } catch (error) {
                showErrorNotification(
                  setPopup,
                  "Failed to move chat. Please try again."
                );
              }
            }
          }}
        />
      )}

      <SidebarWrapper folded={folded} setFolded={setFolded}>
        {folded ? (
          <div className="flex flex-col h-full justify-between">
            <div className="px-spacing-interline">
              {newSessionButton}
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
            </div>
            {settingsButton}
          </div>
        ) : (
          <>
            <SidebarBody
              actionButton={newSessionButton}
              footer={settingsButton}
            >
              <>
                {/* Agents */}
                <DndContext
                  sensors={sensors}
                  collisionDetection={closestCenter}
                  onDragEnd={handleAgentDragEnd}
                >
                  <SidebarSection title="Agents">
                    <SortableContext
                      items={visibleAgentIds}
                      strategy={verticalListSortingStrategy}
                    >
                      {visibleAgents.map((visibleAgent) => (
                        <AgentButton
                          key={visibleAgent.id}
                          agent={visibleAgent}
                        />
                      ))}
                    </SortableContext>
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
                </DndContext>

                {/* Wrap Projects and Recents in a shared DndContext for chat-to-project drag */}
                <DndContext
                  sensors={sensors}
                  collisionDetection={pointerWithin}
                  modifiers={[
                    restrictToFirstScrollableAncestor,
                    restrictToVerticalAxis,
                  ]}
                  onDragEnd={handleChatProjectDragEnd}
                >
                  <SidebarSection
                    title="Projects"
                    action={
                      <IconButton
                        icon={SvgFolderPlus}
                        internal
                        tooltip="New Project"
                        onClick={() =>
                          toggleModal(ModalIds.CreateProjectModal, true)
                        }
                      />
                    }
                  >
                    {projects.map((project) => (
                      <ProjectFolderButton key={project.id} project={project} />
                    ))}

                    <SidebarTab
                      leftIcon={SvgFolderPlus}
                      onClick={() =>
                        toggleModal(ModalIds.CreateProjectModal, true)
                      }
                      lowlight
                    >
                      New Project
                    </SidebarTab>
                  </SidebarSection>

                  {/* Recents */}
                  <RecentsSection
                    isHistoryEmpty={isHistoryEmpty}
                    chatSessions={chatSessions}
                  />
                </DndContext>
              </>
            </SidebarBody>
          </>
        )}
      </SidebarWrapper>
    </>
  );
}

const AppSidebar = memo(AppSidebarInner);
AppSidebar.displayName = "AppSidebar";

export default AppSidebar;
