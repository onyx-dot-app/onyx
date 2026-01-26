"use client";

import { memo, useMemo, useCallback, useState, useEffect, useRef } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useBuildContext } from "@/app/build/contexts/BuildContext";
import {
  useSession,
  useSessionHistory,
  useBuildSessionStore,
  SessionHistoryItem,
} from "@/app/build/hooks/useBuildSessionStore";
import { useUsageLimits } from "@/app/build/hooks/useUsageLimits";
import { BUILD_SEARCH_PARAM_NAMES } from "@/app/build/services/searchParams";
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
} from "@opal/icons";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import Button from "@/refresh-components/buttons/Button";
import TypewriterText from "@/app/build/components/TypewriterText";

// ============================================================================
// Build Session Button
// ============================================================================

interface BuildSessionButtonProps {
  historyItem: SessionHistoryItem;
  isActive: boolean;
  onLoad: () => void;
  onRename: (newName: string) => Promise<void>;
  onDelete: () => Promise<void>;
}

function BuildSessionButton({
  historyItem,
  isActive,
  onLoad,
  onRename,
  onDelete,
}: BuildSessionButtonProps) {
  const [renaming, setRenaming] = useState(false);
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  // Track title changes for typewriter animation (only for auto-naming, not manual rename)
  const prevTitleRef = useRef(historyItem.title);
  const [shouldAnimate, setShouldAnimate] = useState(false);

  // Detect when title changes from "Fresh Craft" to a real name (auto-naming)
  useEffect(() => {
    const prevTitle = prevTitleRef.current;
    const newTitle = historyItem.title;

    // Animate only when transitioning from default name to LLM-generated name
    if (prevTitle !== newTitle && prevTitle === "Fresh Craft" && !renaming) {
      setShouldAnimate(true);
    }

    prevTitleRef.current = newTitle;
  }, [historyItem.title, renaming]);

  const handleConfirmDelete = useCallback(
    async (e: React.MouseEvent<HTMLButtonElement>) => {
      e.stopPropagation();
      await onDelete();
      setIsDeleteModalOpen(false);
      setPopoverOpen(false);
    },
    [onDelete]
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
          title="Delete Build"
          icon={SvgTrash}
          onClose={() => setIsDeleteModalOpen(false)}
          submit={
            <Button danger onClick={handleConfirmDelete}>
              Delete
            </Button>
          }
        >
          Are you sure you want to delete this build? This action cannot be
          undone.
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
      router.push("/build/v1");
    }, [router]);

    const handleLoadSession = useCallback(
      (sessionId: string) => {
        router.push(
          `/build/v1?${BUILD_SEARCH_PARAM_NAMES.SESSION_ID}=${sessionId}`
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
          href="/build/v1/configure"
          transient={pathname.startsWith("/build/v1/configure")}
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
        <div className="flex flex-col gap-2">
          {backToChatButton}
          <UserAvatarPopover folded={folded} />
        </div>
      ),
      [folded, backToChatButton]
    );

    return (
      <SidebarWrapper folded={folded} onFoldClick={onFoldClick}>
        <SidebarBody
          actionButtons={[newBuildButton, buildConfigurePanel]}
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
                      !pathname.startsWith("/build/v1/configure") &&
                      session?.id === historyItem.id
                    }
                    onLoad={() => handleLoadSession(historyItem.id)}
                    onRename={(newName) =>
                      renameBuildSession(historyItem.id, newName)
                    }
                    onDelete={() => deleteBuildSession(historyItem.id)}
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
