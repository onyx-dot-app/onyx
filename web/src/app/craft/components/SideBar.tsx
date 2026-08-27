"use client";

import { memo, useCallback, useState, useEffect, useRef } from "react";
import type { Route } from "next";
import { useRouter, usePathname } from "next/navigation";
import { useBuildContext } from "@/app/craft/contexts/BuildContext";
import {
  useSession,
  useSessionHistory,
  useBuildSessionStore,
  SessionHistoryItem,
} from "@/app/craft/hooks/useBuildSessionStore";
import { CRAFT_SEARCH_PARAM_NAMES } from "@/app/craft/services/searchParams";
import {
  Button,
  LineItemButton,
  Popover,
  PopoverMenu,
  SidebarTab,
  Text,
} from "@opal/components";
import {
  ConfirmationModalLayout,
  SidebarLayouts,
  SidebarStateProvider,
  toast,
  useSidebarState,
} from "@opal/layouts";
import RefreshText from "@/refresh-components/texts/Text";
import { renderSidebarLogo } from "@/lib/sidebar/utils";
import { useShowLogoWhenFolded } from "@/lib/sidebar/hooks";
import AccountPopover from "@/sections/sidebar/AccountPopover";
import ButtonRenaming from "@/refresh-components/buttons/ButtonRenaming";
import { Hoverable } from "@opal/core";
import { noProp } from "@/lib/utils";
import {
  SvgEditBig,
  SvgArrowLeft,
  SvgBlocks,
  SvgClock,
  SvgMoreHorizontal,
  SvgEdit,
  SvgTrash,
  SvgPlug,
  SvgSimpleLoader,
} from "@opal/icons";
import TypewriterText from "@/app/craft/components/TypewriterText";
import OpencodeDebugLogsButton from "@/app/craft/components/OpencodeDebugLogs";
import {
  CRAFT_PATH,
  CRAFT_SKILLS_PATH,
  CRAFT_APPS_PATH,
  CRAFT_TASKS_PATH,
} from "@/app/craft/v1/constants";
import { useUnsavedChangesNavigation } from "@/providers/UnsavedChangesNavigationProvider";

// ============================================================================
// Build Session Button
// ============================================================================

interface CraftSessionDeleteModalProps {
  sessionTitle: string;
  isDeleting?: boolean;
  onClose: () => void;
  onConfirm: (event: React.MouseEvent<HTMLButtonElement>) => void;
}

export function CraftSessionDeleteModal({
  sessionTitle,
  isDeleting = false,
  onClose,
  onConfirm,
}: CraftSessionDeleteModalProps) {
  return (
    <ConfirmationModalLayout
      title={`Delete "${sessionTitle}"?`}
      icon={SvgTrash}
      onClose={isDeleting ? undefined : onClose}
      submit={
        <Button
          disabled={isDeleting}
          variant="danger"
          prominence="primary"
          onClick={onConfirm}
          icon={isDeleting ? SvgSimpleLoader : undefined}
        >
          {isDeleting ? "Deleting..." : "Delete"}
        </Button>
      }
    >
      This permanently removes the Craft session and all of its data. This
      action cannot be undone.
    </ConfirmationModalLayout>
  );
}

interface BuildSessionButtonProps {
  historyItem: SessionHistoryItem;
  isActive: boolean;
  onLoad: () => void;
  onRename: (newName: string) => Promise<void>;
  onDelete: () => Promise<void>;
  onDeleteActiveSession?: () => void;
}

function BuildSessionButton({
  historyItem,
  isActive,
  onLoad,
  onRename,
  onDelete,
  onDeleteActiveSession,
}: BuildSessionButtonProps) {
  const [renaming, setRenaming] = useState(false);
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  // Track title changes for typewriter animation (only for auto-naming, not manual rename)
  const prevTitleRef = useRef(historyItem.title);
  const [shouldAnimate, setShouldAnimate] = useState(false);

  // Detect when title changes from "Fresh Craft" to a real name (auto-naming)
  useEffect(() => {
    const prevTitle = prevTitleRef.current;
    if (
      prevTitle !== historyItem.title &&
      prevTitle === "Fresh Craft" &&
      !renaming
    ) {
      setShouldAnimate(true);
    }
    prevTitleRef.current = historyItem.title;
  }, [historyItem.title, renaming]);

  const closeModal = useCallback(() => {
    setIsDeleteModalOpen(false);
    setPopoverOpen(false);
  }, []);

  const handleConfirmDelete = useCallback(
    async (e: React.MouseEvent<HTMLButtonElement>) => {
      e.stopPropagation();
      setIsDeleting(true);

      try {
        await onDelete();
        setIsDeleting(false);
        toast.success(`Deleted "${historyItem.title}".`);
        closeModal();
        if (isActive && onDeleteActiveSession) {
          onDeleteActiveSession();
        }
      } catch (err) {
        setIsDeleting(false);
        toast.error(
          err instanceof Error ? err.message : "Failed to delete session"
        );
      }
    },
    [onDelete, historyItem.title, closeModal, isActive, onDeleteActiveSession]
  );

  const rightMenu = (
    <>
      <Popover.Trigger asChild onClick={noProp()}>
        <div>
          {/* While renaming the row is an input, so the menu stays away unless
              its own popover is already open. */}
          {(!renaming || popoverOpen) && (
            <Hoverable.Item group="CraftSessionTab">
              <Button
                icon={SvgMoreHorizontal}
                prominence="internal"
                size="sm"
                interaction={popoverOpen ? "hover" : "rest"}
              />
            </Hoverable.Item>
          )}
        </div>
      </Popover.Trigger>
      <Popover.Content side="right" align="start">
        <PopoverMenu>
          {[
            <LineItemButton
              sizePreset="main-ui"
              rounding={2}
              key="rename"
              icon={SvgEdit}
              onClick={noProp(() => setRenaming(true))}
              title="Rename"
            />,
            null,
            <LineItemButton
              sizePreset="main-ui"
              rounding={2}
              key="delete"
              icon={SvgTrash}
              onClick={noProp(() => setIsDeleteModalOpen(true))}
              color="danger"
              title="Delete"
            />,
          ]}
        </PopoverMenu>
      </Popover.Content>
    </>
  );

  return (
    <>
      <Popover
        onOpenChange={(state) => {
          setPopoverOpen(state);
        }}
      >
        <Popover.Anchor>
          <Hoverable.Root
            group="CraftSessionTab"
            interaction={popoverOpen ? "hover" : "rest"}
          >
            <SidebarTab
              /* While renaming, drop the click target so the input stays usable. */
              onClick={renaming ? undefined : onLoad}
              selected={isActive}
              rightChildren={rightMenu}
            >
              {renaming ? (
                <ButtonRenaming
                  initialName={historyItem.title}
                  onRename={onRename}
                  onClose={() => setRenaming(false)}
                />
              ) : shouldAnimate ? (
                // Opal Text takes string children only; this wraps <TypewriterText>.
                <RefreshText
                  as="p"
                  data-state={isActive ? "active" : "inactive"}
                  className="line-clamp-1 break-all text-left"
                  mainUiBody
                >
                  <TypewriterText
                    text={historyItem.title}
                    charSpeed={25}
                    animateOnMount={true}
                    onAnimationComplete={() => setShouldAnimate(false)}
                  />
                </RefreshText>
              ) : (
                historyItem.title
              )}
            </SidebarTab>
          </Hoverable.Root>
        </Popover.Anchor>
      </Popover>
      {isDeleteModalOpen && (
        <CraftSessionDeleteModal
          sessionTitle={historyItem.title}
          isDeleting={isDeleting}
          onClose={closeModal}
          onConfirm={handleConfirmDelete}
        />
      )}
    </>
  );
}

// ============================================================================
// Build Sidebar Inner
// ============================================================================

const MemoizedBuildSidebarInner = memo(() => {
  const { folded } = useSidebarState();
  const router = useRouter();
  const { requestNavigation } = useUnsavedChangesNavigation();
  const pathname = usePathname();
  const session = useSession();
  const sessionHistory = useSessionHistory();
  // Access actions directly like chat does - these don't cause re-renders
  const renameBuildSession = useBuildSessionStore(
    (state) => state.renameBuildSession
  );
  const deleteBuildSession = useBuildSessionStore(
    (state) => state.deleteBuildSession
  );
  const refreshSessionHistory = useBuildSessionStore(
    (state) => state.refreshSessionHistory
  );
  const returnToMainAgent = useBuildSessionStore(
    (state) => state.returnToMainAgent
  );

  // Fetch session history on mount
  useEffect(() => {
    refreshSessionHistory();
  }, [refreshSessionHistory]);

  // Navigate to new build - session controller handles setCurrentSession and pre-provisioning
  const navigate = useCallback(
    (destination: Route) => requestNavigation(() => router.push(destination)),
    [requestNavigation, router]
  );

  const handleNewBuild = useCallback(() => navigate(CRAFT_PATH), [navigate]);

  const handleLoadSession = useCallback(
    (sessionId: string) => {
      // Clicking a session in the sidebar always lands on the main-agent view
      // (one click back from any subagent transcript you were viewing).
      requestNavigation(() => {
        returnToMainAgent(sessionId);
        router.push(
          `${CRAFT_PATH}?${CRAFT_SEARCH_PARAM_NAMES.SESSION_ID}=${sessionId}`
        );
      });
    },
    [requestNavigation, router, returnToMainAgent]
  );

  const showLogoWhenFolded = useShowLogoWhenFolded();

  return (
    <SidebarLayouts.Root foldable>
      <SidebarLayouts.Header
        renderAppLogo={renderSidebarLogo}
        showLogoWhenFolded={showLogoWhenFolded}
      >
        <div className="flex flex-col gap-0.5">
          <SidebarTab icon={SvgEditBig} onClick={handleNewBuild}>
            Start Crafting
          </SidebarTab>
          <SidebarTab
            icon={SvgClock}
            onClick={() => navigate(CRAFT_TASKS_PATH)}
            selected={pathname.startsWith(CRAFT_TASKS_PATH)}
          >
            Scheduled Tasks
          </SidebarTab>
          <SidebarTab
            icon={SvgBlocks}
            onClick={() => navigate(CRAFT_SKILLS_PATH)}
            selected={pathname.startsWith(CRAFT_SKILLS_PATH)}
          >
            Skills
          </SidebarTab>
          <SidebarTab
            icon={SvgPlug}
            onClick={() => navigate(CRAFT_APPS_PATH)}
            selected={pathname.startsWith(CRAFT_APPS_PATH)}
          >
            Apps
          </SidebarTab>
        </div>
      </SidebarLayouts.Header>
      <SidebarLayouts.Body scrollKey="build-sidebar">
        {!folded && (
          <>
            <SidebarLayouts.Section title="Sessions" />
            {sessionHistory.length === 0 ? (
              <div className="pl-2 pr-1.5 py-1">
                <Text color="text-01">
                  Start building! Session history will appear here.
                </Text>
              </div>
            ) : (
              sessionHistory.map((historyItem) => (
                <BuildSessionButton
                  key={historyItem.id}
                  historyItem={historyItem}
                  isActive={
                    !pathname.startsWith(CRAFT_TASKS_PATH) &&
                    !pathname.startsWith(CRAFT_SKILLS_PATH) &&
                    !pathname.startsWith(CRAFT_APPS_PATH) &&
                    session?.id === historyItem.id
                  }
                  onLoad={() => handleLoadSession(historyItem.id)}
                  onRename={(newName) =>
                    renameBuildSession(historyItem.id, newName)
                  }
                  onDelete={() => deleteBuildSession(historyItem.id)}
                  onDeleteActiveSession={
                    session?.id === historyItem.id
                      ? () => navigate(CRAFT_PATH)
                      : undefined
                  }
                />
              ))
            )}
          </>
        )}
      </SidebarLayouts.Body>
      <SidebarLayouts.Footer>
        <div>
          <SidebarTab icon={SvgArrowLeft} onClick={() => navigate("/app")}>
            Back to Chat
          </SidebarTab>
          <OpencodeDebugLogsButton folded={folded} />
          <AccountPopover />
        </div>
      </SidebarLayouts.Footer>
    </SidebarLayouts.Root>
  );
});

MemoizedBuildSidebarInner.displayName = "BuildSidebarInner";

// ============================================================================
// Build Sidebar (Main Export)
// ============================================================================

export default function BuildSidebar() {
  const { leftSidebarFolded, setLeftSidebarFolded } = useBuildContext();

  return (
    <SidebarStateProvider
      defaultFolded={leftSidebarFolded}
      onFoldedChange={setLeftSidebarFolded}
    >
      <MemoizedBuildSidebarInner />
    </SidebarStateProvider>
  );
}
