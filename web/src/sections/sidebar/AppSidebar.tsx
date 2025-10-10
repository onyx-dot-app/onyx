"use client";

import React, { useCallback, useState, memo, useMemo, useEffect } from "react";
import { useSettingsContext } from "@/components/settings/SettingsProvider";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import Text from "@/refresh-components/Text";
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
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import SvgEditBig from "@/icons/edit-big";
import SvgMoreHorizontal from "@/icons/more-horizontal";
import Settings from "@/sections/sidebar/Settings";
import { getAgentIcon, SidebarSection } from "@/sections/sidebar/components";
import NavigationTab from "@/refresh-components/buttons/NavigationTab";
import AgentsModal from "@/sections/AgentsModal";
import { useChatContext } from "@/refresh-components/contexts/ChatContext";
import SvgBubbleText from "@/icons/bubble-text";
import { deleteChatSession, renameChatSession } from "@/app/chat/services/lib";
import { useAgentsContext } from "@/refresh-components/contexts/AgentsContext";
import { useAppSidebarContext } from "@/refresh-components/contexts/AppSidebarContext";
import { ChatSession } from "@/app/chat/interfaces";
import ConfirmationModalContent from "@/refresh-components/modals/ConfirmationModalContent";
import SvgTrash from "@/icons/trash";
import SvgShare from "@/icons/share";
import SvgEdit from "@/icons/edit";
import Button from "@/refresh-components/buttons/Button";
import SvgPin from "@/icons/pin";
import { noProp } from "@/lib/utils";
import { PopoverMenu } from "@/components/ui/popover";
import SvgFolderPlus from "@/icons/folder-plus";
import SvgOnyxOctagon from "@/icons/onyx-octagon";
import CreateProjectModal from "@/components/modals/CreateProjectModal";
import { useAppParams, useAppRouter } from "@/hooks/appNavigation";
import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";
import {
  Project,
  moveChatSession,
  removeChatSessionFromProject,
} from "@/app/chat/projects/projectsService";
import { useSearchParams } from "next/navigation";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import SvgFolderIn from "@/icons/folder-in";
import SvgFolder from "@/icons/folder";
import SvgChevronLeft from "@/icons/chevron-left";
import MoveCustomAgentChatModal from "@/components/modals/MoveCustomAgentChatModal";
import { UNNAMED_CHAT } from "@/lib/constants";
import SidebarWrapper from "@/sections/sidebar/SidebarWrapper";
import ShareChatSessionModal from "@/app/chat/components/modal/ShareChatSessionModal";
import { createModalProvider } from "@/refresh-components/contexts/ModalContext";
import ProjectFolder from "@/components/sidebar/Projects";
import IconButton from "@/refresh-components/buttons/IconButton";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";

// Constants
const DEFAULT_PERSONA_ID = 0;
const LS_HIDE_MOVE_CUSTOM_AGENT_MODAL_KEY = "onyx:hideMoveCustomAgentModal";

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

export interface PopoverSearchInputProps {
  setShowMoveOptions: (show: boolean) => void;
  onSearch: (term: string) => void;
}

export function PopoverSearchInput({
  setShowMoveOptions,
  onSearch,
}: PopoverSearchInputProps) {
  const [searchTerm, setSearchTerm] = useState("");

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setSearchTerm(value);
    onSearch(value);
  };
  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      setShowMoveOptions(false);
    }
  };

  const handleClickBackButton = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation();
    setShowMoveOptions(false);
    setSearchTerm("");
  };

  return (
    <div className="flex flex-row justify-center items-center p-spacing-inline gap-spacing-inline rounded-08 bg-transparent">
      <IconButton
        icon={SvgChevronLeft}
        onClick={handleClickBackButton}
        internal
      />
      <InputTypeIn
        type="text"
        placeholder="Search Projects"
        value={searchTerm}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
      />
    </div>
  );
}

interface ChatButtonProps {
  chatSession: ChatSession;
  project?: Project;
}

function ChatButtonInner({ chatSession, project }: ChatButtonProps) {
  // Modal contexts
  const deleteConfirmationModal = createModalProvider();
  const moveCustomAgentModal = createModalProvider();
  const shareModal = createModalProvider();

  const route = useAppRouter();
  const params = useAppParams();
  const [name, setName] = useState(chatSession.name || UNNAMED_CHAT);
  const [renaming, setRenaming] = useState(false);

  const [showMoveOptions, setShowMoveOptions] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [popoverItems, setPopoverItems] = useState<React.ReactNode[]>([]);
  const { refreshChatSessions } = useChatContext();
  const {
    refreshCurrentProjectDetails,
    projects,
    fetchProjects,
    currentProjectId,
  } = useProjectsContext();

  const [pendingMoveProjectId, setPendingMoveProjectId] = useState<
    number | null
  >(null);
  const isChatUsingDefaultAssistant =
    chatSession.persona_id === DEFAULT_PERSONA_ID;

  const filteredProjects = useMemo(() => {
    if (!searchTerm) return projects;
    const term = searchTerm.toLowerCase();
    return projects.filter((project) =>
      project.name.toLowerCase().includes(term)
    );
  }, [projects, searchTerm]);

  async function submitRename(renamingValue: string) {
    const newName = renamingValue.trim();
    if (newName === "" || newName === chatSession.name) return;

    setName(newName);
    try {
      await renameChatSession(chatSession.id, newName);
      await refreshChatSessions();
    } catch (error) {
      console.error("Failed to rename chat:", error);
    }
  }

  useEffect(() => {
    if (!showMoveOptions) {
      const popoverItems = [
        <NavigationTab
          key="share"
          icon={SvgShare}
          onClick={noProp(() => {
            shareModal.toggle(true);
          })}
        >
          Share
        </NavigationTab>,
        <NavigationTab
          key="rename"
          icon={SvgEdit}
          onClick={noProp(() => setRenaming(true))}
        >
          Rename
        </NavigationTab>,
        <NavigationTab
          key="move"
          icon={SvgFolderIn}
          onClick={noProp(() => setShowMoveOptions(true))}
        >
          Move to Project
        </NavigationTab>,
        project && (
          <NavigationTab
            key="remove"
            icon={SvgFolder}
            onClick={noProp(() => handleRemoveFromProject())}
          >
            {`Remove from ${project.name}`}
          </NavigationTab>
        ),
        null,
        <NavigationTab
          key="delete"
          icon={SvgTrash}
          onClick={noProp(() => deleteConfirmationModal.toggle(true))}
          danger
        >
          Delete
        </NavigationTab>,
      ];
      setPopoverItems(popoverItems);
    } else {
      const popoverItems = [
        <PopoverSearchInput
          key="search"
          setShowMoveOptions={setShowMoveOptions}
          onSearch={setSearchTerm}
        />,
        ...filteredProjects
          .filter((candidateProject) => candidateProject.id !== project?.id)
          .map((targetProject) => (
            <NavigationTab
              key={targetProject.id}
              icon={SvgFolder}
              onClick={noProp(() => handleChatMove(targetProject))}
            >
              {targetProject.name}
            </NavigationTab>
          )),
      ];
      setPopoverItems(popoverItems);
    }
  }, [
    showMoveOptions,
    filteredProjects,
    refreshChatSessions,
    fetchProjects,
    currentProjectId,
    refreshCurrentProjectDetails,
    project,
    chatSession.id,
  ]);

  async function handleChatDelete() {
    try {
      await deleteChatSession(chatSession.id);

      if (project) {
        await fetchProjects();
        await refreshCurrentProjectDetails();

        // Only route if the deleted chat is the currently opened chat session
        if (params(SEARCH_PARAM_NAMES.CHAT_ID) == chatSession.id) {
          route({ projectId: project.id });
        }
      }
      await refreshChatSessions();
    } catch (error) {
      console.error("Failed to delete chat:", error);
    }
  }

  async function performMove(targetProjectId: number) {
    try {
      await moveChatSession(targetProjectId, chatSession.id);
      const projectRefreshPromise = currentProjectId
        ? refreshCurrentProjectDetails()
        : fetchProjects();
      await Promise.all([refreshChatSessions(), projectRefreshPromise]);
      setShowMoveOptions(false);
      setSearchTerm("");
    } catch (error) {
      console.error("Failed to move chat:", error);
    }
  }

  async function handleChatMove(targetProject: Project) {
    const hideModal =
      typeof window !== "undefined" &&
      window.localStorage.getItem(LS_HIDE_MOVE_CUSTOM_AGENT_MODAL_KEY) ===
        "true";

    if (!isChatUsingDefaultAssistant && !hideModal) {
      setPendingMoveProjectId(targetProject.id);
      moveCustomAgentModal.toggle(true);
      return;
    }

    await performMove(targetProject.id);
  }

  async function handleRemoveFromProject() {
    try {
      await removeChatSessionFromProject(chatSession.id);
      const projectRefreshPromise = currentProjectId
        ? refreshCurrentProjectDetails()
        : fetchProjects();
      await Promise.all([refreshChatSessions(), projectRefreshPromise]);
      setShowMoveOptions(false);
      setSearchTerm("");
    } catch (error) {
      console.error("Failed to remove chat from project:", error);
    }
  }

  return (
    <>
      <deleteConfirmationModal.ModalProvider>
        <ConfirmationModalContent
          title="Delete Chat"
          icon={SvgTrash}
          submit={
            <Button
              danger
              onClick={() => {
                deleteConfirmationModal.toggle(false);
                handleChatDelete();
              }}
            >
              Delete
            </Button>
          }
        >
          Are you sure you want to delete this chat? This action cannot be
          undone.
        </ConfirmationModalContent>
      </deleteConfirmationModal.ModalProvider>

      <moveCustomAgentModal.ModalProvider>
        <MoveCustomAgentChatModal
          onCancel={() => {
            moveCustomAgentModal.toggle(false);
            setPendingMoveProjectId(null);
          }}
          onConfirm={async (doNotShowAgain: boolean) => {
            if (doNotShowAgain && typeof window !== "undefined") {
              window.localStorage.setItem(
                LS_HIDE_MOVE_CUSTOM_AGENT_MODAL_KEY,
                "true"
              );
            }
            const target = pendingMoveProjectId;
            moveCustomAgentModal.toggle(false);
            setPendingMoveProjectId(null);
            if (target != null) {
              await performMove(target);
            }
          }}
        />
      </moveCustomAgentModal.ModalProvider>

      <shareModal.ModalProvider>
        <ShareChatSessionModal
          chatSession={chatSession}
          onClose={() => shareModal.toggle(false)}
        />
      </shareModal.ModalProvider>

      <NavigationTab
        icon={project ? () => <></> : SvgBubbleText}
        onClick={() => route({ chatSessionId: chatSession.id })}
        active={params(SEARCH_PARAM_NAMES.CHAT_ID) === chatSession.id}
        popover={<PopoverMenu>{popoverItems}</PopoverMenu>}
        onPopoverChange={(open) => !open && setShowMoveOptions(false)}
        renaming={renaming}
        setRenaming={setRenaming}
        submitRename={submitRename}
      >
        {name}
      </NavigationTab>
    </>
  );
}

export const ChatButton = memo(ChatButtonInner);

interface AgentsButtonProps {
  visibleAgent: MinimalPersonaSnapshot;
}

function AgentsButtonInner({ visibleAgent }: AgentsButtonProps) {
  const route = useAppRouter();
  const params = useAppParams();
  const { pinnedAgents, togglePinnedAgent } = useAgentsContext();
  const pinned = pinnedAgents.some(
    (pinnedAgent) => pinnedAgent.id === visibleAgent.id
  );

  return (
    <SortableItem id={visibleAgent.id}>
      <div className="flex flex-col w-full h-full">
        <NavigationTab
          key={visibleAgent.id}
          icon={getAgentIcon(visibleAgent)}
          onClick={() => route({ agentId: visibleAgent.id })}
          active={
            params(SEARCH_PARAM_NAMES.PERSONA_ID) === String(visibleAgent.id)
          }
          popover={
            <PopoverMenu>
              {[
                <NavigationTab
                  key="pin-unpin-chat"
                  icon={SvgPin}
                  onClick={noProp(() =>
                    togglePinnedAgent(visibleAgent, !pinned)
                  )}
                >
                  {pinned ? "Unpin Agent" : "Pin Agent"}
                </NavigationTab>,
              ]}
            </PopoverMenu>
          }
          highlight
        >
          {visibleAgent.name}
        </NavigationTab>
      </div>
    </SortableItem>
  );
}

const AgentsButton = memo(AgentsButtonInner);

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

function AppSidebarInner() {
  const route = useAppRouter();
  const searchParams = useSearchParams();
  const { pinnedAgents, setPinnedAgents, currentAgent } = useAgentsContext();
  const { folded, setFolded } = useAppSidebarContext();
  const agentsModal = createModalProvider();
  const createProjectModal = createModalProvider();
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
      <agentsModal.ModalProvider medium>
        <AgentsModal />
      </agentsModal.ModalProvider>

      <createProjectModal.ModalProvider>
        <CreateProjectModal />
      </createProjectModal.ModalProvider>

      <SidebarWrapper folded={folded} setFolded={setFolded}>
        <div className="flex flex-col gap-spacing-interline">
          <NavigationTab
            icon={SvgEditBig}
            className="!w-full"
            folded={folded}
            onClick={() => route({})}
            active={Array.from(searchParams).length === 0}
            tooltip
          >
            New Session
          </NavigationTab>

          {folded && (
            <>
              <NavigationTab
                icon={SvgOnyxOctagon}
                folded
                tooltip
                onClick={() => agentsModal.toggle(true)}
              >
                Agents
              </NavigationTab>
              <NavigationTab
                icon={SvgFolderPlus}
                folded
                tooltip
                onClick={() => createProjectModal.toggle(true)}
              >
                New Project
              </NavigationTab>
            </>
          )}
        </div>

        <div className="flex flex-col gap-padding-content flex-1 overflow-y-scroll">
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
                      <AgentsButton
                        key={visibleAgent.id}
                        visibleAgent={visibleAgent}
                      />
                    ))}
                  </SortableContext>
                </DndContext>
                <NavigationTab
                  icon={SvgMoreHorizontal}
                  onClick={() => agentsModal.toggle(true)}
                  lowlight
                >
                  More Agents
                </NavigationTab>
              </SidebarSection>

              <SidebarSection title="Projects">
                {projects.map((project) => (
                  <ProjectFolder key={project.id} project={project} />
                ))}
                <NavigationTab
                  icon={SvgFolderPlus}
                  onClick={() => createProjectModal.toggle(true)}
                  lowlight
                >
                  New Project
                </NavigationTab>
              </SidebarSection>

              {/* Recents */}
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
                    />
                  ))
                )}
              </SidebarSection>
            </>
          )}
        </div>

        {/* Bottom */}
        <div className="flex flex-col">
          <Settings folded={folded} />
        </div>
      </SidebarWrapper>
    </>
  );
}

const AppSidebar = memo(AppSidebarInner);
AppSidebar.displayName = "AppSidebar";

export default AppSidebar;
