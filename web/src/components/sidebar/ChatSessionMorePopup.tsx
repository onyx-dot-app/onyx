"use client";

import { ChatSession } from "@/app/chat/interfaces";
import { deleteChatSession } from "@/app/chat/services/lib";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import {
  moveChatSession as moveChatSessionService,
  removeChatSessionFromProject as removeChatSessionFromProjectService,
} from "@/app/chat/projects/projectsService";
import { DefaultDropdownElement } from "@/components/Dropdown";
import { HoverDropdown } from "@/components/HoverDropdown";
import { Popover } from "@/components/popover/Popover";
import { FiEdit2, FiMoreHorizontal, FiShare2, FiTrash } from "react-icons/fi";
import { HiOutlineArrowUturnRight } from "react-icons/hi2";
import { useChatContext } from "@/components/context/ChatContext";
import { useCallback, useState } from "react";
import MoveCustomAgentChatModal from "@/components/modals/MoveCustomAgentChatModal";

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
}

export function ChatSessionMorePopup({
  chatSession,
  projectId,
  isRenamingChat,
  setIsRenamingChat,
  showShareModal,
  afterDelete,
  afterMove,
  afterRemoveFromProject,
  search,
  iconSize = 16,
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

  const handlePopoverOpenChange = useCallback(
    (open: boolean) => {
      setPopoverOpen(open);
      if (!open) {
        setIsDeleteModalOpen(false);
      }
    },
    [isDeleteModalOpen]
  );

  const handleDeleteClick = useCallback(() => {
    setIsDeleteModalOpen(true);
  }, []);

  const handleCancelDelete = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDeleteModalOpen(false);
    setPopoverOpen(false);
  }, []);

  const handleConfirmDelete = useCallback(
    async (e: React.MouseEvent) => {
      e.preventDefault();
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
      await refreshChatSessions({ skipRedirectOnMissing: true });
      setPopoverOpen(false);
      afterMove?.();
    },
    [chatSession.id, fetchProjects, refreshChatSessions, afterMove]
  );

  const handleMoveChatSession = useCallback(
    async (item: { id: string; label: string }) => {
      const targetProjectId = parseInt(item.id);
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
  }, [
    chatSession.id,
    fetchProjects,
    refreshChatSessions,
    removeChatSessionFromProjectService,
    afterRemoveFromProject,
  ]);

  return (
    <div>
      <div
        onClick={(e) => {
          e.preventDefault();
          setPopoverOpen(!popoverOpen);
        }}
        className="-my-1"
      >
        <Popover
          open={popoverOpen}
          onOpenChange={handlePopoverOpenChange}
          content={
            <div className="p-1 rounded">
              <FiMoreHorizontal
                onClick={() => setPopoverOpen(true)}
                size={iconSize}
              />
            </div>
          }
          popover={
            <div
              className={`border border-border text-text-dark rounded-lg bg-background z-50 ${
                isDeleteModalOpen ? "w-64" : "w-48"
              }`}
            >
              {!isDeleteModalOpen ? (
                <>
                  {showShareModal && (
                    <DefaultDropdownElement
                      name="Share"
                      icon={FiShare2}
                      onSelect={() => showShareModal(chatSession)}
                    />
                  )}
                  {!search && (
                    <DefaultDropdownElement
                      name="Rename"
                      icon={FiEdit2}
                      onSelect={() => setIsRenamingChat(true)}
                    />
                  )}
                  <DefaultDropdownElement
                    name="Delete"
                    icon={FiTrash}
                    onSelect={handleDeleteClick}
                  />
                  {projects.length > 0 && (
                    <HoverDropdown
                      label="Move to Project"
                      items={projects
                        .filter((project) => project.id !== projectId)
                        .map((project) => ({
                          id: project.id.toString(),
                          label: project.name,
                        }))}
                      onItemClick={handleMoveChatSession}
                      emptyMessage="No projects to move to"
                    />
                  )}
                  {projectId && (
                    <DefaultDropdownElement
                      name={`Remove from ${projects.find((p) => p.id === projectId)?.name ?? "Project"}`}
                      icon={HiOutlineArrowUturnRight}
                      onSelect={handleRemoveChatSessionFromProject}
                    />
                  )}
                </>
              ) : (
                <div className="p-3">
                  <p className="text-sm mb-3">
                    Are you sure you want to delete this chat?
                  </p>
                  <div className="flex justify-center gap-2">
                    <button
                      className="px-3 py-1 text-sm bg-background-200 rounded"
                      onClick={handleCancelDelete}
                    >
                      Cancel
                    </button>
                    <button
                      className="px-3 py-1 text-sm bg-red-500 text-white rounded"
                      onClick={handleConfirmDelete}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              )}
            </div>
          }
          requiresContentPadding
          sideOffset={6}
          triggerMaxWidth
        />
      </div>
      <MoveCustomAgentChatModal
        isOpen={showMoveCustomAgentModal}
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
    </div>
  );
}
