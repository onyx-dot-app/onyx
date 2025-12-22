"use client";

import { cn, noProp } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import { useCallback, useMemo, useState, useEffect } from "react";
import ShareChatSessionModal from "@/app/chat/components/modal/ShareChatSessionModal";
import IconButton from "@/refresh-components/buttons/IconButton";
import LineItem from "@/refresh-components/buttons/LineItem";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import useChatSessions from "@/hooks/useChatSessions";
import { usePopup } from "@/components/admin/connectors/Popup";
import {
  handleMoveOperation,
  shouldShowMoveModal,
  showErrorNotification,
} from "@/sections/sidebar/sidebarUtils";
import { LOCAL_STORAGE_KEYS } from "@/sections/sidebar/constants";
import { deleteChatSession } from "@/app/chat/services/lib";
import { useRouter } from "next/navigation";
import MoveCustomAgentChatModal from "@/components/modals/MoveCustomAgentChatModal";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { PopoverMenu } from "@/components/ui/popover";
import { PopoverSearchInput } from "@/sections/sidebar/ChatButton";
import SimplePopover from "@/refresh-components/SimplePopover";
import { useAppSidebarContext } from "@/refresh-components/contexts/AppSidebarContext";
import useScreenSize from "@/hooks/useScreenSize";
import {
  SvgFolderIn,
  SvgMoreHorizontal,
  SvgShare,
  SvgSidebar,
  SvgTrash,
} from "@opal/icons";
import { useSettingsContext } from "@/components/settings/SettingsProvider";

export default function ChatHeader() {
  const settings = useSettingsContext();
  const { isMobile } = useScreenSize();
  const { setFolded } = useAppSidebarContext();
  const [showShareModal, setShowShareModal] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [showMoveCustomAgentModal, setShowMoveCustomAgentModal] =
    useState(false);
  const [pendingMoveProjectId, setPendingMoveProjectId] = useState<
    number | null
  >(null);
  const [showMoveOptions, setShowMoveOptions] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [popoverItems, setPopoverItems] = useState<React.ReactNode[]>([]);
  const {
    projects,
    fetchProjects,
    refreshCurrentProjectDetails,
    currentProjectId,
  } = useProjectsContext();
  const { currentChatSession, refreshChatSessions, currentChatSessionId } =
    useChatSessions();
  const { popup, setPopup } = usePopup();
  const router = useRouter();

  const customHeaderContent =
    settings?.enterpriseSettings?.custom_header_content;

  const availableProjects = useMemo(() => {
    if (!projects) return [];
    return projects.filter((project) => project.id !== currentProjectId);
  }, [projects, currentProjectId]);

  const filteredProjects = useMemo(() => {
    if (!searchTerm) return availableProjects;
    const term = searchTerm.toLowerCase();
    return availableProjects.filter((project) =>
      project.name.toLowerCase().includes(term)
    );
  }, [availableProjects, searchTerm]);

  const resetMoveState = useCallback(() => {
    setShowMoveOptions(false);
    setSearchTerm("");
    setPendingMoveProjectId(null);
    setShowMoveCustomAgentModal(false);
  }, []);

  const performMove = useCallback(
    async (targetProjectId: number) => {
      if (!currentChatSession) return;
      try {
        await handleMoveOperation(
          {
            chatSession: currentChatSession,
            targetProjectId,
            refreshChatSessions,
            refreshCurrentProjectDetails,
            fetchProjects,
            currentProjectId,
          },
          setPopup
        );
        resetMoveState();
        setPopoverOpen(false);
      } catch (error) {
        console.error("Failed to move chat session:", error);
      }
    },
    [
      currentChatSession,
      refreshChatSessions,
      refreshCurrentProjectDetails,
      fetchProjects,
      currentProjectId,
      setPopup,
      resetMoveState,
    ]
  );

  const handleMoveClick = useCallback(
    (projectId: number) => {
      if (!currentChatSession) return;
      if (shouldShowMoveModal(currentChatSession)) {
        setPendingMoveProjectId(projectId);
        setShowMoveCustomAgentModal(true);
        return;
      }
      void performMove(projectId);
    },
    [currentChatSession, performMove]
  );

  const handleDeleteChat = useCallback(async () => {
    if (!currentChatSession) return;
    try {
      const response = await deleteChatSession(currentChatSession.id);
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
  }, [
    currentChatSession,
    refreshChatSessions,
    fetchProjects,
    router,
    setPopup,
  ]);

  const setDeleteConfirmationModalOpen = useCallback((open: boolean) => {
    setDeleteModalOpen(open);
    if (open) {
      setPopoverOpen(false);
    }
  }, []);

  useEffect(() => {
    if (!showMoveOptions) {
      const items = [
        <LineItem
          key="move"
          icon={SvgFolderIn}
          onClick={noProp(() => setShowMoveOptions(true))}
        >
          Move to Project
        </LineItem>,
        <LineItem
          key="delete"
          icon={SvgTrash}
          onClick={noProp(() => setDeleteConfirmationModalOpen(true))}
          danger
        >
          Delete
        </LineItem>,
      ];
      setPopoverItems(items);
    } else {
      const items = [
        <PopoverSearchInput
          key="search"
          setShowMoveOptions={setShowMoveOptions}
          onSearch={setSearchTerm}
        />,
        ...filteredProjects.map((project) => (
          <LineItem
            key={project.id}
            icon={SvgFolderIn}
            onClick={noProp(() => handleMoveClick(project.id))}
          >
            {project.name}
          </LineItem>
        )),
      ];
      setPopoverItems(items);
    }
  }, [
    showMoveOptions,
    filteredProjects,
    currentChatSession,
    setDeleteConfirmationModalOpen,
    handleMoveClick,
  ]);

  return (
    <>
      {popup}

      {showShareModal && currentChatSession && (
        <ShareChatSessionModal
          chatSession={currentChatSession}
          onClose={() => setShowShareModal(false)}
        />
      )}

      {showMoveCustomAgentModal && (
        <MoveCustomAgentChatModal
          onCancel={resetMoveState}
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

      <header className="w-full flex flex-row justify-center items-center py-3 px-4 h-16">
        {/* Left - contains the icon-button to fold the AppSidebar on mobile */}
        <div className="flex-1">
          <IconButton
            icon={SvgSidebar}
            onClick={() => setFolded(false)}
            className={cn(!isMobile && "invisible")}
            internal
          />
        </div>

        {/* Center - contains the custom-header-content */}
        <div className="flex-1 flex flex-col items-center">
          <Text text03>{customHeaderContent}</Text>
        </div>

        {/* Right - contains the share and more-options buttons */}
        <div
          className={cn(
            "flex-1 flex flex-row items-center justify-end px-1",
            !currentChatSessionId && "invisible"
          )}
        >
          <Button
            leftIcon={SvgShare}
            transient={showShareModal}
            tertiary
            onClick={() => setShowShareModal(true)}
          >
            Share Chat
          </Button>
          <SimplePopover
            trigger={
              <IconButton
                icon={SvgMoreHorizontal}
                className="ml-2"
                transient={popoverOpen}
                tertiary
              />
            }
            onOpenChange={(state) => {
              setPopoverOpen(state);
              if (!state) setShowMoveOptions(false);
            }}
            side="bottom"
            align="end"
          >
            <PopoverMenu>{popoverItems}</PopoverMenu>
          </SimplePopover>
        </div>
      </header>
    </>
  );
}
