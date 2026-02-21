/**
 * App Page Layout Components
 *
 * Provides the root layout, header, and footer for app pages.
 * AppRoot renders AppHeader and Footer by default (both can be disabled via props).
 *
 * @example
 * ```tsx
 * import * as AppLayouts from "@/layouts/app-layouts";
 *
 * export default function ChatPage() {
 *   return (
 *     <AppLayouts.Root>
 *       <ChatInterface />
 *     </AppLayouts.Root>
 *   );
 * }
 * ```
 */

"use client";

import { cn, ensureHrefProtocol, noProp } from "@/lib/utils";
import type { Components } from "react-markdown";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import { useCallback, useMemo, useState, useEffect } from "react";
import { useAppBackground } from "@/providers/AppBackgroundProvider";
import { useTheme } from "next-themes";
import ShareChatSessionModal from "@/sections/modals/ShareChatSessionModal";
import IconButton from "@/refresh-components/buttons/IconButton";
import LineItem from "@/refresh-components/buttons/LineItem";
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
import MoveCustomAgentChatModal from "@/components/modals/MoveCustomAgentChatModal";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import FrostedDiv from "@/refresh-components/FrostedDiv";
import Popover, { PopoverMenu } from "@/refresh-components/Popover";
import { PopoverSearchInput } from "@/sections/sidebar/ChatButton";
import SimplePopover from "@/refresh-components/SimplePopover";
import { Interactive } from "@opal/core";
import { OpenButton } from "@opal/components";
import { LineItemLayout } from "@/layouts/general-layouts";
import { useAppSidebarContext } from "@/providers/AppSidebarProvider";
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
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { AppMode, useAppMode } from "@/providers/AppModeProvider";
import useAppFocus from "@/hooks/useAppFocus";
import { useQueryController } from "@/providers/QueryControllerProvider";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";

/**
 * App Header Component
 *
 * Renders the header for chat sessions with share, move, and delete actions.
 * Designed to be rendered inside ChatScrollContainer with sticky positioning.
 *
 * Features:
 * - Share chat functionality
 * - Move chat to project (with confirmation for custom agents)
 * - Delete chat with confirmation
 * - Mobile-responsive sidebar toggle
 * - Custom header content from enterprise settings
 * - App-Mode toggle (EE gated)
 */
function Header() {
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();
  const { appMode, setAppMode } = useAppMode();
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
  const [modePopoverOpen, setModePopoverOpen] = useState(false);
  const {
    projects,
    fetchProjects,
    refreshCurrentProjectDetails,
    currentProjectId,
  } = useProjectsContext();
  const { currentChatSession, refreshChatSessions } = useChatSessions();
  const router = useRouter();
  const appFocus = useAppFocus();
  const { classification } = useQueryController();

  const customHeaderContent =
    settings?.enterpriseSettings?.custom_header_content;
  // Some pages don't want the custom header content, namely every page except Chat, Search, and
  // NewSession. The header provides features such as the open sidebar button on mobile which pages
  // without this content still use.
  const pageWithHeaderContent = appFocus.isChat() || appFocus.isNewSession();

  const effectiveMode: AppMode = appFocus.isNewSession() ? appMode : "chat";

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
      await Promise.all([refreshChatSessions(), fetchProjects()]);
      router.replace("/app");
      setDeleteModalOpen(false);
    } catch (error) {
      console.error("Failed to delete chat:", error);
      showErrorNotification("Failed to delete chat. Please try again.");
    }
  }, [currentChatSession, refreshChatSessions, fetchProjects, router]);

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
            <LineItem
              key={project.id}
              icon={SvgFolderIn}
              onClick={noProp(() => handleMoveClick(project.id))}
            >
              {project.name}
            </LineItem>
          )),
        ]
      : [
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
            <Button danger onClick={handleDeleteChat}>
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
            <IconButton
              icon={SvgSidebar}
              onClick={() => setFolded(false)}
              internal
            />
          )}
          {isPaidEnterpriseFeaturesEnabled &&
            settings.isSearchModeAvailable &&
            appFocus.isNewSession() &&
            !classification && (
              <Popover open={modePopoverOpen} onOpenChange={setModePopoverOpen}>
                <Popover.Trigger asChild>
                  <OpenButton
                    icon={
                      effectiveMode === "search" ? SvgSearchMenu : SvgBubbleText
                    }
                  >
                    {effectiveMode === "search" ? "Search" : "Chat"}
                  </OpenButton>
                </Popover.Trigger>
                <Popover.Content align="start" width="lg">
                  <Popover.Menu>
                    <LineItem
                      icon={SvgSearchMenu}
                      selected={effectiveMode === "search"}
                      description="Quick search for documents"
                      onClick={noProp(() => {
                        setAppMode("search");
                        setModePopoverOpen(false);
                      })}
                    >
                      Search
                    </LineItem>
                    <LineItem
                      icon={SvgBubbleText}
                      selected={effectiveMode === "chat"}
                      description="Conversation and research"
                      onClick={noProp(() => {
                        setAppMode("chat");
                        setModePopoverOpen(false);
                      })}
                    >
                      Chat
                    </LineItem>
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
              ? "order-last basis-full py-2 sm:py-0 sm:order-none sm:basis-auto sm:flex-1"
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
                leftIcon={SvgShare}
                transient={showShareModal}
                tertiary
                onClick={() => setShowShareModal(true)}
                aria-label="share-chat-button"
              >
                {isMobile ? "" : "Share Chat"}
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
            </FrostedDiv>
          )}
        </div>
      </div>
    </>
  );
}

const footerMarkdownComponents = {
  p: ({ children }) => (
    //dont remove the !my-0 class, it's important for the markdown to render without any alignment issues
    <Text as="p" text03 secondaryAction className="!my-0 text-center">
      {children}
    </Text>
  ),
  a: ({ node, href, className, children, ...rest }) => {
    const fullHref = ensureHrefProtocol(href);
    return (
      <a
        href={fullHref}
        target="_blank"
        rel="noopener noreferrer"
        {...rest}
        className={cn(className, "underline underline-offset-2")}
      >
        <Text text03 secondaryAction>
          {children}
        </Text>
      </a>
    );
  },
} satisfies Partial<Components>;

function Footer() {
  const settings = useSettingsContext();
  const appFocus = useAppFocus();

  const customFooterContent =
    settings?.enterpriseSettings?.custom_lower_disclaimer_content ||
    `[Onyx ${
      settings?.webVersion || "dev"
    }](https://www.onyx.app/) - Open Source AI Platform`;

  return (
    <footer
      className={cn(
        "relative w-full flex flex-row justify-center items-center gap-2 px-2 mt-auto",
        // # Note (from @raunakab):
        //
        // The conditional rendering of vertical padding based on the current page is intentional.
        // The `AppInputBar` has `shadow-01` applied, which extends ~14px below it.
        // Because the content area in `Root` uses `overflow-auto`, the shadow would be
        // clipped at the container boundary — causing a visible rendering artefact.
        //
        // To fix this, `AppPage.tsx` uses animated spacer divs around `AppInputBar` to
        // give the shadow breathing room. However, that extra space adds visible gap
        // between the input and the Footer. To compensate, we remove the Footer's top
        // padding when `appFocus.isChat()`.
        //
        // There is a corresponding note inside `AppInputBar.tsx` and `AppPage.tsx`
        // explaining this. Please refer to those notes as well.
        appFocus.isChat() ? "pb-2" : "py-2"
      )}
    >
      <MinimalMarkdown
        content={customFooterContent}
        className={cn("max-w-full text-center")}
        components={footerMarkdownComponents}
      />
    </footer>
  );
}

/**
 * App Root Component
 *
 * Wraps app pages with header (AppHeader) and footer chrome.
 *
 * Layout Structure:
 * ```
 * ┌──────────────────────────────────┐
 * │ AppHeader                        │
 * ├──────────────────────────────────┤
 * │                                  │
 * │ Content Area (children)          │
 * │                                  │
 * ├──────────────────────────────────┤
 * │ Footer (custom disclaimer)       │
 * └──────────────────────────────────┘
 * ```
 *
 * @example
 * ```tsx
 * <AppLayouts.Root>
 *   <ChatInterface />
 * </AppLayouts.Root>
 * ```
 */
export interface AppRootProps {
  /** Opt-in to render the user's custom background image */
  enableBackground?: boolean;
  children?: React.ReactNode;
}

function Root({ children, enableBackground }: AppRootProps) {
  const { hasBackground, appBackgroundUrl } = useAppBackground();
  const { resolvedTheme } = useTheme();
  const appFocus = useAppFocus();
  const isLightMode = resolvedTheme === "light";
  const showBackground = hasBackground && enableBackground;

  return (
    /* NOTE: Some elements, markdown tables in particular, refer to this `@container` in order to
      breakout of their immediate containers using cqw units.
      The `data-main-container` attribute is used by portaled elements (e.g. CommandMenu) to
      render inside this container so they can be centered relative to the main content area
      rather than the full viewport (which would include the sidebar).
    */
    <div
      data-main-container
      className={cn(
        "@container flex flex-col h-full w-full relative overflow-hidden",
        showBackground && "bg-cover bg-center bg-fixed"
      )}
      style={
        showBackground
          ? { backgroundImage: `url(${appBackgroundUrl})` }
          : undefined
      }
    >
      {/* Effect 1 */}
      {/* Vignette overlay for custom backgrounds (disabled in light mode) */}
      {showBackground && !isLightMode && (
        <div
          className="absolute z-0 inset-0 pointer-events-none"
          style={{
            background: `
              linear-gradient(to bottom, rgba(0, 0, 0, 0.4) 0%, transparent 4rem),
              linear-gradient(to top, rgba(0, 0, 0, 0.4) 0%, transparent 4rem)
            `,
          }}
        />
      )}

      {/* Effect 2 */}
      {/* Semi-transparent overlay for readability when background is set */}
      {showBackground && appFocus.isChat() && (
        <>
          <div className="absolute inset-0 backdrop-blur-[1px] pointer-events-none" />
          <div
            className="absolute z-0 inset-0 backdrop-blur-md transition-all duration-600 pointer-events-none"
            style={{
              maskImage: `linear-gradient(
                to right,
                transparent 0%,
                black max(0%, calc(50% - 25rem)),
                black min(100%, calc(50% + 25rem)),
                transparent 100%
              )`,
              WebkitMaskImage: `linear-gradient(
                to right,
                transparent 0%,
                black max(0%, calc(50% - 25rem)),
                black min(100%, calc(50% + 25rem)),
                transparent 100%
              )`,
            }}
          />
        </>
      )}

      <div className="z-app-layout">
        {!appFocus.isSharedChat() && <Header />}
      </div>
      <div className="z-app-layout flex-1 overflow-auto h-full w-full">
        {children}
      </div>
      <div className="z-app-layout">
        <Footer />
      </div>
    </div>
  );
}

export { Root };
