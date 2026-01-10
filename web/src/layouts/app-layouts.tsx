/**
 * App Page Layout Component
 *
 * Primary layout component for chat/application pages. Handles white-labeling,
 * chat session actions (share, move, delete), and responsive header/footer rendering.
 *
 * Features:
 * - Custom header/footer content from enterprise settings
 * - Share chat functionality
 * - Move chat to project (with confirmation for custom agents)
 * - Delete chat with confirmation
 * - Mobile-responsive sidebar toggle
 * - Conditional rendering based on chat state
 *
 * @example
 * ```tsx
 * import AppLayouts from "@/layouts/app-layouts";
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
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import { useSettingsContext } from "@/components/settings/SettingsProvider";

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
        <Text as="span" text03 secondaryAction>
          {children}
        </Text>
      </a>
    );
  },
} satisfies Partial<Components>;

function AppHeader() {
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

      {(isMobile || customHeaderContent || currentChatSessionId) && (
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
          <div className="flex-1 flex flex-col items-center overflow-hidden">
            <Text
              as="p"
              text03
              mainUiBody
              className="text-center break-words w-full"
            >
              {customHeaderContent}
            </Text>
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
      )}
    </>
  );
}

function AppFooter() {
  const settings = useSettingsContext();

  const customFooterContent =
    settings?.enterpriseSettings?.custom_lower_disclaimer_content ||
    `[Onyx ${
      settings?.webVersion || "dev"
    }](https://www.onyx.app/) - Open Source AI Platform`;

  return (
    <footer className="w-full flex flex-row justify-center items-center gap-2 pb-2">
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
 * Wraps chat pages with white-labeling chrome (custom header/footer) and
 * provides chat session management actions.
 *
 * Layout Structure:
 * ```
 * ┌──────────────────────────────────┐
 * │ Header (custom or with actions)  │
 * ├──────────────────────────────────┤
 * │                                  │
 * │ Content Area (children)          │
 * │                                  │
 * ├──────────────────────────────────┤
 * │ Footer (custom disclaimer)       │
 * └──────────────────────────────────┘
 * ```
 *
 * Features:
 * - Renders custom header content from enterprise settings
 * - Shows sidebar toggle on mobile
 * - "Share Chat" button for current chat session
 * - Kebab menu with "Move to Project" and "Delete" options
 * - Move confirmation modal for custom agent chats
 * - Delete confirmation modal
 * - Renders custom footer disclaimer from enterprise settings
 *
 * State Management:
 * - Manages multiple modals (share, move, delete)
 * - Handles project search/filtering in move modal
 * - Integrates with projects context for chat operations
 * - Uses settings context for white-labeling
 * - Uses chat sessions hook for current session
 *
 * @example
 * ```tsx
 * // Basic usage in a chat page
 * <AppLayouts.Root>
 *   <ChatInterface />
 * </AppLayouts.Root>
 *
 * // The header will show:
 * // - Mobile: Sidebar toggle button
 * // - Desktop: Share button + kebab menu (when chat session exists)
 * // - Custom header text (if configured)
 *
 * // The footer will show custom disclaimer (if configured)
 * ```
 */
export interface AppRootProps {
  children?: React.ReactNode;
}

function AppRoot({ children }: AppRootProps) {
  return (
    /* NOTE: Some elements, markdown tables in particular, refer to this `@container` in order to
      breakout of their immediate containers using cqw units.
    */
    <div className="@container flex flex-col h-full w-full">
      <AppHeader />
      <div className="flex-1 overflow-auto h-full w-full">{children}</div>
      <AppFooter />
    </div>
  );
}

export { AppRoot as Root };
