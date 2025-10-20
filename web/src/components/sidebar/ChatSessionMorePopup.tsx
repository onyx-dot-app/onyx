"use client";

import { ChatSession } from "@/app/chat/interfaces";
import { deleteChatSession } from "@/app/chat/services/lib";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import {
  moveChatSession as moveChatSessionService,
  removeChatSessionFromProject as removeChatSessionFromProjectService,
} from "@/app/chat/projects/projectsService";
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
  PopoverMenu,
} from "@/components/ui/popover";
import { FiMoreHorizontal } from "react-icons/fi";
import { useChatContext } from "@/refresh-components/contexts/ChatContext";
import { useCallback, useState, useMemo } from "react";
import MoveCustomAgentChatModal from "@/components/modals/MoveCustomAgentChatModal";
// PopoverMenu already imported above
import MenuButton from "@/refresh-components/buttons/MenuButton";
import SvgShare from "@/icons/share";
import SvgFolderIn from "@/icons/folder-in";
import SvgTrash from "@/icons/trash";
import SvgFolder from "@/icons/folder";
import { cn, noProp } from "@/lib/utils";
import ConfirmationModal from "@/refresh-components/modals/ConfirmationModal";
import Button from "@/refresh-components/buttons/Button";
import { PopoverSearchInput } from "@/sections/sidebar/ChatButton";
// Constants
const DEFAULT_PERSONA_ID = 0;
const LS_HIDE_MOVE_CUSTOM_AGENT_MODAL_KEY = "onyx:hideMoveCustomAgentModal";

interface ChatSessionMorePopupProps {
  chatSession: ChatSession;
  projectId?: number;
  isRenamingChat: boolean;
  setIsRenamingChat: (value: boolean) => void;
  showShareModal?: (chatSession: ChatSession) => void;
  afterDelete?: () => void;
  afterMove?: () => void;
  afterRemoveFromProject?: () => void;
  search?: boolean;
  iconSize?: number;
  isVisible?: boolean;
}

export function ChatSessionMorePopup({
  chatSession,
  projectId,
  isRenamingChat: _isRenamingChat,
  setIsRenamingChat: _setIsRenamingChat,
  showShareModal,
  afterDelete,
  afterMove,
  afterRemoveFromProject,
  search,
  iconSize = 16,
  isVisible = false,
}: ChatSessionMorePopupProps) {
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const { refreshChatSessions } = useChatContext();
  const { fetchProjects, projects } = useProjectsContext();

  const [pendingMoveProjectId, setPendingMoveProjectId] = useState<
    number | null
  >(null);
  const [showMoveCustomAgentModal, setShowMoveCustomAgentModal] =
    useState(false);

  const isChatUsingDefaultAssistant =
    chatSession.persona_id === DEFAULT_PERSONA_ID;

  const [showMoveOptions, setShowMoveOptions] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");

  const filteredProjects = projects.filter((project) =>
    project.name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const handlePopoverOpenChange = useCallback((open: boolean) => {
    setPopoverOpen(open);
  }, []);

  const handleConfirmDelete = useCallback(
    async (e: React.MouseEvent<HTMLButtonElement>) => {
      e.stopPropagation();
      await deleteChatSession(chatSession.id);
      await refreshChatSessions();
      await fetchProjects();
      setIsDeleteModalOpen(false);
      setPopoverOpen(false);
      afterDelete?.();
    },
    [chatSession, refreshChatSessions, fetchProjects, afterDelete]
  );

  const performMove = useCallback(
    async (targetProjectId: number) => {
      await moveChatSessionService(targetProjectId, chatSession.id);
      await fetchProjects();
      await refreshChatSessions();
      setPopoverOpen(false);
      afterMove?.();
    },
    [chatSession.id, fetchProjects, refreshChatSessions, afterMove]
  );

  const handleMoveChatSession = useCallback(
    async (item: { id: number; label: string }) => {
      const targetProjectId = item.id;
      const hideModal =
        typeof window !== "undefined" &&
        window.localStorage.getItem(LS_HIDE_MOVE_CUSTOM_AGENT_MODAL_KEY) ===
          "true";

      if (!isChatUsingDefaultAssistant && !hideModal) {
        setPendingMoveProjectId(targetProjectId);
        setShowMoveCustomAgentModal(true);
        return;
      }

      await performMove(targetProjectId);
    },
    [isChatUsingDefaultAssistant, performMove]
  );

  const handleRemoveChatSessionFromProject = useCallback(async () => {
    await removeChatSessionFromProjectService(chatSession.id);
    await fetchProjects();
    await refreshChatSessions();
    afterRemoveFromProject?.();
    setPopoverOpen(false);
  }, [
    chatSession.id,
    fetchProjects,
    refreshChatSessions,
    removeChatSessionFromProjectService,
    afterRemoveFromProject,
  ]);

  // Build popover items similar to AppSidebar (no rename here)
  const popoverItems = useMemo(() => {
    if (!showMoveOptions) {
      return [
        showShareModal && (
          <MenuButton
            key="share"
            icon={SvgShare}
            onClick={noProp(() => showShareModal(chatSession))}
          >
            Share
          </MenuButton>
        ),
        <MenuButton
          key="move"
          icon={SvgFolderIn}
          onClick={noProp(() => setShowMoveOptions(true))}
        >
          Move to Project
        </MenuButton>,
        projectId && (
          <MenuButton
            key="remove"
            icon={SvgFolder}
            onClick={noProp(() => handleRemoveChatSessionFromProject())}
          >
            {`Remove from ${
              projects.find((p) => p.id === projectId)?.name ?? "Project"
            }`}
          </MenuButton>
        ),
        null,
        <MenuButton
          key="delete"
          icon={SvgTrash}
          onClick={noProp(() => setIsDeleteModalOpen(true))}
          danger
        >
          Delete
        </MenuButton>,
      ];
    }
    return [
      <PopoverSearchInput
        key="search"
        setShowMoveOptions={setShowMoveOptions}
        onSearch={setSearchTerm}
      />,
      ...filteredProjects
        .filter((candidate) => candidate.id !== projectId)
        .map((target) => (
          <MenuButton
            key={target.id}
            icon={SvgFolder}
            onClick={noProp(() =>
              handleMoveChatSession({ id: target.id, label: target.name })
            )}
          >
            {target.name}
          </MenuButton>
        )),
    ];
  }, [
    showMoveOptions,
    showShareModal,
    projects,
    projectId,
    filteredProjects,
    chatSession,
    setShowMoveOptions,
    setSearchTerm,
    handleMoveChatSession,
    handleRemoveChatSessionFromProject,
  ]);

  return (
    <div>
      <div className="-my-1">
        <Popover open={popoverOpen} onOpenChange={handlePopoverOpenChange}>
          <PopoverTrigger
            asChild
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              handlePopoverOpenChange(!popoverOpen);
            }}
          >
            <div
              className={cn(
                "p-1 rounded cursor-pointer select-none transition-opacity duration-150",
                isVisible || popoverOpen
                  ? "opacity-100 pointer-events-auto"
                  : "opacity-0 pointer-events-none"
              )}
            >
              <FiMoreHorizontal size={iconSize} />
            </div>
          </PopoverTrigger>
          <PopoverContent
            align="end"
            side="right"
            avoidCollisions
            sideOffset={8}
          >
            <PopoverMenu>{popoverItems}</PopoverMenu>
          </PopoverContent>
        </Popover>
      </div>
      {isDeleteModalOpen && (
        <ConfirmationModal
          title="Delete Chat"
          icon={SvgTrash}
          onClose={() => setIsDeleteModalOpen(false)}
          submit={
            <Button danger onClick={handleConfirmDelete}>
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
                LS_HIDE_MOVE_CUSTOM_AGENT_MODAL_KEY,
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
    </div>
  );
}
