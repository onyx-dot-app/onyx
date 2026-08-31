"use client";

import { useTranslations } from "next-intl";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { RootLayout, RootLayoutRightPanelSlotContext } from "@opal/layouts";
import { cn, markdown } from "@opal/utils";
import { INTERACTIVE_SELECTOR, noProp } from "@/lib/utils";
import { useAppBackground } from "@/providers/AppBackgroundProvider";
import { useTheme } from "next-themes";
import useBrowserInfo from "@/hooks/useBrowserInfo";
import ShareChatSessionModal from "@/sections/modals/ShareChatSessionModal";
import { useProjectsContext } from "@/lib/projects/providers";
import useChatSessions from "@/hooks/useChatSessions";
import {
  shouldShowMoveModal,
  showErrorNotification,
} from "@/lib/sidebar/utils";
import { handleMoveOperation } from "@/lib/sidebar/svc";
import { LOCAL_STORAGE_KEYS } from "@/lib/sidebar/constants";
import { deleteChatSession, endIncognitoSession } from "@/app/app/services/lib";
import {
  exportChatSession,
  ChatExportFormat,
} from "@/lib/chat/exportChatSession";
import { UNNAMED_CHAT } from "@/lib/constants";
import { useRouter } from "next/navigation";
import { MoveCustomAgentChatModal } from "@/lib/agents/components";
import { ConfirmationModalLayout } from "@opal/layouts";
import FrostedDiv from "@/refresh-components/FrostedDiv";
import {
  Button,
  LineItemButton,
  OpenButton,
  Popover,
  PopoverMenu,
  Text,
} from "@opal/components";
import { PopoverSearchInput } from "@/sections/sidebar/ChatButton";
import SimplePopover from "@/refresh-components/SimplePopover";
import { useSidebarState } from "@opal/layouts";
import useScreenSize from "@/hooks/useScreenSize";
import {
  SvgBubbleText,
  SvgChevronLeft,
  SvgDownload,
  SvgFileText,
  SvgEyeOff,
  SvgFitWidth,
  SvgFolderIn,
  SvgFullWidth,
  SvgHash,
  SvgMoreHorizontal,
  SvgSearchMenu,
  SvgShare,
  SvgSidebar,
  SvgTrash,
  SvgX,
} from "@opal/icons";
import { useIsSearchModeAvailable, useSettings } from "@/lib/settings/hooks";
import type { AppMode } from "@/providers/QueryControllerProvider";
import { useAppDocumentTitle, useCustomFooterContent } from "@/lib/app/hooks";
import { useAppPosition } from "@/lib/position/hooks";
import { useQueryController } from "@/providers/QueryControllerProvider";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";
import { useFullWidthChat } from "@/providers/FullWidthChatProvider";
import { useIncognito } from "@/providers/IncognitoProvider";

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

function Header() {
  const t = useTranslations("chat.appChrome");
  const appPosition = useAppPosition();
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const { state, setAppMode } = useQueryController();
  const isSearchModeAvailable = useIsSearchModeAvailable();
  const settings = useSettings();
  const { isMobile } = useScreenSize();
  const { setFolded } = useSidebarState();
  const { fullWidthChat, toggleFullWidthChat } = useFullWidthChat();
  const {
    incognitoAvailable,
    incognitoEnabled,
    incognitoLocked,
    toggleIncognito,
    setIncognitoEnabled,
  } = useIncognito();
  const [showShareModal, setShowShareModal] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [showMoveCustomAgentModal, setShowMoveCustomAgentModal] =
    useState(false);
  const [pendingMoveProjectId, setPendingMoveProjectId] = useState<
    number | null
  >(null);
  const [showMoveOptions, setShowMoveOptions] = useState(false);
  const [showExportOptions, setShowExportOptions] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [popoverItems, setPopoverItems] = useState<React.ReactNode[]>([]);
  const [modePopoverOpen, setModePopoverOpen] = useState(false);
  const {
    projects,
    fetchProjects,
    refreshCurrentProjectDetails,
    currentProjectId,
    setCurrentMessageFiles,
  } = useProjectsContext();
  const {
    currentChatSession,
    currentChatSessionId,
    refreshChatSessions,
    removeSession,
  } = useChatSessions();
  const router = useRouter();

  const customHeaderContent = settings.enterprise?.custom_header_content;
  const pageWithHeaderContent =
    appPosition.isChat() || appPosition.isNewSession() || appPosition.isAgent();

  const effectiveMode: AppMode =
    appPosition.isNewSession() && state.phase === "idle"
      ? state.appMode
      : "chat";

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

  // Incognito stays on until teardown returns, so the composer cannot submit
  // into a session being torn down. The server deletes that session's uploads
  // itself, including any that landed late.
  const handleExitIncognito = useCallback(async () => {
    const sessionId = currentChatSessionId;
    if (sessionId) {
      let tornDown = false;
      try {
        tornDown = await endIncognitoSession(sessionId);
      } catch (error) {
        console.error("Failed to end incognito session:", error);
      }
      // Stay put on failure. Dropping the id is what would strand the context
      // and uploads, and the user can retry from here.
      if (!tornDown) {
        showErrorNotification("Could not end the incognito chat. Try again.");
        return;
      }
      removeSession(sessionId);
    }
    setIncognitoEnabled(false);
    setCurrentMessageFiles([]);
    if (sessionId) {
      router.replace("/app");
    }
  }, [
    currentChatSessionId,
    setIncognitoEnabled,
    setCurrentMessageFiles,
    removeSession,
    router,
  ]);

  const handleExport = useCallback(
    async (format: ChatExportFormat) => {
      if (!currentChatSession) return;
      try {
        await exportChatSession(
          currentChatSession.id,
          currentChatSession.name || UNNAMED_CHAT,
          format
        );
      } catch (error) {
        console.error("Failed to export chat:", error);
        showErrorNotification(t("exportFailed.message"));
      }
    },
    [currentChatSession]
  );

  useEffect(() => {
    let items: ReactNode[];
    if (showMoveOptions) {
      items = [
        <PopoverSearchInput
          key="search"
          setShowMoveOptions={setShowMoveOptions}
          onSearch={setSearchTerm}
        />,
        ...filteredProjects.map((project) => (
          <LineItemButton
            key={project.id}
            sizePreset="main-ui"
            rounding={2}
            icon={SvgFolderIn}
            title={project.name}
            onClick={noProp(() => handleMoveClick(project.id))}
          />
        )),
      ];
    } else if (showExportOptions) {
      items = [
        <LineItemButton
          key="export-back"
          sizePreset="main-ui"
          rounding={2}
          icon={SvgChevronLeft}
          title={t("exportAs.label")}
          onClick={noProp(() => setShowExportOptions(false))}
        />,
        <Popover.Close asChild key="export-plaintext">
          <LineItemButton
            sizePreset="main-ui"
            rounding={2}
            icon={SvgFileText}
            title={t("exportPlaintext.label")}
            onClick={noProp(() => handleExport("text"))}
          />
        </Popover.Close>,
        <Popover.Close asChild key="export-markdown">
          <LineItemButton
            sizePreset="main-ui"
            rounding={2}
            icon={SvgHash}
            title={t("exportMarkdown.label")}
            onClick={noProp(() => handleExport("markdown"))}
          />
        </Popover.Close>,
      ];
    } else {
      items = [
        <LineItemButton
          key="move"
          sizePreset="main-ui"
          rounding={2}
          icon={SvgFolderIn}
          title={t("moveToProject.label")}
          onClick={noProp(() => setShowMoveOptions(true))}
        />,
        <LineItemButton
          key="export"
          sizePreset="main-ui"
          rounding={2}
          icon={SvgDownload}
          title={t("exportAs.label")}
          onClick={noProp(() => setShowExportOptions(true))}
        />,
        null,
        <LineItemButton
          key="delete"
          sizePreset="main-ui"
          rounding={2}
          color="danger"
          icon={SvgTrash}
          title={t("delete.label")}
          onClick={noProp(() => setDeleteConfirmationModalOpen(true))}
        />,
      ];
    }

    setPopoverItems(items);
  }, [
    showMoveOptions,
    showExportOptions,
    filteredProjects,
    currentChatSession,
    setDeleteConfirmationModalOpen,
    handleMoveClick,
    handleExport,
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
          title={t("deleteModal.title")}
          icon={SvgTrash}
          onClose={() => setDeleteModalOpen(false)}
          submit={
            <Button variant="danger" onClick={handleDeleteChat}>
              {t("deleteModal.submitButton.label")}
            </Button>
          }
        >
          {t("deleteModal.description")}
        </ConfirmationModalLayout>
      )}

      {(appPosition.isChat() ||
        appPosition.isNewSession() ||
        appPosition.isAgent() ||
        appPosition.isProject() ||
        isMobile) &&
        !appPosition.isSharedChat() && (
          <RootLayout.Header>
            <div className="w-full h-full flex flex-row flex-wrap justify-center items-start p-2 sm:px-4">
              {/*
          Left:
          - (mobile) sidebar toggle
          - app-mode (for Unified S+C [EE gated])
        */}
              <div className="flex-1 flex flex-row items-center gap-2">
                {isMobile && (
                  <Button
                    prominence="internal"
                    icon={SvgSidebar}
                    aria-label={t("openSidebar.ariaLabel")}
                    onClick={() => setFolded(false)}
                  />
                )}
                {incognitoEnabled &&
                  (appPosition.isChat() || appPosition.isNewSession()) && (
                    <OpenButton
                      disabled
                      icon={SvgEyeOff}
                      aria-label={t("incognitoPill.ariaLabel")}
                      data-testid="incognito-chat-pill"
                    >
                      {t("incognitoPill.label")}
                    </OpenButton>
                  )}
                {businessTier &&
                  isSearchModeAvailable &&
                  !incognitoEnabled &&
                  appPosition.isNewSession() &&
                  state.phase === "idle" && (
                    <Popover
                      open={modePopoverOpen}
                      onOpenChange={setModePopoverOpen}
                    >
                      <Popover.Trigger asChild>
                        <OpenButton
                          aria-label={t("modeButton.ariaLabel")}
                          icon={
                            effectiveMode === "search"
                              ? SvgSearchMenu
                              : SvgBubbleText
                          }
                        >
                          {effectiveMode === "search"
                            ? t("mode.search.label")
                            : t("mode.chat.label")}
                        </OpenButton>
                      </Popover.Trigger>
                      <Popover.Content align="start" width="lg">
                        <Popover.Menu>
                          <LineItemButton
                            sizePreset="main-ui"
                            rounding={2}
                            icon={SvgSearchMenu}
                            state={
                              effectiveMode === "search" ? "selected" : "empty"
                            }
                            title={t("mode.search.label")}
                            description={t("mode.search.description")}
                            onClick={noProp(() => {
                              setAppMode("search");
                              setModePopoverOpen(false);
                            })}
                          />
                          <LineItemButton
                            sizePreset="main-ui"
                            rounding={2}
                            icon={SvgBubbleText}
                            state={
                              effectiveMode === "chat" ? "selected" : "empty"
                            }
                            title={t("mode.chat.label")}
                            description={t("mode.chat.description")}
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
                {pageWithHeaderContent && customHeaderContent && (
                  <span className="text-center w-full">
                    <Text color="text-03">{customHeaderContent}</Text>
                  </span>
                )}
              </div>

              {/*
          Right:
          - share button
          - more-options buttons
        */}
              <div className="flex flex-1 justify-end items-center">
                {(appPosition.isChat() || appPosition.isNewSession()) && (
                  <FrostedDiv className="flex shrink flex-row items-center">
                    {incognitoAvailable && !incognitoEnabled && (
                      <Button
                        icon={SvgEyeOff}
                        prominence="tertiary"
                        onClick={toggleIncognito}
                        disabled={incognitoLocked}
                        aria-label={t("incognitoStart.ariaLabel")}
                        tooltip={
                          incognitoLocked
                            ? t("incognitoStart.lockedTooltip")
                            : t("incognitoStart.tooltip")
                        }
                      />
                    )}
                    {/* On mobile widths the reading-width cap never applies
                        (chat is always full width), so the toggle is hidden. */}
                    {!isMobile && (
                      <Button
                        icon={fullWidthChat ? SvgFitWidth : SvgFullWidth}
                        prominence="tertiary"
                        onClick={toggleFullWidthChat}
                        tooltip={
                          fullWidthChat
                            ? t("fullWidth.fitTooltip")
                            : t("fullWidth.fullTooltip")
                        }
                        aria-label={t("fullWidth.ariaLabel")}
                        aria-pressed={fullWidthChat}
                      />
                    )}
                    {incognitoEnabled && (
                      <Button
                        icon={SvgX}
                        prominence="tertiary"
                        onClick={() => void handleExitIncognito()}
                        aria-label={t("incognitoExit.ariaLabel")}
                        tooltip={t("incognitoExit.tooltip")}
                      />
                    )}
                  </FrostedDiv>
                )}
                {appPosition.isChat() &&
                  currentChatSession &&
                  !incognitoEnabled && (
                    <FrostedDiv className="flex shrink flex-row items-center">
                      <Button
                        icon={SvgShare}
                        prominence="tertiary"
                        interaction={showShareModal ? "hover" : "rest"}
                        responsiveHideText
                        onClick={() => setShowShareModal(true)}
                        aria-label="share-chat-button"
                      >
                        {t("share.label")}
                      </Button>
                      <SimplePopover
                        trigger={
                          <Button
                            icon={SvgMoreHorizontal}
                            prominence="tertiary"
                            interaction={popoverOpen ? "hover" : "rest"}
                          />
                        }
                        onOpenChange={(state) => {
                          setPopoverOpen(state);
                          if (!state) {
                            setShowMoveOptions(false);
                            setShowExportOptions(false);
                            setSearchTerm("");
                          }
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
          </RootLayout.Header>
        )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Footer
// ---------------------------------------------------------------------------

function Footer() {
  const appPosition = useAppPosition();
  const customFooterContent = useCustomFooterContent();

  return (
    <RootLayout.Footer>
      <div
        className={cn(
          "relative w-full flex flex-row justify-center items-center gap-2 px-2 sm:px-4 mt-auto",
          // # Note (from @raunakab):
          //
          // The conditional rendering of vertical padding based on the current page is intentional.
          // The `AppInputBar` has `shadow-box-01` applied, which extends ~14px below it.
          // Because the content area in `AppChrome` uses `overflow-auto`, the shadow would be
          // clipped at the container boundary — causing a visible rendering artefact.
          //
          // To fix this, `AppPage.tsx` uses animated spacer divs around `AppInputBar` to
          // give the shadow breathing room. However, that extra space adds visible gap
          // between the input and the Footer. To compensate, we remove the Footer's top
          // padding when `appPosition.isChat()`.
          //
          // There is a corresponding note inside `AppInputBar.tsx` and `AppPage.tsx`
          // explaining this. Please refer to those notes as well.
          appPosition.isChat() ? "pb-2" : "py-2"
        )}
      >
        <Text font="secondary-action" color="text-03">
          {markdown(customFooterContent)}
        </Text>
      </div>
    </RootLayout.Footer>
  );
}

// ---------------------------------------------------------------------------
// AppChrome
// ---------------------------------------------------------------------------

interface AppChromeProps {
  children: React.ReactNode;
}

export default function AppChrome({ children }: AppChromeProps) {
  const [rightPanel, setRightPanel] = useState<ReactNode>(null);

  const appPosition = useAppPosition();
  useAppDocumentTitle();

  const { hasBackground, appBackgroundUrl } = useAppBackground();
  const { resolvedTheme } = useTheme();
  const { isSafari } = useBrowserInfo();
  const isLightMode = resolvedTheme === "light";
  const showBackground =
    hasBackground && (appPosition.isChat() || appPosition.isNewSession());

  const horizontalBlurMask = `linear-gradient(
    to right,
    transparent 0%,
    black max(0%, calc(50% - 25rem)),
    black min(100%, calc(50% + 25rem)),
    transparent 100%
  )`;

  const inputWasFocused = useRef(false);

  // Track whether the chat input was focused before a mousedown, so we can
  // restore focus on mouseup if no text was selected. This preserves
  // click-drag text selection while keeping the input focused on plain clicks.
  const handleMouseDown = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      const activeEl = document.activeElement;
      const isFocused =
        activeEl instanceof HTMLElement &&
        activeEl.id === "onyx-chat-input-textbox";
      const target = event.target;
      const isInteractive =
        target instanceof HTMLElement && !!target.closest(INTERACTIVE_SELECTOR);
      inputWasFocused.current = isFocused && !isInteractive;
    },
    []
  );

  const handleMouseUp = useCallback(() => {
    if (!inputWasFocused.current) return;
    inputWasFocused.current = false;
    const sel = window.getSelection();
    if (sel && !sel.isCollapsed) return;
    const textarea = document.getElementById("onyx-chat-input-textbox");
    if (textarea && document.activeElement !== textarea) {
      textarea.focus();
    }
  }, []);

  return (
    <RootLayoutRightPanelSlotContext.Provider value={setRightPanel}>
      <RootLayout.App
        data-main-container
        onMouseDown={handleMouseDown}
        onMouseUp={handleMouseUp}
      >
        <div className="flex flex-row flex-1 min-h-0">
          <div
            className={cn(
              "@container relative isolate flex-1 flex flex-col min-h-0",
              showBackground && "bg-cover bg-center bg-fixed"
            )}
            style={
              showBackground
                ? { backgroundImage: `url(${appBackgroundUrl})` }
                : undefined
            }
          >
            {/* Effect 1 — Vignette overlay for custom backgrounds (disabled in light mode).
              z-[-1] keeps overlays below the normal-flow header/content/footer. */}
            {showBackground && !isLightMode && (
              <div
                className="absolute z-[-1] inset-0 pointer-events-none"
                style={{
                  background: `
                  linear-gradient(to bottom, rgba(0, 0, 0, 0.4) 0%, transparent 4rem),
                  linear-gradient(to top, rgba(0, 0, 0, 0.4) 0%, transparent 4rem)
                `,
                }}
              />
            )}
            {/* Effect 2 — Semi-transparent overlay for readability when background is set */}
            {showBackground && appPosition.isChat() && (
              <>
                <div className="absolute z-[-1] inset-0 backdrop-blur-[1px] pointer-events-none" />
                {isSafari ? (
                  <div
                    className="absolute z-[-1] inset-0 bg-cover bg-center bg-fixed pointer-events-none"
                    style={{
                      backgroundImage: `url(${appBackgroundUrl})`,
                      filter: "blur(16px)",
                      maskImage: horizontalBlurMask,
                      WebkitMaskImage: horizontalBlurMask,
                    }}
                  />
                ) : (
                  <div
                    className="absolute z-[-1] inset-0 backdrop-blur-md transition-all duration-600 pointer-events-none"
                    style={{
                      maskImage: horizontalBlurMask,
                      WebkitMaskImage: horizontalBlurMask,
                    }}
                  />
                )}
              </>
            )}

            {/* Header */}
            <Header />
            <RootLayout.MainContent>{children}</RootLayout.MainContent>
            <Footer />
          </div>
          {rightPanel}
        </div>
      </RootLayout.App>
    </RootLayoutRightPanelSlotContext.Provider>
  );
}
