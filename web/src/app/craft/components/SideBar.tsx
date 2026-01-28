"use client";

import { memo, useMemo, useCallback, useState, useEffect, useRef } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useBuildContext } from "@/app/craft/contexts/BuildContext";
import {
  useSession,
  useSessionHistory,
  useBuildSessionStore,
  SessionHistoryItem,
} from "@/app/craft/hooks/useBuildSessionStore";
import { useUsageLimits } from "@/app/craft/hooks/useUsageLimits";
import { CRAFT_SEARCH_PARAM_NAMES } from "@/app/craft/services/searchParams";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import Text from "@/refresh-components/texts/Text";
import SidebarWrapper from "@/sections/sidebar/SidebarWrapper";
import SidebarBody from "@/sections/sidebar/SidebarBody";
import SidebarSection from "@/sections/sidebar/SidebarSection";
import UserAvatarPopover from "@/sections/sidebar/UserAvatarPopover";
import Popover, { PopoverMenu } from "@/refresh-components/Popover";
import IconButton from "@/refresh-components/buttons/IconButton";
import ButtonRenaming from "@/refresh-components/buttons/ButtonRenaming";
import LineItem from "@/refresh-components/buttons/LineItem";
import { cn, noProp } from "@/lib/utils";
import useScreenSize from "@/hooks/useScreenSize";
import {
  SvgEditBig,
  SvgArrowLeft,
  SvgSettings,
  SvgMoreHorizontal,
  SvgEdit,
  SvgTrash,
  SvgCheckCircle,
} from "@opal/icons";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import Button from "@/refresh-components/buttons/Button";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import TypewriterText from "@/app/craft/components/TypewriterText";
import {
  DELETE_SUCCESS_DISPLAY_DURATION_MS,
  DELETE_MESSAGE_ROTATION_INTERVAL_MS,
} from "@/app/craft/constants";
import { CRAFT_PATH, CRAFT_CONFIGURE_PATH } from "@/app/craft/v1/constants";

// ============================================================================
// Fun Deleting Messages
// ============================================================================

const DELETING_MESSAGES = [
  "Mining away your blocks...",
  "Returning diamonds to the caves...",
  "Creeper blew up your save file...",
  "Throwing items into lava...",
  "Despawning your entities...",
  "Breaking bedrock illegally...",
  "Enderman teleported your data away...",
  "Falling into the void...",
  "Your build ran out of hearts...",
  "Respawning at world spawn...",
  "Feeding your code to the Ender Dragon...",
  "Activating TNT chain reaction...",
  "Zombie horde consumed your bytes...",
  "Wither withering your session...",
  "Herobrine deleted your world...",
];

function DeletingMessage() {
  const [messageIndex, setMessageIndex] = useState(() =>
    Math.floor(Math.random() * DELETING_MESSAGES.length)
  );

  useEffect(() => {
    const interval = setInterval(() => {
      setMessageIndex((prev) => {
        let next = Math.floor(Math.random() * DELETING_MESSAGES.length);
        while (next === prev && DELETING_MESSAGES.length > 1) {
          next = Math.floor(Math.random() * DELETING_MESSAGES.length);
        }
        return next;
      });
    }, DELETE_MESSAGE_ROTATION_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  return (
    <Text as="p" text03 className="animate-subtle-pulse">
      {DELETING_MESSAGES[messageIndex]}
    </Text>
  );
}

// ============================================================================
// Build Session Button
// ============================================================================

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
  const [deleteSuccess, setDeleteSuccess] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const deleteTimeoutRef = useRef<NodeJS.Timeout | null>(null);

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
    if (deleteTimeoutRef.current) {
      clearTimeout(deleteTimeoutRef.current);
      deleteTimeoutRef.current = null;
    }
    setIsDeleteModalOpen(false);
    setPopoverOpen(false);
    setDeleteSuccess(false);
    setDeleteError(null);
    setIsDeleting(false);
  }, []);

  const handleConfirmDelete = useCallback(
    async (e: React.MouseEvent<HTMLButtonElement>) => {
      e.stopPropagation();
      setIsDeleting(true);
      setDeleteError(null);

      try {
        await onDelete();
        setIsDeleting(false);
        setDeleteSuccess(true);
        // Show success briefly, then close and redirect if needed
        deleteTimeoutRef.current = setTimeout(() => {
          closeModal();
          if (isActive && onDeleteActiveSession) {
            onDeleteActiveSession();
          }
        }, DELETE_SUCCESS_DISPLAY_DURATION_MS);
      } catch (err) {
        setIsDeleting(false);
        setDeleteError(
          err instanceof Error ? err.message : "Failed to delete session"
        );
      }
    },
    [onDelete, closeModal, isActive, onDeleteActiveSession]
  );

  const rightMenu = (
    <>
      <Popover.Trigger asChild onClick={noProp()}>
        <div>
          <IconButton
            icon={SvgMoreHorizontal}
            className={cn(
              !popoverOpen && "hidden",
              !renaming && "group-hover/SidebarTab:flex"
            )}
            transient={popoverOpen}
            internal
          />
        </div>
      </Popover.Trigger>
      <Popover.Content side="right" align="start">
        <PopoverMenu>
          {[
            <LineItem
              key="rename"
              icon={SvgEdit}
              onClick={noProp(() => setRenaming(true))}
            >
              Rename
            </LineItem>,
            null,
            <LineItem
              key="delete"
              icon={SvgTrash}
              onClick={noProp(() => setIsDeleteModalOpen(true))}
              danger
            >
              Delete
            </LineItem>,
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
          <SidebarTab
            onClick={onLoad}
            transient={isActive}
            rightChildren={rightMenu}
            focused={renaming}
          >
            {renaming ? (
              <ButtonRenaming
                initialName={historyItem.title}
                onRename={onRename}
                onClose={() => setRenaming(false)}
              />
            ) : shouldAnimate ? (
              <Text
                as="p"
                data-state={isActive ? "active" : "inactive"}
                className={cn(
                  "sidebar-tab-text-defaulted line-clamp-1 break-all text-left"
                )}
                mainUiBody
              >
                <TypewriterText
                  text={historyItem.title}
                  charSpeed={25}
                  animateOnMount={true}
                  onAnimationComplete={() => setShouldAnimate(false)}
                />
              </Text>
            ) : (
              historyItem.title
            )}
          </SidebarTab>
        </Popover.Anchor>
      </Popover>
      {isDeleteModalOpen && (
        <ConfirmationModalLayout
          title={
            deleteSuccess
              ? "Deleted"
              : deleteError
                ? "Delete Failed"
                : "Delete Build"
          }
          icon={deleteSuccess ? SvgCheckCircle : SvgTrash}
          onClose={isDeleting || deleteSuccess ? undefined : closeModal}
          hideCancel={isDeleting || deleteSuccess}
          twoTone={!isDeleting && !deleteSuccess && !deleteError}
          submit={
            deleteSuccess ? (
              <Button action disabled leftIcon={SvgCheckCircle}>
                Done
              </Button>
            ) : deleteError ? (
              <Button danger onClick={closeModal}>
                Close
              </Button>
            ) : (
              <Button
                danger
                onClick={handleConfirmDelete}
                disabled={isDeleting}
                leftIcon={isDeleting ? SimpleLoader : undefined}
              >
                {isDeleting ? "Deleting..." : "Delete"}
              </Button>
            )
          }
        >
          {deleteSuccess ? (
            <Text as="p" text03>
              Build deleted successfully.
            </Text>
          ) : deleteError ? (
            <Text as="p" text03 className="text-status-error-02">
              {deleteError}
            </Text>
          ) : isDeleting ? (
            <DeletingMessage />
          ) : (
            "Are you sure you want to delete this craft? This action cannot be undone."
          )}
        </ConfirmationModalLayout>
      )}
    </>
  );
}

// ============================================================================
// Build Sidebar Inner
// ============================================================================

interface BuildSidebarInnerProps {
  folded: boolean;
  onFoldClick: () => void;
}

const MemoizedBuildSidebarInner = memo(
  ({ folded, onFoldClick }: BuildSidebarInnerProps) => {
    const router = useRouter();
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
    const { limits, isEnabled } = useUsageLimits();

    // Fetch session history on mount
    useEffect(() => {
      refreshSessionHistory();
    }, [refreshSessionHistory]);

    // Build section title with usage if cloud is enabled
    const sessionsTitle = useMemo(() => {
      if (isEnabled && limits) {
        return `Sessions (${limits.messagesUsed}/${limits.limit})`;
      }
      return "Sessions";
    }, [isEnabled, limits]);

    // Navigate to new build - session controller handles setCurrentSession and pre-provisioning
    const handleNewBuild = useCallback(() => {
      router.push(CRAFT_PATH);
    }, [router]);

    const handleLoadSession = useCallback(
      (sessionId: string) => {
        router.push(
          `${CRAFT_PATH}?${CRAFT_SEARCH_PARAM_NAMES.SESSION_ID}=${sessionId}`
        );
      },
      [router]
    );

    const newBuildButton = useMemo(
      () => (
        <SidebarTab
          leftIcon={SvgEditBig}
          folded={folded}
          onClick={handleNewBuild}
        >
          Start Crafting
        </SidebarTab>
      ),
      [folded, handleNewBuild]
    );

    const buildConfigurePanel = useMemo(
      () => (
        <SidebarTab
          leftIcon={SvgSettings}
          folded={folded}
          href={CRAFT_CONFIGURE_PATH}
          transient={pathname.startsWith(CRAFT_CONFIGURE_PATH)}
        >
          Configure
        </SidebarTab>
      ),
      [folded, pathname]
    );

    const backToChatButton = useMemo(
      () => (
        <SidebarTab leftIcon={SvgArrowLeft} folded={folded} href="/chat">
          Back to Chat
        </SidebarTab>
      ),
      [folded]
    );

    const footer = useMemo(
      () => (
        <div>
          {backToChatButton}
          <UserAvatarPopover folded={folded} />
        </div>
      ),
      [folded, backToChatButton]
    );

    return (
      <SidebarWrapper folded={folded} onFoldClick={onFoldClick}>
        <SidebarBody
          actionButtons={
            <div className="flex flex-col gap-0.5">
              {newBuildButton}
              {buildConfigurePanel}
            </div>
          }
          footer={footer}
          scrollKey="build-sidebar"
        >
          {!folded && (
            <SidebarSection title={sessionsTitle}>
              {sessionHistory.length === 0 ? (
                <div className="pl-2 pr-1.5 py-1">
                  <Text text01>
                    Start building! Session history will appear here.
                  </Text>
                </div>
              ) : (
                sessionHistory.map((historyItem) => (
                  <BuildSessionButton
                    key={historyItem.id}
                    historyItem={historyItem}
                    isActive={
                      !pathname.startsWith(CRAFT_CONFIGURE_PATH) &&
                      session?.id === historyItem.id
                    }
                    onLoad={() => handleLoadSession(historyItem.id)}
                    onRename={(newName) =>
                      renameBuildSession(historyItem.id, newName)
                    }
                    onDelete={() => deleteBuildSession(historyItem.id)}
                    onDeleteActiveSession={
                      session?.id === historyItem.id
                        ? () => router.push(CRAFT_PATH)
                        : undefined
                    }
                  />
                ))
              )}
            </SidebarSection>
          )}
        </SidebarBody>
      </SidebarWrapper>
    );
  }
);

MemoizedBuildSidebarInner.displayName = "BuildSidebarInner";

// ============================================================================
// Build Sidebar (Main Export)
// ============================================================================

export default function BuildSidebar() {
  const { leftSidebarFolded, setLeftSidebarFolded } = useBuildContext();
  const { isMobile } = useScreenSize();

  if (!isMobile)
    return (
      <MemoizedBuildSidebarInner
        folded={leftSidebarFolded}
        onFoldClick={() => setLeftSidebarFolded((prev) => !prev)}
      />
    );

  return (
    <>
      <div
        className={cn(
          "fixed inset-y-0 left-0 z-50 transition-transform duration-200",
          leftSidebarFolded ? "-translate-x-full" : "translate-x-0"
        )}
      >
        <MemoizedBuildSidebarInner
          folded={false}
          onFoldClick={() => setLeftSidebarFolded(true)}
        />
      </div>

      {/* Hitbox to close the sidebar if anything outside of it is touched */}
      <div
        className={cn(
          "fixed inset-0 z-40 bg-mask-03 backdrop-blur-03 transition-opacity duration-200",
          leftSidebarFolded
            ? "opacity-0 pointer-events-none"
            : "opacity-100 pointer-events-auto"
        )}
        onClick={() => setLeftSidebarFolded(true)}
      />
    </>
  );
}
