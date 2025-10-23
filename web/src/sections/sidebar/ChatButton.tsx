"use client";

import React, { useState, memo, useMemo, useEffect } from "react";
import { useDraggable } from "@dnd-kit/core";
import SvgMoreHorizontal from "@/icons/more-horizontal";
import { useChatContext } from "@/refresh-components/contexts/ChatContext";
import SvgBubbleText from "@/icons/bubble-text";
import { deleteChatSession, renameChatSession } from "@/app/chat/services/lib";
import { ChatSession } from "@/app/chat/interfaces";
import ConfirmationModal from "@/refresh-components/modals/ConfirmationModal";
import SvgTrash from "@/icons/trash";
import SvgShare from "@/icons/share";
import SvgEdit from "@/icons/edit";
import Button from "@/refresh-components/buttons/Button";
import { cn, noProp } from "@/lib/utils";
import {
  Popover,
  PopoverContent,
  PopoverMenu,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useAppParams, useAppRouter } from "@/hooks/appNavigation";
import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";
import {
  Project,
  removeChatSessionFromProject,
} from "@/app/chat/projects/projectsService";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import SvgFolderIn from "@/icons/folder-in";
import SvgFolder from "@/icons/folder";
import SvgChevronLeft from "@/icons/chevron-left";
import MoveCustomAgentChatModal from "@/components/modals/MoveCustomAgentChatModal";
import { UNNAMED_CHAT } from "@/lib/constants";
import ShareChatSessionModal from "@/app/chat/components/modal/ShareChatSessionModal";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import IconButton from "@/refresh-components/buttons/IconButton";
import MenuButton from "@/refresh-components/buttons/MenuButton";
import { PopoverAnchor } from "@radix-ui/react-popover";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { usePopup } from "@/components/admin/connectors/Popup";
import {
  DRAG_TYPES,
  DEFAULT_PERSONA_ID,
  LOCAL_STORAGE_KEYS,
} from "@/sections/sidebar/constants";
import {
  shouldShowMoveModal,
  showErrorNotification,
  handleMoveOperation,
} from "@/sections/sidebar/sidebarUtils";
import ButtonRenaming from "@/sections/sidebar/ButtonRenaming";

// (no local constants; use shared constants/imports)

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

interface ChatButtonProps {
  chatSession: ChatSession;
  project?: Project;
  draggable?: boolean;
}

function ChatButtonInner({
  chatSession,
  project,
  draggable = false,
}: ChatButtonProps) {
  const route = useAppRouter();
  const params = useAppParams();
  const [mounted, setMounted] = useState(false);
  const [name, setName] = useState(chatSession.name || UNNAMED_CHAT);
  const [renaming, setRenaming] = useState(false);
  const [deleteConfirmationModalOpen, setDeleteConfirmationModalOpen] =
    useState(false);
  const [showMoveOptions, setShowMoveOptions] = useState(false);
  const [showShareModal, setShowShareModal] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [popoverItems, setPopoverItems] = useState<React.ReactNode[]>([]);
  const { refreshChatSessions } = useChatContext();
  const {
    refreshCurrentProjectDetails,
    projects,
    fetchProjects,
    currentProjectId,
  } = useProjectsContext();
  const { popup, setPopup } = usePopup();
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [pendingMoveProjectId, setPendingMoveProjectId] = useState<
    number | null
  >(null);
  const [showMoveCustomAgentModal, setShowMoveCustomAgentModal] =
    useState(false);
  const isChatUsingDefaultAssistant =
    chatSession.persona_id === DEFAULT_PERSONA_ID;
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
  useEffect(() => {
    setMounted(true);
  }, []);
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
        <MenuButton
          key="share"
          icon={SvgShare}
          onClick={noProp(() => setShowShareModal(true))}
        >
          Share
        </MenuButton>,
        <MenuButton
          key="rename"
          icon={SvgEdit}
          onClick={noProp(() => setRenaming(true))}
        >
          Rename
        </MenuButton>,
        <MenuButton
          key="move"
          icon={SvgFolderIn}
          onClick={noProp(() => setShowMoveOptions(true))}
        >
          Move to Project
        </MenuButton>,
        project && (
          <MenuButton
            key="remove"
            icon={SvgFolder}
            onClick={noProp(() => handleRemoveFromProject())}
          >
            {`Remove from ${project.name}`}
          </MenuButton>
        ),
        null,
        <MenuButton
          key="delete"
          icon={SvgTrash}
          onClick={noProp(() => setDeleteConfirmationModalOpen(true))}
          danger
        >
          Delete
        </MenuButton>,
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
            <MenuButton
              key={targetProject.id}
              icon={SvgFolder}
              onClick={noProp(() => handleChatMove(targetProject))}
            >
              {targetProject.name}
            </MenuButton>
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

  async function handleRename(newName: string) {
    setName(newName);
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
        if (params(SEARCH_PARAM_NAMES.CHAT_ID) == chatSession.id) {
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
            active={popoverOpen}
            internal
          />
        </div>
      </PopoverTrigger>
      <PopoverContent side="right" align="end">
        <PopoverMenu>{popoverItems}</PopoverMenu>
      </PopoverContent>
    </>
  );

  const popover = (
    <Popover
      onOpenChange={(state) => {
        setPopoverOpen(state);
        if (!state) setShowMoveOptions(false);
      }}
    >
      <PopoverAnchor>
        <SidebarTab
          leftIcon={project ? () => <></> : SvgBubbleText}
          onClick={() => route({ chatSessionId: chatSession.id })}
          active={params(SEARCH_PARAM_NAMES.CHAT_ID) === chatSession.id}
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
            name
          )}
        </SidebarTab>
      </PopoverAnchor>
    </Popover>
  );

  return (
    <>
      {popup}

      {deleteConfirmationModalOpen && (
        <ConfirmationModal
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
        </ConfirmationModal>
      )}

      {showMoveCustomAgentModal && (
        <MoveCustomAgentChatModal
          onCancel={() => {
            setShowMoveCustomAgentModal(false);
            setPendingMoveProjectId(null);
          }}
          onConfirm={async (doNotShowAgain: boolean) => {
            if (doNotShowAgain && typeof window !== "undefined") {
              window.localStorage.setItem(
                LOCAL_STORAGE_KEYS.HIDE_MOVE_CUSTOM_AGENT_MODAL,
                "true"
              );
            }
            const target = pendingMoveProjectId;
            setShowMoveCustomAgentModal(false);
            setPendingMoveProjectId(null);
            if (target != null) {
              await performMove(target);
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

const ChatButton = memo(ChatButtonInner);
export default ChatButton;
