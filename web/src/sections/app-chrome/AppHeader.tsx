"use client";

import { cn } from "@opal/utils";
import Text from "@/refresh-components/texts/Text";
import { useCallback, useMemo, useState, useEffect } from "react";
import ShareChatSessionModal from "@/sections/modals/ShareChatSessionModal";
import IconButton from "@/refresh-components/buttons/IconButton";
import { useProjectsContext } from "@/providers/ProjectsContext";
import useChatSessions from "@/hooks/useChatSessions";
import {
  handleMoveOperation,
  shouldShowMoveModal,
  showErrorNotification,
} from "@/sections/sidebar/sidebarUtils";
import { LOCAL_STORAGE_KEYS } from "@/sections/sidebar/constants";
import { deleteChatSession } from "@/app/app/services/lib";
import { useRouter } from "next/navigation";
import MoveCustomAgentChatModal from "@/sections/modals/MoveCustomAgentChatModal";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import FrostedDiv from "@/refresh-components/FrostedDiv";
import { Popover, PopoverMenu } from "@opal/components";
import { PopoverSearchInput } from "@/sections/sidebar/ChatButton";
import SimplePopover from "@/refresh-components/SimplePopover";
import { Button, LineItemButton, OpenButton } from "@opal/components";
import { useSidebarState } from "@/layouts/sidebar-layouts";
import useScreenSize from "@/hooks/useScreenSize";
import {
  SvgBubbleText,
  SvgFolderIn,
  SvgMoreHorizontal,
  SvgSearchMenu,
  SvgShare,
  SvgSidebar,
  SvgTrash,
} from "@opal/icons";
import { useSettingsContext } from "@/providers/SettingsProvider";
import type { AppMode } from "@/providers/QueryControllerProvider";
import useAppFocus from "@/hooks/useAppFocus";
import { useQueryController } from "@/providers/QueryControllerProvider";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/interfaces/settings";
import { noProp } from "@/lib/utils";

export default function AppHeader() {
  const appFocus = useAppFocus();

  if (appFocus.isSharedChat()) return null;

  return <AppHeaderInner />;
}

function AppHeaderInner() {
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const { state, setAppMode } = useQueryController();
  const settings = useSettingsContext();
  const { isMobile } = useScreenSize();
  const { setFolded } = useSidebarState();
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
  const [modePopoverOpen, setModePopoverOpen] = useState(false);
  const {
    projects,
    fetchProjects,
    refreshCurrentProjectDetails,
    currentProjectId,
  } = useProjectsContext();
  const { currentChatSession, refreshChatSessions, removeSession } =
    useChatSessions();
  const router = useRouter();
  const appFocus = useAppFocus();

  const customHeaderContent =
    settings?.enterpriseSettings?.custom_header_content;
  const pageWithHeaderContent = appFocus.isChat() || appFocus.isNewSession();

  const effectiveMode: AppMode =
    appFocus.isNewSession() && state.phase === "idle" ? state.appMode : "chat";

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
        await handleMoveOperation({
          chatSession: currentChatSession,
          targetProjectId,
          refreshChatSessions,
          refreshCurrentProjectDetails,
          fetchProjects,
          currentProjectId,
        });
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
      removeSession(currentChatSession.id);
      await Promise.all([refreshChatSessions(), fetchProjects()]);
      router.replace("/app");
      setDeleteModalOpen(false);
    } catch (error) {
      console.error("Failed to delete chat:", error);
      showErrorNotification("Failed to delete chat. Please try again.");
    }
  }, [
    currentChatSession,
    refreshChatSessions,
    removeSession,
    fetchProjects,
    router,
  ]);

  const setDeleteConfirmationModalOpen = useCallback((open: boolean) => {
    setDeleteModalOpen(open);
    if (open) {
      setPopoverOpen(false);
    }
  }, []);

  useEffect(() => {
    const items = showMoveOptions
      ? [
          <PopoverSearchInput
            key="search"
            setShowMoveOptions={setShowMoveOptions}
            onSearch={setSearchTerm}
          />,
          ...filteredProjects.map((project) => (
            <LineItemButton
              key={project.id}
              sizePreset="main-ui"
              rounding="sm"
              icon={SvgFolderIn}
              title={project.name}
              onClick={noProp(() => handleMoveClick(project.id))}
            />
          )),
        ]
      : [
          <LineItemButton
            key="move"
            sizePreset="main-ui"
            rounding="sm"
            icon={SvgFolderIn}
            title="Move to Project"
            onClick={noProp(() => setShowMoveOptions(true))}
          />,
          <LineItemButton
            key="delete"
            sizePreset="main-ui"
            rounding="sm"
            color="danger"
            icon={SvgTrash}
            title="Delete"
            onClick={noProp(() => setDeleteConfirmationModalOpen(true))}
          />,
        ];

    setPopoverItems(items);
  }, [
    showMoveOptions,
    filteredProjects,
    currentChatSession,
    setDeleteConfirmationModalOpen,
    handleMoveClick,
  ]);

  return (
    <>
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
            <Button variant="danger" onClick={handleDeleteChat}>
              Delete
            </Button>
          }
        >
          Are you sure you want to delete this chat? This action cannot be
          undone.
        </ConfirmationModalLayout>
      )}

      <div
        className={cn(
          "w-full flex flex-row flex-wrap justify-center items-center px-4",
          // # Note (@raunakab):
          //
          // We add an additional top margin to align this header with the `LogoSection` inside of the App-Sidebar.
          // For more information, check out `SidebarWrapper.tsx`.
          "mt-2"
        )}
      >
        {/*
          Left:
          - (mobile) sidebar toggle
          - app-mode (for Unified S+C [EE gated])
        */}
        <div className="flex-1 flex flex-row items-center gap-2 h-[3.3rem]">
          {isMobile && (
            <Button
              prominence="internal"
              icon={SvgSidebar}
              onClick={() => setFolded(false)}
            />
          )}
          {businessTier &&
            settings.isSearchModeAvailable &&
            appFocus.isNewSession() &&
            state.phase === "idle" && (
              <Popover open={modePopoverOpen} onOpenChange={setModePopoverOpen}>
                <Popover.Trigger asChild>
                  <OpenButton
                    aria-label="Change app mode"
                    icon={
                      effectiveMode === "search" ? SvgSearchMenu : SvgBubbleText
                    }
                  >
                    {effectiveMode === "search" ? "Search" : "Chat"}
                  </OpenButton>
                </Popover.Trigger>
                <Popover.Content align="start" width="lg">
                  <Popover.Menu>
                    <LineItemButton
                      sizePreset="main-ui"
                      rounding="sm"
                      icon={SvgSearchMenu}
                      state={effectiveMode === "search" ? "selected" : "empty"}
                      title="Search"
                      description="Quick search for documents"
                      onClick={noProp(() => {
                        setAppMode("search");
                        setModePopoverOpen(false);
                      })}
                    />
                    <LineItemButton
                      sizePreset="main-ui"
                      rounding="sm"
                      icon={SvgBubbleText}
                      state={effectiveMode === "chat" ? "selected" : "empty"}
                      title="Chat"
                      description="Conversation and research"
                      onClick={noProp(() => {
                        setAppMode("chat");
                        setModePopoverOpen(false);
                      })}
                    />
                  </Popover.Menu>
                </Popover.Content>
              </Popover>
            )}
        </div>

        {/*
          Center:
          - custom-header-content
          - Wraps to its own row below left/right on mobile when content is present
        */}
        <div
          className={cn(
            "flex flex-col items-center overflow-hidden",
            pageWithHeaderContent && customHeaderContent
              ? "order-last basis-full py-2 sm:py-0 sm:order-0 sm:basis-auto sm:flex-1"
              : "flex-1"
          )}
        >
          <Text text03 className="text-center w-full">
            {pageWithHeaderContent && customHeaderContent}
          </Text>
        </div>

        {/*
          Right:
          - share button
          - more-options buttons
        */}
        <div className="flex flex-1 justify-end items-center h-[3.3rem]">
          {appFocus.isChat() && currentChatSession && (
            <FrostedDiv className="flex shrink flex-row items-center">
              <Button
                icon={SvgShare}
                prominence="tertiary"
                interaction={showShareModal ? "hover" : "rest"}
                responsiveHideText
                onClick={() => setShowShareModal(true)}
                aria-label="share-chat-button"
              >
                Share
              </Button>
              <SimplePopover
                trigger={
                  /* TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved */
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
            </FrostedDiv>
          )}
        </div>
      </div>
    </>
  );
}
