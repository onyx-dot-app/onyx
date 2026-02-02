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
import ShareChatSessionModal from "@/app/app/components/modal/ShareChatSessionModal";
import IconButton from "@/refresh-components/buttons/IconButton";
import LineItem from "@/refresh-components/buttons/LineItem";
import { useProjectsContext } from "@/providers/ProjectsContext";
import useChatSessions from "@/hooks/useChatSessions";
import { usePopup } from "@/components/admin/connectors/Popup";
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
import { PopoverMenu } from "@/refresh-components/Popover";
import { PopoverSearchInput } from "@/sections/sidebar/ChatButton";
import SimplePopover from "@/refresh-components/SimplePopover";
import { useAppSidebarContext } from "@/providers/AppSidebarProvider";
import useScreenSize from "@/hooks/useScreenSize";
import {
  SvgFolderIn,
  SvgMoreHorizontal,
  SvgShare,
  SvgSidebar,
  SvgTrash,
} from "@opal/icons";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import { useSettingsContext } from "@/providers/SettingsProvider";
import useAppFocus from "@/hooks/useAppFocus";

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
  const { currentChatSession, refreshChatSessions } = useChatSessions();
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
      router.replace("/app");
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

      <div className="w-full flex flex-row justify-center items-center py-3 px-4 h-16">
        {/*
          Left:
          - (mobile) sidebar toggle
          - app-mode (for Unified S+C [EE gated])
        */}
        <div className="flex-1">
          <IconButton
            icon={SvgSidebar}
            onClick={() => setFolded(false)}
            className={cn(!isMobile && "invisible")}
            internal
          />
        </div>

        {/*
          Center:
          - custom-header-content
        */}
        <div className="flex-1 flex flex-col items-center overflow-hidden">
          <Text text03 className="text-center w-full">
            {customHeaderContent}
          </Text>
        </div>

        {/*
          Right:
          - share button
          - more-options buttons
        */}
        <div className="flex flex-1 justify-end">
          {currentChatSession && (
            <FrostedDiv className="flex shrink flex-row items-center">
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
        // The `ChatInputBar` has `shadow-01` applied, which extends ~14px below it.
        // Because the content area in `Root` uses `overflow-auto`, the shadow would be
        // clipped at the container boundary — causing a visible rendering artefact.
        //
        // To fix this, `ChatInputBar` has `mb-[14px]` to give the shadow breathing room.
        // However, that extra margin adds visible space between the input and the Footer.
        // To compensate, we remove the Footer's top padding when `appFocus.isChat()`.
        //
        // There is a corresponding note inside `ChatInputBar.tsx` explaining the `mb-[14px]`.
        // Please refer to that note as well.
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
    */
    <div
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
        <Header />
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
