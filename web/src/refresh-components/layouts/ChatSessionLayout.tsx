"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ChatSession } from "@/app/chat/interfaces";
import {
  useHeaderActions,
  useHeaderActionsValue,
} from "@/refresh-components/contexts/HeaderActionsContext";
import Button from "@/refresh-components/buttons/Button";
import SvgShare from "@/icons/share";
import ShareChatSessionModal from "@/app/chat/components/modal/ShareChatSessionModal";
import SimplePopover from "@/refresh-components/SimplePopover";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgMoreHorizontal from "@/icons/more-horizontal";
import MenuButton from "@/refresh-components/buttons/MenuButton";
import SvgFolderIn from "@/icons/folder-in";
import SvgTrash from "@/icons/trash";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import { useChatContext } from "@/refresh-components/contexts/ChatContext";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useRouter } from "next/navigation";
import { deleteChatSession } from "@/app/chat/services/lib";
import {
  handleMoveOperation,
  shouldShowMoveModal,
  showErrorNotification,
} from "@/sections/sidebar/sidebarUtils";
import { LOCAL_STORAGE_KEYS } from "@/sections/sidebar/constants";
import MoveCustomAgentChatModal from "@/components/modals/MoveCustomAgentChatModal";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { Modal } from "@/components/Modal";
import Text from "@/refresh-components/texts/Text";

interface ChatSessionLayoutProps {
  chatSession: ChatSession | null;
  children: React.ReactNode;
  reserveHeaderSpace?: boolean;
}

export default function ChatSessionLayout({
  chatSession,
  children,
  reserveHeaderSpace = true,
}: ChatSessionLayoutProps) {
  const {
    setHeaderActions,
    reserveHeaderSpace: reserveSlot,
    clearHeaderActions,
  } = useHeaderActions();
  const { reserveSpace } = useHeaderActionsValue();
  const [showShareModal, setShowShareModal] = useState(false);
  const [moveModalOpen, setMoveModalOpen] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [pendingMoveProjectId, setPendingMoveProjectId] = useState<
    number | null
  >(null);
  const [showMoveCustomAgentModal, setShowMoveCustomAgentModal] =
    useState(false);

  const {
    projects,
    fetchProjects,
    refreshCurrentProjectDetails,
    currentProjectId,
  } = useProjectsContext();
  const { refreshChatSessions } = useChatContext();
  const { popup, setPopup } = usePopup();
  const router = useRouter();

  useEffect(() => {
    if (!reserveHeaderSpace) {
      return;
    }
    reserveSlot();
    return () => {
      clearHeaderActions();
    };
  }, [reserveHeaderSpace, reserveSlot, clearHeaderActions]);

  useEffect(() => {
    if (!chatSession) {
      setHeaderActions(null);
      return;
    }

    const actions = (
      <div className="flex flex-row items-center">
        <Button
          leftIcon={SvgShare}
          transient={showShareModal}
          tertiary
          onClick={() => setShowShareModal(true)}
        >
          Share Chat
        </Button>
        <SimplePopover
          trigger={(open) => (
            <IconButton icon={SvgMoreHorizontal} tertiary transient={open} />
          )}
        >
          {(close) => (
            <div className="flex flex-col gap-1 min-w-[12rem]">
              <MenuButton
                icon={SvgFolderIn}
                onClick={() => {
                  close();
                  setMoveModalOpen(true);
                }}
              >
                Move to Project
              </MenuButton>
              <MenuButton
                icon={SvgTrash}
                danger
                onClick={() => {
                  close();
                  setDeleteModalOpen(true);
                }}
              >
                Delete
              </MenuButton>
            </div>
          )}
        </SimplePopover>
      </div>
    );

    setHeaderActions(actions);
    return () => {
      setHeaderActions(null);
    };
  }, [chatSession, showShareModal, setHeaderActions, reserveSpace]);

  const performMove = useCallback(
    async (targetProjectId: number) => {
      if (!chatSession) {
        return;
      }
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
        setMoveModalOpen(false);
      } catch (error) {
        console.error("Failed to move chat session:", error);
      } finally {
        setPendingMoveProjectId(null);
        setShowMoveCustomAgentModal(false);
      }
    },
    [
      chatSession,
      refreshChatSessions,
      refreshCurrentProjectDetails,
      fetchProjects,
      currentProjectId,
      setPopup,
    ]
  );

  const handleMoveSelection = useCallback(
    (projectId: number) => {
      if (!chatSession) return;
      if (shouldShowMoveModal(chatSession)) {
        setPendingMoveProjectId(projectId);
        setShowMoveCustomAgentModal(true);
        return;
      }
      void performMove(projectId);
    },
    [chatSession, performMove]
  );

  const handleDeleteChat = useCallback(async () => {
    if (!chatSession) return;
    try {
      const response = await deleteChatSession(chatSession.id);
      if (!response.ok) {
        throw new Error("Failed to delete chat session");
      }
      await Promise.all([refreshChatSessions(), fetchProjects()]);
      router.replace("/chat");
      setDeleteModalOpen(false);
    } catch (error) {
      console.error("Failed to delete chat:", error);
      showErrorNotification(
        setPopup,
        "Failed to delete chat. Please try again."
      );
    }
  }, [chatSession, refreshChatSessions, fetchProjects, router, setPopup]);

  const handleMoveModalClose = useCallback(() => {
    setMoveModalOpen(false);
    setPendingMoveProjectId(null);
    setShowMoveCustomAgentModal(false);
  }, []);

  const projectsWithoutCurrent = useMemo(() => {
    if (!projects) return [];
    return projects.filter((project) => project.id !== currentProjectId);
  }, [projects, currentProjectId]);

  return (
    <>
      {popup}
      {chatSession && showShareModal && (
        <ShareChatSessionModal
          chatSession={chatSession}
          onClose={() => setShowShareModal(false)}
        />
      )}
      {moveModalOpen && (
        <Modal
          title="Move Chat to Project"
          onOutsideClick={handleMoveModalClose}
          width="max-w-md"
          hideDividerForTitle
        >
          <div className="flex flex-col gap-3">
            <Text text03>
              Choose a project to move <b>{chatSession?.name || "this chat"}</b>{" "}
              into.
            </Text>
            <div className="flex flex-col gap-1">
              {projectsWithoutCurrent.length === 0 && (
                <Text text03>No available projects.</Text>
              )}
              {projectsWithoutCurrent.map((project) => (
                <MenuButton
                  key={project.id}
                  icon={SvgFolderIn}
                  onClick={() => handleMoveSelection(project.id)}
                >
                  {project.name}
                </MenuButton>
              ))}
            </div>
            <div className="flex justify-end">
              <Button tertiary onClick={handleMoveModalClose}>
                Cancel
              </Button>
            </div>
          </div>
        </Modal>
      )}
      {showMoveCustomAgentModal && (
        <MoveCustomAgentChatModal
          onCancel={handleMoveModalClose}
          onConfirm={async (doNotShowAgain: boolean) => {
            if (doNotShowAgain && typeof window !== "undefined") {
              window.localStorage.setItem(
                LOCAL_STORAGE_KEYS.HIDE_MOVE_CUSTOM_AGENT_MODAL,
                "true"
              );
            }
            if (pendingMoveProjectId != null) {
              await performMove(pendingMoveProjectId);
            }
          }}
        />
      )}
      {deleteModalOpen && (
        <ConfirmationModalLayout
          title="Delete Chat"
          icon={SvgTrash}
          onClose={() => setDeleteModalOpen(false)}
          submit={
            <Button danger onClick={handleDeleteChat}>
              Delete
            </Button>
          }
        >
          Are you sure you want to delete this chat? This action cannot be
          undone.
        </ConfirmationModalLayout>
      )}
      {children}
    </>
  );
}
