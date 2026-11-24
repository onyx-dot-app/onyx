"use client";

import { useTranslations } from "next-intl";
import { useCallback, useMemo, useRef, useState, type ReactNode } from "react";
import { RootLayout, RootLayoutRightPanelSlotContext } from "@opal/layouts";
import { cn, markdown } from "@opal/utils";
import { INTERACTIVE_SELECTOR } from "@/lib/utils";
import { useAppBackground } from "@/providers/AppBackgroundProvider";
import { useTheme } from "next-themes";
import useBrowserInfo from "@/hooks/useBrowserInfo";
import ShareChatSessionModal from "@/sections/modals/ShareChatSessionModal";
import { useProjectsContext } from "@/lib/projects/providers";
import useChatSessions from "@/hooks/useChatSessions";
import { showErrorNotification } from "@/lib/sidebar/utils";
import { endIncognitoSession } from "@/app/app/services/lib";
import { useChatExportMenu } from "@/lib/chat/hooks";
import ChatActivity from "@/sections/chat/ChatActivity";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import FrostedDiv from "@/refresh-components/FrostedDiv";
import {
  Button,
  Dropdown,
  SelectButton,
  Text,
  useCreateModal,
} from "@opal/components";
import { useSidebarState } from "@opal/layouts";
import useScreenSize from "@/hooks/useScreenSize";
import {
  SvgBubbleText,
  SvgEyeOff,
  SvgSearchMenu,
  SvgShare,
  SvgSidebar,
  SvgX,
} from "@opal/icons";
import { useIsSearchModeAvailable, useSettings } from "@/lib/settings/hooks";
import type { AppMode } from "@/providers/QueryControllerProvider";
import { useAppDocumentTitle, useCustomFooterContent } from "@/lib/app/hooks";
import { useAppPosition } from "@/lib/navigation/hooks";
import { PendingRoute, useNavigation } from "@opal/navigation";
import { AppChromeLoader } from "@/layouts/chromes/AppChromeLoader";
import { useQueryController } from "@/providers/QueryControllerProvider";
import { useTierAtLeast } from "@/lib/tiers/hooks";
import { Tier } from "@/lib/tiers/types";
import { useIncognito } from "@/providers/IncognitoProvider";
import { AppWorkspaceElementsContext } from "@/layouts/chromes/AppWorkspace";
import { PANEL_TOGGLE_ROOM } from "@/lib/outputPanel/layout";

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
  // The store's chat, whose requests, agents and files the activity card shows
  const storeSessionId = useChatSessionStore((state) => state.currentSessionId);
  const {
    incognitoAvailable,
    incognitoEnabled,
    incognitoLocked,
    toggleIncognito,
    setIncognitoEnabled,
  } = useIncognito();
  const shareModal = useCreateModal();
  const [modePopoverOpen, setModePopoverOpen] = useState(false);
  const { setCurrentMessageFiles } = useProjectsContext();
  const { currentChatSession, currentChatSessionId, removeSession } =
    useChatSessions();
  const { exportItems } = useChatExportMenu(currentChatSession);
  const navigation = useNavigation();

  const showIncognitoStart =
    appPosition.isNewSession() &&
    incognitoAvailable &&
    !incognitoEnabled &&
    !incognitoLocked;

  const customHeaderContent = settings.enterprise?.custom_header_content;
  const showHeaderContent =
    !!customHeaderContent &&
    (appPosition.isChat() ||
      appPosition.isNewSession() ||
      appPosition.isAgent());

  const effectiveMode: AppMode =
    appPosition.isNewSession() && state.phase === "idle"
      ? state.appMode
      : "chat";

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
      navigation.go("/app", { replace: true });
    }
  }, [
    currentChatSessionId,
    setIncognitoEnabled,
    setCurrentMessageFiles,
    removeSession,
    navigation,
  ]);

  return (
    <>
      <shareModal.Provider>
        {currentChatSession && (
          <ShareChatSessionModal
            chatSession={currentChatSession}
            onClose={() => shareModal.toggle(false)}
          />
        )}
      </shareModal.Provider>

      {(appPosition.isChat() ||
        appPosition.isNewSession() ||
        appPosition.isAgent() ||
        appPosition.isProject() ||
        isMobile) &&
        !appPosition.isSharedChat() && (
          <RootLayout.Header>
            {/* A chat's header keeps out of the room for the chat's right
                panel toggle, which the closed panel places over the header's
                end */}
            <div
              className="w-full h-full flex flex-row flex-wrap justify-center items-start p-2 sm:px-4"
              style={
                appPosition.isChat()
                  ? { paddingInlineEnd: `max(1rem, ${PANEL_TOGGLE_ROOM})` }
                  : undefined
              }
            >
              {/*
          Left:
          - (mobile) sidebar toggle
          - app-mode (for Unified S+C [EE gated])
        */}
              <div className="flex-1 min-w-0 self-stretch flex flex-row items-center gap-2">
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
                    <SelectButton
                      chevron
                      disabled
                      icon={SvgEyeOff}
                      aria-label={t("incognitoPill.ariaLabel")}
                      data-testid="incognito-chat-pill"
                    >
                      {t("incognitoPill.label")}
                    </SelectButton>
                  )}
                {businessTier &&
                  isSearchModeAvailable &&
                  !incognitoEnabled &&
                  appPosition.isNewSession() &&
                  state.phase === "idle" && (
                    <Dropdown
                      open={modePopoverOpen}
                      onOpenChange={setModePopoverOpen}
                    >
                      <Dropdown.Trigger asChild>
                        <SelectButton
                          chevron
                          aria-label={t("modeButton.ariaLabel")}
                          icon={
                            effectiveMode === "search"
                              ? SvgSearchMenu
                              : SvgBubbleText
                          }
                          interaction={modePopoverOpen ? "hover" : "rest"}
                        >
                          {effectiveMode === "search"
                            ? t("mode.search.label")
                            : t("mode.chat.label")}
                        </SelectButton>
                      </Dropdown.Trigger>
                      <Dropdown.Data
                        label={t("modeButton.ariaLabel")}
                        value={effectiveMode}
                        onSelect={(option) =>
                          setAppMode(
                            option.value === "search" ? "search" : "chat"
                          )
                        }
                        items={[
                          {
                            kind: "option",
                            value: "search",
                            icon: SvgSearchMenu,
                            title: t("mode.search.label"),
                            description: t("mode.search.description"),
                          },
                          {
                            kind: "option",
                            value: "chat",
                            icon: SvgBubbleText,
                            title: t("mode.chat.label"),
                            description: t("mode.chat.description"),
                          },
                        ]}
                      />
                    </Dropdown>
                  )}
                {appPosition.isChat() &&
                  currentChatSession?.id === appPosition.chat() &&
                  currentChatSession.name && (
                    <div className="min-w-0 px-2">
                      <Text
                        as="p"
                        font="main-ui-action"
                        color="text-04"
                        maxLines={1}
                        overflowTooltip
                      >
                        {currentChatSession.name}
                      </Text>
                    </div>
                  )}
              </div>

              {/*
          Center:
          - custom-header-content
          - Wraps to its own row below left/right on mobile when content is present
        */}
              {showHeaderContent && (
                <div className="flex flex-col items-center overflow-hidden order-last basis-full py-2 sm:py-0 sm:order-0 sm:basis-auto sm:flex-1">
                  <span className="text-center w-full">
                    <Text color="text-03">{customHeaderContent}</Text>
                  </span>
                </div>
              )}

              {/*
          Right:
          - share menu
        */}
              {/* Without center content, the left side takes the free room */}
              <div
                className={cn(
                  "flex justify-end items-center",
                  showHeaderContent ? "flex-1" : "shrink-0"
                )}
              >
                {(showIncognitoStart ||
                  (incognitoEnabled &&
                    (appPosition.isChat() || appPosition.isNewSession()))) && (
                  <FrostedDiv className="flex shrink flex-row items-center">
                    {showIncognitoStart && (
                      <Button
                        icon={SvgEyeOff}
                        prominence="tertiary"
                        onClick={toggleIncognito}
                        aria-label={t("incognitoStart.ariaLabel")}
                        tooltip={t("incognitoStart.tooltip")}
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
                {/* Once the store holds the chat on screen, also for a chat
                    outside the loaded Recents */}
                {appPosition.isChat() &&
                  storeSessionId !== null &&
                  storeSessionId === appPosition.chat() &&
                  !incognitoEnabled && (
                    <FrostedDiv className="flex shrink flex-row items-center">
                      <ChatActivity
                        key={storeSessionId}
                        sessionId={storeSessionId}
                      />
                    </FrostedDiv>
                  )}
                {/* Only for the chat on screen: during a navigation to another
                    chat, the URL's session is still the one these act on. */}
                {appPosition.isChat() &&
                  currentChatSession &&
                  currentChatSession.id === appPosition.chat() &&
                  !incognitoEnabled && (
                    <FrostedDiv className="flex shrink flex-row items-center">
                      <Dropdown width={60} align="end">
                        <Dropdown.Trigger asChild>
                          <Button
                            icon={SvgShare}
                            prominence="tertiary"
                            interaction={
                              shareModal.isOpen ? "hover" : undefined
                            }
                            aria-label={t("shareMenu.label")}
                            tooltip={t("shareMenu.label")}
                            data-testid="share-chat-button"
                          />
                        </Dropdown.Trigger>
                        <Dropdown.Data
                          label={t("shareMenu.label")}
                          items={[
                            {
                              kind: "action",
                              id: "share",
                              icon: SvgShare,
                              title: t("share.label"),
                              onSelect: () => shareModal.toggle(true),
                            },
                            ...exportItems,
                          ]}
                        />
                      </Dropdown>
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
          // Wrapping a long disclaimer needs both halves. `[&>*]:min-w-0`
          // lets the text shrink, since a flex item's min-width is `auto`
          // and otherwise holds it at its min-content width. `wordWrap` on
          // the Text below then lets an unbroken run split, which ordinary
          // wrapping will not do — it only breaks at whitespace, so a
          // pasted URL or one long token would still overflow.
          "relative w-full flex flex-row justify-center items-center gap-2 px-2 sm:px-4 mt-auto [&>*]:min-w-0",
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
        <Text
          font="secondary-action"
          color="text-03"
          as="p"
          wordWrap="wrap-anywhere"
          textPosition="text-center"
        >
          {markdown(customFooterContent)}
        </Text>
      </div>
    </RootLayout.Footer>
  );
}

// ---------------------------------------------------------------------------
// AppChrome
// ---------------------------------------------------------------------------

export interface AppChromeProps {
  children: React.ReactNode;
}

export default function AppChrome({ children }: AppChromeProps) {
  const [rightPanel, setRightPanel] = useState<ReactNode>(null);
  const workspaceRef = useRef<HTMLDivElement>(null);
  const pageRef = useRef<HTMLDivElement>(null);
  const [panelToggleSlot, setPanelToggleSlot] = useState<HTMLElement | null>(
    null
  );
  const [activitySlot, setActivitySlot] = useState<HTMLElement | null>(null);
  const workspaceElements = useMemo(
    () => ({
      workspace: workspaceRef,
      page: pageRef,
      panelToggleSlot,
      activitySlot,
    }),
    [panelToggleSlot, activitySlot]
  );

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
        <div
          ref={workspaceRef}
          className="@container/workspace relative flex flex-row flex-1 min-h-0"
        >
          <AppWorkspaceElementsContext.Provider value={workspaceElements}>
            <div ref={setPanelToggleSlot} />
            <div
              ref={pageRef}
              data-app-page
              className={cn(
                // Eases the room for the panel toggle with the panel's slide
                "@container relative isolate flex-1 flex flex-col min-h-0 [transition-property:--panel-toggle-reserve] ease-in-out duration-300 motion-reduce:transition-none",
                // A docked activity card covers the workspace's end below the
                // header: the chat's scrolled content, its input row
                // (`data-activity-room`) and the footer make room. The header
                // and the scroller keep their width, so the buttons and the
                // scrollbar stay at the end. The padding is only what the
                // card (21.5rem) needs beyond the centered chat column's
                // gutter (`--app-chat-column-width`, reading or wide; 45rem
                // outside the chat grid), so the column stays put when the
                // gutter fits it: gutter = (100% - column) / 2, padding =
                // 2 * 21.5rem + column - 100%.
                "@min-[64rem]/workspace:has-[[data-activity-docked]]:[&_[data-chat-scroll]>*]:pe-[max(0px,calc(43rem_+_var(--app-chat-column-width,45rem)_-_100%))]",
                "@min-[64rem]/workspace:has-[[data-activity-docked]]:[&_[data-activity-room]]:pe-[max(1rem,calc(43rem_+_var(--app-chat-column-width,45rem)_-_100%))]",
                "@min-[64rem]/workspace:has-[[data-activity-docked]]:[&>footer]:pe-[max(1rem,calc(43rem_+_var(--app-chat-column-width,45rem)_-_100%))]",
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
              <RootLayout.MainContent>
                <PendingRoute base="/app" loader={<AppChromeLoader />}>
                  {children}
                </PendingRoute>
              </RootLayout.MainContent>
              <Footer />
              <div ref={setActivitySlot} />
            </div>
            {/* The slot's panel measures the workspace and covers the page */}
            {rightPanel}
          </AppWorkspaceElementsContext.Provider>
        </div>
      </RootLayout.App>
    </RootLayoutRightPanelSlotContext.Provider>
  );
}
