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
import { SidebarTab, Text } from "@opal/components";
import {
  SidebarLayouts,
  SidebarStateProvider,
  useSidebarState,
} from "@opal/layouts";
import RefreshText from "@/refresh-components/texts/Text";
import { renderAppLogo } from "@/sections/sidebar/SidebarWrapper";
import { useShowLogoWhenFolded } from "@/lib/sidebar/hooks";
import AccountPopover from "@/sections/sidebar/AccountPopover";
import { Popover, PopoverMenu } from "@opal/components";
import IconButton from "@/refresh-components/buttons/IconButton";
import ButtonRenaming from "@/refresh-components/buttons/ButtonRenaming";
import LineItem from "@/refresh-components/buttons/LineItem";
import { noProp } from "@/lib/utils";
import { cn } from "@opal/utils";
import {
  SvgEditBig,
  SvgArrowLeft,
  SvgBlocks,
  SvgClock,
  SvgMoreHorizontal,
  SvgEdit,
  SvgTrash,
  SvgCheckCircle,
  SvgPlug,
  SvgSimpleLoader,
} from "@opal/icons";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { Button } from "@opal/components";
import TypewriterText from "@/app/craft/components/TypewriterText";
import OpencodeDebugLogsButton from "@/app/craft/components/OpencodeDebugLogs";
import {
  DELETE_SUCCESS_DISPLAY_DURATION_MS,
  DELETE_MESSAGE_ROTATION_INTERVAL_MS,
} from "@/app/craft/constants";
import {
  CRAFT_PATH,
  CRAFT_SKILLS_PATH,
  CRAFT_APPS_PATH,
  CRAFT_TASKS_PATH,
} from "@/app/craft/v1/constants";

// ============================================================================
// Fun Deleting Messages
// ============================================================================

const DELETING_MESSAGES = [
  "正在清理构建记录...",
  "正在回收会话资源...",
  "正在移除工作区快照...",
  "正在整理临时文件...",
  "正在关闭后台任务...",
  "正在删除会话数据...",
  "正在释放缓存...",
  "正在归档历史状态...",
  "正在同步删除结果...",
  "正在刷新侧边栏...",
  "正在完成最后一步...",
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
    <div className="animate-subtle-pulse">
      <Text as="p" color="text-03">
        {DELETING_MESSAGES[messageIndex]}
      </Text>
    </div>
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
          err instanceof Error ? err.message : "删除会话失败"
        );
      }
    },
    [onDelete, closeModal, isActive, onDeleteActiveSession]
  );

  const rightMenu = (
    <>
      <Popover.Trigger asChild onClick={noProp()}>
        <div>
          {/* TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved */}
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
              重命名
            </LineItem>,
            null,
            <LineItem
              key="delete"
              icon={SvgTrash}
              onClick={noProp(() => setIsDeleteModalOpen(true))}
              danger
            >
              删除
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
        </Popover.Anchor>
      </Popover>
      {isDeleteModalOpen && (
        <ConfirmationModalLayout
          title={
            deleteSuccess
              ? "已删除"
              : deleteError
                ? "删除失败"
                : "删除 Glomi 创作会话"
          }
          icon={deleteSuccess ? SvgCheckCircle : SvgTrash}
          onClose={isDeleting || deleteSuccess ? undefined : closeModal}
          hideCancel={isDeleting || deleteSuccess}
          twoTone={!isDeleting && !deleteSuccess && !deleteError}
          submit={
            deleteSuccess ? (
              <Button disabled variant="action" icon={SvgCheckCircle}>
                完成
              </Button>
            ) : deleteError ? (
              <Button variant="danger" onClick={closeModal}>
                关闭
              </Button>
            ) : (
              <Button
                disabled={isDeleting}
                variant="danger"
                onClick={handleConfirmDelete}
                icon={isDeleting ? SvgSimpleLoader : undefined}
              >
                {isDeleting ? "正在删除..." : "删除"}
              </Button>
            )
          }
        >
          {deleteSuccess ? (
            <Text as="p" color="text-03">
              构建已成功删除。
            </Text>
          ) : deleteError ? (
            <Text as="p" color="status-error-02">
              {deleteError}
            </Text>
          ) : isDeleting ? (
            <DeletingMessage />
          ) : (
            "确定要删除此 Glomi 创作会话吗？此操作无法撤销。"
          )}
        </ConfirmationModalLayout>
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
  const { limits, isEnabled } = useUsageLimits();

  // Fetch session history on mount
  useEffect(() => {
    refreshSessionHistory();
  }, [refreshSessionHistory]);

  // Build section title with usage if cloud is enabled
  // limit=0 indicates unlimited (local/self-hosted mode), so hide the count
  const sessionsTitle = useMemo(() => {
    if (isEnabled && limits && limits.limit > 0) {
      return `总消息数（${limits.messagesUsed}/${limits.limit}）`;
    }
    return "会话";
  }, [isEnabled, limits]);

  // Navigate to new build - session controller handles setCurrentSession and pre-provisioning
  const handleNewBuild = useCallback(() => {
    router.push(CRAFT_PATH);
  }, [router]);

  const handleLoadSession = useCallback(
    (sessionId: string) => {
      // Clicking a session in the sidebar always lands on the main-agent view
      // (one click back from any subagent transcript you were viewing).
      returnToMainAgent(sessionId);
      router.push(
        `${CRAFT_PATH}?${CRAFT_SEARCH_PARAM_NAMES.SESSION_ID}=${sessionId}`
      );
    },
    [router, returnToMainAgent]
  );

  const newBuildButton = useMemo(
    () => (
      <SidebarTab icon={SvgEditBig} folded={folded} onClick={handleNewBuild}>
        开始创作
      </SidebarTab>
    ),
    [folded, handleNewBuild]
  );

  const scheduledTasksPanel = useMemo(
    () => (
      <SidebarTab
        icon={SvgClock}
        folded={folded}
        href={CRAFT_TASKS_PATH}
        selected={pathname.startsWith(CRAFT_TASKS_PATH)}
      >
        定时任务
      </SidebarTab>
    ),
    [folded, pathname]
  );

  const appsTab = useMemo(
    () => (
      <SidebarTab
        icon={SvgPlug}
        folded={folded}
        href={CRAFT_APPS_PATH}
        selected={pathname.startsWith(CRAFT_APPS_PATH)}
      >
        应用
      </SidebarTab>
    ),
    [folded, pathname]
  );

  const skillsPanel = useMemo(
    () => (
      <SidebarTab
        icon={SvgBlocks}
        folded={folded}
        href={CRAFT_SKILLS_PATH}
        selected={pathname.startsWith(CRAFT_SKILLS_PATH)}
      >
        技能
      </SidebarTab>
    ),
    [folded, pathname]
  );

  const backToChatButton = useMemo(
    () => (
      <SidebarTab icon={SvgArrowLeft} folded={folded} href="/app">
        返回聊天
      </SidebarTab>
    ),
    [folded]
  );

  const footer = useMemo(
    () => (
      <div>
        {backToChatButton}
        <OpencodeDebugLogsButton folded={folded} />
        <AccountPopover folded={folded} />
      </div>
    ),
    [folded, backToChatButton]
  );

  const showLogoWhenFolded = useShowLogoWhenFolded();

  return (
    <SidebarLayouts.Root foldable>
      <SidebarLayouts.Header
        logo={renderAppLogo}
        showLogoWhenFolded={showLogoWhenFolded}
      >
        <div className="flex flex-col gap-0.5">
          {newBuildButton}
          {scheduledTasksPanel}
          {skillsPanel}
          {appsTab}
        </div>
      </SidebarLayouts.Header>
      <SidebarLayouts.Body scrollKey="build-sidebar">
        {!folded && (
          <>
            <SidebarLayouts.Section title={sessionsTitle} />
            {sessionHistory.length === 0 ? (
              <div className="pl-2 pr-1.5 py-1">
                <Text color="text-01">
                  开始创作吧！会话历史会显示在这里。
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
                      ? () => router.push(CRAFT_PATH)
                      : undefined
                  }
                />
              ))
            )}
          </>
        )}
      </SidebarLayouts.Body>
      <SidebarLayouts.Footer>{footer}</SidebarLayouts.Footer>
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
