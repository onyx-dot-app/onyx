"use client";

import { useCallback, memo, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
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
import Settings from "@/sections/sidebar/Settings/Settings";
import SidebarSection from "@/sections/sidebar/SidebarSection";
import useChatSessions from "@/hooks/useChatSessions";
import { useProjects } from "@/lib/hooks/useProjects";
import { useAgents, useCurrentAgent, usePinnedAgents } from "@/hooks/useAgents";
import { useAppSidebarContext } from "@/refresh-components/contexts/AppSidebarContext";
import ProjectFolderButton from "@/sections/sidebar/ProjectFolderButton";
import CreateProjectModal from "@/components/modals/CreateProjectModal";
import MoveCustomAgentChatModal from "@/components/modals/MoveCustomAgentChatModal";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import { removeChatSessionFromProject } from "@/app/chat/projects/projectsService";
import type { Project } from "@/app/chat/projects/projectsService";
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
import SidebarBody from "@/sections/sidebar/SidebarBody";
import { useUser } from "@/components/user/UserProvider";
import useAppFocus from "@/hooks/useAppFocus";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import useScreenSize from "@/hooks/useScreenSize";
import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";
import {
  SvgEditBig,
  SvgFolderPlus,
  SvgMoreHorizontal,
  SvgOnyxOctagon,
  SvgSettings,
} from "@opal/icons";

// Visible-agents = pinned-agents + current-agent (if current-agent not in pinned-agents)
// OR Visible-agents = pinned-agents (if current-agent in pinned-agents)
function buildVisibleAgents(
  pinnedAgents: MinimalPersonaSnapshot[],
  currentAgent: MinimalPersonaSnapshot | null
): [MinimalPersonaSnapshot[], boolean] {
  /* NOTE: The unified agent (id = 0) is not visible in the sidebar,
  so we filter it out. */
  if (!currentAgent)
    return [pinnedAgents.filter((agent) => agent.id !== 0), false];
  const currentAgentIsPinned = pinnedAgents.some(
    (pinnedAgent) => pinnedAgent.id === currentAgent.id
  );
  const visibleAgents = (
    currentAgentIsPinned ? pinnedAgents : [...pinnedAgents, currentAgent]
  ).filter((agent) => agent.id !== 0);

  return [visibleAgents, currentAgentIsPinned];
}

interface RecentsSectionProps {
  chatSessions: ChatSession[];
}

function RecentsSection({ chatSessions }: RecentsSectionProps) {
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
        {chatSessions.length === 0 ? (
          <Text as="p" text01 className="px-3">
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

interface AppSidebarInnerProps {
  folded: boolean;
  onFoldClick: () => void;
}

const MemoizedAppSidebarInner = memo(
  ({ folded, onFoldClick }: AppSidebarInnerProps) => {
    const searchParams = useSearchParams();
    const combinedSettings = useSettingsContext();
    const { popup, setPopup } = usePopup();

    // Use SWR hooks for data fetching
    const {
      chatSessions,
      refreshChatSessions,
      isLoading: isLoadingChatSessions,
    } = useChatSessions();
    const {
      projects,
      refreshProjects,
      isLoading: isLoadingProjects,
    } = useProjects();
    const { isLoading: isLoadingAgents } = useAgents();
    const currentAgent = useCurrentAgent();
    const {
      pinnedAgents,
      updatePinnedAgents,
      isLoading: isLoadingPinnedAgents,
    } = usePinnedAgents();

    // Wait for ALL dynamic data before showing any sections
    const isLoadingDynamicContent =
      isLoadingChatSessions ||
      isLoadingProjects ||
      isLoadingAgents ||
      isLoadingPinnedAgents;

    // Still need some context for stateful operations
    const { refreshCurrentProjectDetails, currentProjectId } =
      useProjectsContext();

    // State for custom agent modal
    const [pendingMoveChatSession, setPendingMoveChatSession] =
      useState<ChatSession | null>(null);
    const [pendingMoveProjectId, setPendingMoveProjectId] = useState<
      number | null
    >(null);
    const [showMoveCustomAgentModal, setShowMoveCustomAgentModal] =
      useState(false);

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

        const activeIndex = visibleAgentIds.findIndex(
          (agentId) => agentId === active.id
        );
        const overIndex = visibleAgentIds.findIndex(
          (agentId) => agentId === over.id
        );

        let newPinnedAgents: MinimalPersonaSnapshot[];

        if (currentAgent && !currentAgentIsPinned) {
          // This is the case in which the user is dragging the UNPINNED agent and moving it to somewhere else in the list.
          // This is an indication that we WANT to pin this agent!
          if (activeIndex === visibleAgentIds.length - 1) {
            const pinnedWithCurrent = [...pinnedAgents, currentAgent];
            newPinnedAgents = arrayMove(
              pinnedWithCurrent,
              activeIndex,
              overIndex
            );
          } else {
            // Use visibleAgents to ensure the indices match with `visibleAgentIds`
            newPinnedAgents = arrayMove(visibleAgents, activeIndex, overIndex);
          }
        } else {
          // Use visibleAgents to ensure the indices match with `visibleAgentIds`
          newPinnedAgents = arrayMove(visibleAgents, activeIndex, overIndex);
        }

        updatePinnedAgents(newPinnedAgents);
      },
      [
        visibleAgentIds,
        visibleAgents,
        pinnedAgents,
        updatePinnedAgents,
        currentAgent,
        currentAgentIsPinned,
      ]
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
            fetchProjects: refreshProjects,
            currentProjectId,
          },
          setPopup
        );
        const projectRefreshPromise = currentProjectId
          ? refreshCurrentProjectDetails()
          : refreshProjects();
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
                : refreshProjects();
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
        refreshProjects,
        setPopup,
      ]
    );

    const { isAdmin, isCurator } = useUser();
    const activeSidebarTab = useAppFocus();
    const createProjectModal = useCreateModal();
    const newSessionButton = useMemo(() => {
      const href =
        combinedSettings?.settings?.disable_default_assistant && currentAgent
          ? `/chat?assistantId=${currentAgent.id}`
          : "/chat";
      return (
        <div data-testid="AppSidebar/new-session">
          <SidebarTab
            leftIcon={SvgEditBig}
            folded={folded}
            href={href}
            transient={activeSidebarTab.isNewSession()}
          >
            New Session
          </SidebarTab>
        </div>
      );
    }, [folded, activeSidebarTab, combinedSettings, currentAgent]);
    const moreAgentsButton = useMemo(
      () => (
        <div data-testid="AppSidebar/more-agents">
          <SidebarTab
            leftIcon={
              folded || visibleAgents.length === 0
                ? SvgOnyxOctagon
                : SvgMoreHorizontal
            }
            href="/chat/agents"
            folded={folded}
            transient={activeSidebarTab.isMoreAgents()}
            lowlight={!folded}
          >
            {visibleAgents.length === 0 ? "Explore Agents" : "More Agents"}
          </SidebarTab>
        </div>
      ),
      [folded, activeSidebarTab, visibleAgents]
    );
    const newProjectButton = useMemo(
      () => (
        <SidebarTab
          leftIcon={SvgFolderPlus}
          onClick={() => createProjectModal.toggle(true)}
          transient={createProjectModal.isOpen}
          folded={folded}
          lowlight={!folded}
        >
          New Project
        </SidebarTab>
      ),
      [folded, createProjectModal.toggle, createProjectModal.isOpen]
    );
    const settingsButton = useMemo(
      () => (
        <div>
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

    return (
      <>
        {popup}
        <createProjectModal.Provider>
          <CreateProjectModal />
        </createProjectModal.Provider>

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

        <SidebarWrapper folded={folded} onFoldClick={onFoldClick}>
          <SidebarBody
            scrollKey="app-sidebar"
            footer={settingsButton}
            actionButton={newSessionButton}
          >
            {/* When folded, show icons immediately without waiting for data */}
            {folded ? (
              <>
                {moreAgentsButton}
                {newProjectButton}
              </>
            ) : isLoadingDynamicContent ? null : (
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
                    {moreAgentsButton}
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
                  {/* Projects */}
                  <SidebarSection
                    title="Projects"
                    action={
                      <IconButton
                        icon={SvgFolderPlus}
                        internal
                        tooltip="New Project"
                        onClick={() => createProjectModal.toggle(true)}
                      />
                    }
                  >
                    {projects.map((project) => (
                      <ProjectFolderButton key={project.id} project={project} />
                    ))}
                    {projects.length === 0 && newProjectButton}
                  </SidebarSection>

                  {/* Recents */}
                  <RecentsSection chatSessions={chatSessions} />
                </DndContext>
              </>
            )}
          </SidebarBody>
        </SidebarWrapper>
      </>
    );
  }
);
MemoizedAppSidebarInner.displayName = "AppSidebar";

export default function AppSidebar() {
  const { folded, setFolded } = useAppSidebarContext();
  const { isMobile } = useScreenSize();

  if (!isMobile)
    return (
      <MemoizedAppSidebarInner
        folded={folded}
        onFoldClick={() => setFolded((prev) => !prev)}
      />
    );

  return (
    <>
      <div
        className={cn(
          "fixed inset-y-0 left-0 z-50 transition-transform duration-200",
          folded ? "-translate-x-full" : "translate-x-0"
        )}
      >
        <MemoizedAppSidebarInner
          folded={false}
          onFoldClick={() => setFolded(true)}
        />
      </div>

      {/* Hitbox to close the sidebar if anything outside of it is touched */}
      <div
        className={cn(
          "fixed inset-0 z-40 bg-mask-03 backdrop-blur-03 transition-opacity duration-200",
          folded
            ? "opacity-0 pointer-events-none"
            : "opacity-100 pointer-events-auto"
        )}
        onClick={() => setFolded(true)}
      />
    </>
  );
}
