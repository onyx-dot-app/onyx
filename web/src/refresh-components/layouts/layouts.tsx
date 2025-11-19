"use client";

import { ChatSession } from "@/app/chat/interfaces";
import { cn, noProp } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import SvgShare from "@/icons/share";
import { CombinedSettings } from "@/app/admin/settings/interfaces";
import { useMemo, useState, useEffect } from "react";
import ShareChatSessionModal from "@/app/chat/components/modal/ShareChatSessionModal";
import { useChatPageLayout } from "@/app/chat/stores/useChatSessionStore";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgMoreHorizontal from "@/icons/more-horizontal";
import MenuButton from "@/refresh-components/buttons/MenuButton";
import SvgFolderIn from "@/icons/folder-in";
import SvgTrash from "@/icons/trash";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import { useChatContext } from "@/refresh-components/contexts/ChatContext";
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
import { FOLDED_SIZE } from "@/refresh-components/Logo";

interface AppPageProps extends React.HtmlHTMLAttributes<HTMLDivElement> {
  settings: CombinedSettings | null;
  chatSession: ChatSession | null;
}

export function AppPage({
  settings,
  chatSession,
  className,
  ...rest
}: AppPageProps) {
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
  const { showCenteredInput } = useChatPageLayout();
  const {
    projects,
    fetchProjects,
    refreshCurrentProjectDetails,
    currentProjectId,
  } = useProjectsContext();
  const { refreshChatSessions } = useChatContext();
  const { popup, setPopup } = usePopup();
  const router = useRouter();

  const customHeaderContent =
    settings?.enterpriseSettings?.custom_header_content;
  const useCustomLogo = settings?.enterpriseSettings?.use_custom_logo;
  const customFooterContent =
    settings?.enterpriseSettings?.custom_lower_disclaimer_content;

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

  const resetMoveState = () => {
    setShowMoveOptions(false);
    setSearchTerm("");
    setPendingMoveProjectId(null);
    setShowMoveCustomAgentModal(false);
  };

  const performMove = async (targetProjectId: number) => {
    if (!chatSession) return;
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
      resetMoveState();
      setPopoverOpen(false);
    } catch (error) {
      console.error("Failed to move chat session:", error);
    }
  };

  const handleMoveClick = (projectId: number) => {
    if (!chatSession) return;
    if (shouldShowMoveModal(chatSession)) {
      setPendingMoveProjectId(projectId);
      setShowMoveCustomAgentModal(true);
      return;
    }
    void performMove(projectId);
  };

  const handleDeleteChat = async () => {
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
  };

  const setDeleteConfirmationModalOpen = (open: boolean) => {
    setDeleteModalOpen(open);
    if (open) {
      setPopoverOpen(false);
    }
  };

  useEffect(() => {
    if (!showMoveOptions) {
      const popoverItems = [
        <MenuButton
          key="move"
          icon={SvgFolderIn}
          onClick={noProp(() => setShowMoveOptions(true))}
        >
          Move to Project
        </MenuButton>,
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
        ...filteredProjects.map((project) => (
          <MenuButton
            key={project.id}
            icon={SvgFolderIn}
            onClick={noProp(() => handleMoveClick(project.id))}
          >
            {project.name}
          </MenuButton>
        )),
      ];
      setPopoverItems(popoverItems);
    }
  }, [
    showMoveOptions,
    filteredProjects,
    handleMoveClick,
    setDeleteConfirmationModalOpen,
  ]);

  return (
    <>
      {popup}
      {showShareModal && chatSession && (
        <ShareChatSessionModal
          chatSession={chatSession}
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

      <div className="flex flex-col h-full w-full">
        {(customHeaderContent || !showCenteredInput) && (
          <header className="w-full flex flex-row justify-center items-center py-3 px-4 h-16">
            <div className="flex-1" />
            <div className="flex-1 flex flex-col items-center">
              <Text text03>{customHeaderContent}</Text>
            </div>
            <div className="flex-1 flex flex-row items-center justify-end px-1">
              <Button
                leftIcon={SvgShare}
                transient={showShareModal}
                tertiary
                onClick={() => setShowShareModal(true)}
                className={cn(showCenteredInput && "invisible")}
              >
                Share Chat
              </Button>
              <div className={cn(showCenteredInput && "invisible")}>
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
            </div>
          </header>
        )}

        <div className={cn("flex-1 overflow-auto", className)} {...rest} />

        {(useCustomLogo || customFooterContent) && (
          <footer className="w-full flex flex-row justify-center items-center gap-2 py-3">
            {useCustomLogo && (
              <img
                src="/api/enterprise-settings/logo"
                alt="Logo"
                style={{
                  objectFit: "contain",
                  height: FOLDED_SIZE,
                  width: FOLDED_SIZE,
                }}
                className="flex-shrink-0"
              />
            )}
            {customFooterContent && (
              <Text text03 secondaryBody>
                {customFooterContent}
              </Text>
            )}
          </footer>
        )}
      </div>
    </>
  );
}
