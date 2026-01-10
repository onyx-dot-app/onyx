"use client";

import React, { useState, memo, useMemo, useEffect } from "react";
import { useDraggable } from "@dnd-kit/core";
import useChatSessions from "@/hooks/useChatSessions";
import { deleteChatSession, renameChatSession } from "@/app/chat/services/lib";
import { ChatSession } from "@/app/chat/interfaces";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import Button from "@/refresh-components/buttons/Button";
import { cn, noProp } from "@/lib/utils";
import {
  Popover,
  PopoverContent,
  PopoverMenu,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useAppRouter } from "@/hooks/appNavigation";
import {
  Project,
  removeChatSessionFromProject,
  createProject as createProjectService,
} from "@/app/chat/projects/projectsService";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import MoveCustomAgentChatModal from "@/components/modals/MoveCustomAgentChatModal";
import { UNNAMED_CHAT } from "@/lib/constants";
import ShareChatSessionModal from "@/app/chat/components/modal/ShareChatSessionModal";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import IconButton from "@/refresh-components/buttons/IconButton";
import { PopoverAnchor } from "@radix-ui/react-popover";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { usePopup } from "@/components/admin/connectors/Popup";
import { DRAG_TYPES, LOCAL_STORAGE_KEYS } from "@/sections/sidebar/constants";
import {
  shouldShowMoveModal,
  showErrorNotification,
  handleMoveOperation,
} from "@/sections/sidebar/sidebarUtils";
import ButtonRenaming from "@/refresh-components/buttons/ButtonRenaming";
import Truncated from "@/refresh-components/texts/Truncated";
import Text from "@/refresh-components/texts/Text";
import useAppFocus from "@/hooks/useAppFocus";
import LineItem from "@/refresh-components/buttons/LineItem";
import {
  SvgChevronLeft,
  SvgEdit,
  SvgFolder,
  SvgFolderIn,
  SvgFolderPlus,
  SvgMoreHorizontal,
  SvgShare,
  SvgTrash,
} from "@opal/icons";
import useOnMount from "@/hooks/useOnMount";
import { useAgents, usePinnedAgents } from "@/hooks/useAgents";

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
    <div className="flex flex-row items-center">
      <IconButton
        icon={SvgChevronLeft}
        onClick={handleClickBackButton}
        internal
      />
      <InputTypeIn
        type="text"
        value={searchTerm}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        placeholder="Search Projects"
        onClick={noProp()}
        internal
        autoFocus
      />
    </div>
  );
}

export interface ChatButtonProps {
  chatSession: ChatSession;
  project?: Project;
  draggable?: boolean;
}

const ChatButton = memo(
  ({ chatSession, project, draggable = false }: ChatButtonProps) => {
    const route = useAppRouter();
    const activeSidebarTab = useAppFocus();
    const active = useMemo(
      () =>
        activeSidebarTab.isChat() &&
        activeSidebarTab.getId() === chatSession.id,
      [activeSidebarTab, chatSession.id]
    );
    const mounted = useOnMount();
    const [displayName, setDisplayName] = useState(
      chatSession.name || UNNAMED_CHAT
    );
    const [renaming, setRenaming] = useState(false);
    const [deleteConfirmationModalOpen, setDeleteConfirmationModalOpen] =
      useState(false);
    const [showMoveOptions, setShowMoveOptions] = useState(false);
    const [showShareModal, setShowShareModal] = useState(false);
    const [searchTerm, setSearchTerm] = useState("");
    const [popoverItems, setPopoverItems] = useState<React.ReactNode[]>([]);
    const { refreshChatSessions } = useChatSessions();
    const {
      refreshCurrentProjectDetails,
      projects,
      fetchProjects,
      currentProjectId,
      createProject,
    } = useProjectsContext();
    const { popup, setPopup } = usePopup();
    const { agents } = useAgents();
    const { pinnedAgents, togglePinnedAgent } = usePinnedAgents();
    const [popoverOpen, setPopoverOpen] = useState(false);
    const [pendingMoveProjectId, setPendingMoveProjectId] = useState<
      number | null
    >(null);
    const [showMoveCustomAgentModal, setShowMoveCustomAgentModal] =
      useState(false);
    const [navigateAfterMoveProjectId, setNavigateAfterMoveProjectId] =
      useState<number | null>(null);

    // Drag and drop setup for chat sessions
    const dragId = `${DRAG_TYPES.CHAT}-${chatSession.id}`;
    const { attributes, listeners, setNodeRef, transform, isDragging } =
      useDraggable({
        id: dragId,
        data: {
          type: DRAG_TYPES.CHAT,
          chatSession,
          projectId: project?.id,
        },
        disabled: !draggable || renaming,
      });

    // Sync local name state when chatSession.name changes (e.g., after auto-naming)
    useEffect(() => {
      const newName = chatSession.name || UNNAMED_CHAT;
      const oldName = displayName;

      // Only animate if transitioning from UNNAMED_CHAT to a real name
      if (oldName === UNNAMED_CHAT && newName !== UNNAMED_CHAT && mounted) {
        // Type out the name character by character
        let currentIndex = 0;
        const typingInterval = setInterval(() => {
          currentIndex++;
          setDisplayName(newName.slice(0, currentIndex));

          if (currentIndex >= newName.length) {
            clearInterval(typingInterval);
          }
        }, 30); // 30ms per character

        return () => clearInterval(typingInterval);
      } else {
        // No animation for other changes (manual rename, initial load, etc.)
        setDisplayName(newName);
      }
    }, [chatSession.name, mounted]);

    const filteredProjects = useMemo(() => {
      if (!searchTerm) return projects;
      const term = searchTerm.toLowerCase();
      return projects.filter((project) =>
        project.name.toLowerCase().includes(term)
      );
    }, [projects, searchTerm]);

    useEffect(() => {
      if (!showMoveOptions) {
        const popoverItems = [
          <LineItem
            key="share"
            icon={SvgShare}
            onClick={noProp(() => setShowShareModal(true))}
          >
            Share
          </LineItem>,
          <LineItem
            key="rename"
            icon={SvgEdit}
            onClick={noProp(() => setRenaming(true))}
          >
            Rename
          </LineItem>,
          <LineItem
            key="move"
            icon={SvgFolderIn}
            onClick={noProp(() => setShowMoveOptions(true))}
          >
            Move to Project
          </LineItem>,
          project && (
            <LineItem
              key="remove"
              icon={SvgFolder}
              onClick={noProp(() => handleRemoveFromProject())}
            >
              {`Remove from ${project.name}`}
            </LineItem>
          ),
          null,
          <LineItem
            key="delete"
            icon={SvgTrash}
            danger
            onClick={noProp(() => setDeleteConfirmationModalOpen(true))}
          >
            Delete
          </LineItem>,
        ];
        setPopoverItems(popoverItems);
      } else {
        const availableProjects = filteredProjects.filter(
          (candidateProject) => candidateProject.id !== project?.id
        );

        const popoverItems = [
          <PopoverSearchInput
            key="search"
            setShowMoveOptions={setShowMoveOptions}
            onSearch={setSearchTerm}
          />,
          ...availableProjects.map((targetProject) => (
            <LineItem
              key={targetProject.id}
              icon={SvgFolder}
              onClick={noProp(() => handleChatMove(targetProject))}
            >
              {targetProject.name}
            </LineItem>
          )),
          // Show "Create New Project" option when no projects match the search
          ...(availableProjects.length === 0 && searchTerm.trim() !== ""
            ? [
                null,
                <LineItem
                  key="create-new"
                  icon={SvgFolderPlus}
                  onClick={noProp(() =>
                    handleCreateProjectAndMove(searchTerm.trim())
                  )}
                >
                  <Text as="p" text03 mainUiMuted className="-mr-1">
                    Create
                  </Text>
                  <Truncated text03 mainUiAction>
                    {searchTerm.trim()}
                  </Truncated>
                </LineItem>,
              ]
            : []),
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
      searchTerm,
      createProject,
    ]);

    // Pin the chat's agent when clicking on the conversation
    async function handleClick() {
      const agent = agents.find((a) => a.id === chatSession.persona_id);
      if (agent) {
        const isAlreadyPinned = pinnedAgents.some((a) => a.id === agent.id);
        if (!isAlreadyPinned) {
          await togglePinnedAgent(agent, true);
        }
      }
      route({ chatSessionId: chatSession.id });
    }

    async function handleRename(newName: string) {
      setDisplayName(newName);
      await renameChatSession(chatSession.id, newName);
      await refreshChatSessions();
    }

    async function handleChatDelete() {
      try {
        await deleteChatSession(chatSession.id);

        if (project) {
          await fetchProjects();
          await refreshCurrentProjectDetails();

          // Only route if the deleted chat is the currently opened chat session
          if (active) {
            route({ projectId: project.id });
          }
        }
        await refreshChatSessions();
      } catch (error) {
        console.error("Failed to delete chat:", error);
        showErrorNotification(
          setPopup,
          "Failed to delete chat. Please try again."
        );
      }
    }

    async function performMove(targetProjectId: number) {
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
        setShowMoveOptions(false);
        setSearchTerm("");
      } catch (error) {
        // handleMoveOperation already handles error notification
        console.error("Failed to move chat:", error);
      }
    }

    async function handleChatMove(targetProject: Project) {
      if (shouldShowMoveModal(chatSession)) {
        setPendingMoveProjectId(targetProject.id);
        setShowMoveCustomAgentModal(true);
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

    async function handleCreateProjectAndMove(projectName: string) {
      try {
        // Create the new project using the service directly (without navigation)
        const newProject = await createProjectService(projectName);

        // Refresh projects list to include the new project
        await fetchProjects();

        // Mark that we want to navigate to this project after moving
        setNavigateAfterMoveProjectId(newProject.id);

        // Check if we should show the move modal for custom agents
        if (shouldShowMoveModal(chatSession)) {
          setPendingMoveProjectId(newProject.id);
          setShowMoveCustomAgentModal(true);
          setShowMoveOptions(false);
          setSearchTerm("");
          return;
        }

        // Move the chat to the newly created project
        await performMove(newProject.id);

        // Navigate to the new project to see the chat
        route({ projectId: newProject.id });
        setNavigateAfterMoveProjectId(null);
      } catch (error) {
        console.error("Failed to create project and move chat:", error);
        showErrorNotification(
          setPopup,
          "Failed to create project. Please try again."
        );
        setNavigateAfterMoveProjectId(null);
      }
    }

    const rightMenu = (
      <>
        <PopoverTrigger asChild onClick={noProp()}>
          <div>
            <IconButton
              icon={SvgMoreHorizontal}
              className={cn(
                !popoverOpen && "hidden",
                !renaming && "group-hover/SidebarTab:flex"
              )}
              transient={popoverOpen}
              internal
            />
          </div>
        </PopoverTrigger>
        <PopoverContent side="right" align="start">
          <PopoverMenu>{popoverItems}</PopoverMenu>
        </PopoverContent>
      </>
    );

    const popover = (
      <Popover
        onOpenChange={(state) => {
          setPopoverOpen(state);
          if (!state) {
            setShowMoveOptions(false);
            setSearchTerm("");
          }
        }}
      >
        <PopoverAnchor>
          <SidebarTab
            onClick={handleClick}
            transient={active}
            rightChildren={rightMenu}
            focused={renaming}
          >
            {renaming ? (
              <ButtonRenaming
                initialName={chatSession.name}
                onRename={handleRename}
                onClose={() => setRenaming(false)}
              />
            ) : (
              displayName
            )}
          </SidebarTab>
        </PopoverAnchor>
      </Popover>
    );

    return (
      <>
        {popup}

        {deleteConfirmationModalOpen && (
          <ConfirmationModalLayout
            title="Delete Chat"
            icon={SvgTrash}
            onClose={() => setDeleteConfirmationModalOpen(false)}
            submit={
              <Button
                danger
                onClick={() => {
                  setDeleteConfirmationModalOpen(false);
                  handleChatDelete();
                }}
              >
                Delete
              </Button>
            }
          >
            Are you sure you want to delete this chat? This action cannot be
            undone.
          </ConfirmationModalLayout>
        )}

        {showMoveCustomAgentModal && (
          <MoveCustomAgentChatModal
            onCancel={() => {
              setShowMoveCustomAgentModal(false);
              setPendingMoveProjectId(null);
              setNavigateAfterMoveProjectId(null);
            }}
            onConfirm={async (doNotShowAgain: boolean) => {
              if (doNotShowAgain && typeof window !== "undefined") {
                window.localStorage.setItem(
                  LOCAL_STORAGE_KEYS.HIDE_MOVE_CUSTOM_AGENT_MODAL,
                  "true"
                );
              }
              const target = pendingMoveProjectId;
              const shouldNavigate = navigateAfterMoveProjectId;
              setShowMoveCustomAgentModal(false);
              setPendingMoveProjectId(null);
              if (target != null) {
                await performMove(target);
                // Navigate if this was triggered by creating a new project
                if (shouldNavigate != null) {
                  route({ projectId: shouldNavigate });
                  setNavigateAfterMoveProjectId(null);
                }
              }
            }}
          />
        )}

        {showShareModal && (
          <ShareChatSessionModal
            chatSession={chatSession}
            onClose={() => setShowShareModal(false)}
          />
        )}

        {draggable ? (
          <div
            ref={setNodeRef}
            style={{
              transform: transform
                ? `translate3d(0px, ${transform.y}px, 0)`
                : undefined,
              opacity: isDragging ? 0.5 : 1,
            }}
            {...(mounted ? attributes : {})}
            {...(mounted ? listeners : {})}
          >
            {popover}
          </div>
        ) : (
          popover
        )}
      </>
    );
  }
);
ChatButton.displayName = "ChatButton";

export default ChatButton;
