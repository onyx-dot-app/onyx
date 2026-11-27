"use client";

import { useNavigation, usePathname } from "@opal/navigation";
import {
  useCallback,
  useState,
  useEffect,
  useLayoutEffect,
  useRef,
} from "react";
import useNotifications from "@/hooks/useNotifications";
import type { Route } from "next";
import { useTranslations } from "next-intl";
import { useSettings } from "@/lib/settings/hooks";
import ChatButton from "@/sections/sidebar/ChatButton";
import { useTrackChatRuns } from "@/lib/chat/hooks";
import { DragEndEvent } from "@dnd-kit/core";
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  pointerWithin,
} from "@dnd-kit/core";
import { sortableKeyboardCoordinates } from "@dnd-kit/sortable";
import { useDroppable } from "@dnd-kit/core";
import {
  restrictToFirstScrollableAncestor,
  restrictToVerticalAxis,
} from "@dnd-kit/modifiers";
import useChatSessions from "@/hooks/useChatSessions";
import { useProjects } from "@/lib/projects/hooks";
import { ProjectFolderButton } from "@/lib/projects/components";
import { CreateProjectModal } from "@/lib/projects/components";
import { MoveCustomAgentChatModal } from "@/lib/agents/components";
import { useProjectsContext } from "@/lib/projects/providers";
import { removeChatSessionFromProject } from "@/lib/projects/svc";
import type { Project } from "@/lib/projects/types";
import { SidebarLoader } from "@opal/loaders";
import { SidebarLayouts, Section } from "@opal/layouts";
import BrandedSidebarHeader from "@/sections/sidebar/BrandedSidebarHeader";
import { Button as OpalButton, Text } from "@opal/components";
import { cn } from "@opal/utils";
import { Disabled } from "@opal/core";
import { usePlans, useTierAtLeast } from "@/lib/tiers/hooks";
import { BetaTag, PlanTag } from "@/lib/tiers/components";
import { Tier } from "@/lib/tiers/types";
import { DRAG_TYPES, LOCAL_STORAGE_KEYS } from "@/lib/sidebar/constants";
import { PHFeatureFlag, usePHFeatureFlag } from "@/lib/analytics/hooks";
import {
  shouldShowMoveModal,
  showErrorNotification,
} from "@/lib/sidebar/utils";
import { handleMoveOperation } from "@/lib/sidebar/svc";
import { SidebarTab } from "@opal/components";
import { ChatSession } from "@/app/app/types";
import { useUser } from "@/providers/UserProvider";
import { useAppPosition } from "@/lib/navigation/hooks";
import { useCreateModal } from "@opal/components";
import { useModalContext } from "@/components/context/ModalContext";
import {
  SvgClock,
  SvgDevKit,
  SvgEditBig,
  SvgFolderPlus,
  SvgSearchMenu,
} from "@opal/icons";
import BuildModeIntroBackground from "@/app/craft/components/IntroBackground";
import BuildModeIntroContent from "@/app/craft/components/IntroContent";
import { CRAFT_PATH } from "@/app/craft/v1/constants";
import UnseenMarker from "@/refresh-components/UnseenMarker";
import {
  useUnviewedChatScheduledTaskCount,
  useUnviewedScheduledTaskCount,
} from "@/lib/scheduledTasks/hooks";
import { SCHEDULED_TASKS_PATH } from "@/lib/scheduledTasks/paths";
import { track, AnalyticsEvent } from "@/lib/analytics/utils";
import { motion, AnimatePresence } from "motion/react";
import { NotificationType } from "@/lib/notifications/types";
import { dismissNotification } from "@/lib/notifications/api";
import ChatSearchCommandMenu from "@/sections/sidebar/ChatSearchCommandMenu";
import ChatShortcuts, {
  useChatJumpHint,
} from "@/sections/sidebar/ChatShortcuts";
import { JUMP_TO_CHAT_SHORTCUTS } from "@/lib/shortcuts/constants";
import { formatHotkey } from "@/lib/shortcuts/utils";
import { useChatShortcutActions } from "@/lib/shortcuts/hooks";
import { sidebarWindow } from "@/lib/sidebar/utils";
import AppRail from "@/sections/sidebar/AppRail";
import AgentsSidebarContent from "@/sections/sidebar/AgentsSidebarContent";
import CustomizeSidebarContent from "@/sections/customize/CustomizeSidebarContent";
import SettingsSidebarContent from "@/sections/settings/SettingsSidebarContent";

interface RecentsSectionProps {
  chatSessions: ChatSession[];
  isLoading: boolean;
  hasMore: boolean;
  isLoadingMore: boolean;
  onLoadMore: () => void;
}

function RecentsSection({
  chatSessions,
  isLoading,
  hasMore,
  isLoadingMore,
  onLoadMore,
}: RecentsSectionProps) {
  const t = useTranslations("sidebar");
  const { modifier: jumpHintModifier, isMac } = useChatJumpHint();
  const keyNames = {
    ctrl: t("chatSearch.keys.ctrl"),
    alt: t("chatSearch.keys.alt"),
    shift: t("chatSearch.keys.shift"),
  };
  const { setNodeRef, isOver } = useDroppable({
    id: DRAG_TYPES.RECENTS,
    data: {
      type: DRAG_TYPES.RECENTS,
    },
  });

  // Sentinel ref for IntersectionObserver-based infinite scroll
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const onLoadMoreRef = useRef(onLoadMore);

  // Layout effect: an already-scheduled observer callback must not see the
  // previous page's loadMore after commit.
  useLayoutEffect(() => {
    onLoadMoreRef.current = onLoadMore;
  }, [onLoadMore]);

  useEffect(() => {
    if (!hasMore || isLoadingMore) return;

    const sentinel = sentinelRef.current;
    if (!sentinel) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          onLoadMoreRef.current();
        }
      },
      { threshold: 0 }
    );

    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMore, isLoadingMore]);

  return (
    <div
      ref={setNodeRef}
      className={cn(
        "transition-colors duration-200 rounded-08 h-full",
        isOver && "bg-background-tint-03"
      )}
    >
      <SidebarLayouts.Section title={t("appSidebar.recents.title")}>
        {isLoading ? (
          <SidebarLoader count={5} />
        ) : chatSessions.length === 0 ? (
          <div className="px-3">
            <Text as="p" color="text-01">
              {t("appSidebar.recents.empty.text")}
            </Text>
          </div>
        ) : (
          <>
            {chatSessions.map((chatSession, index) => (
              <ChatButton
                key={chatSession.id}
                chatSession={chatSession}
                draggable
                jumpShortcut={
                  jumpHintModifier && index < JUMP_TO_CHAT_SHORTCUTS.length
                    ? {
                        label: formatHotkey(
                          `${jumpHintModifier}+${index + 1}`,
                          isMac,
                          keyNames
                        ),
                        width: isMac ? "2.5rem" : "4.5rem",
                      }
                    : undefined
                }
              />
            ))}
            {hasMore && (
              <div
                ref={sentinelRef}
                // Waiting to scroll into view, nothing is loading yet.
                aria-hidden={!isLoadingMore}
                className={cn(
                  "transition-opacity duration-300",
                  isLoadingMore ? "opacity-100" : "opacity-40"
                )}
              >
                <SidebarLoader count={3} />
              </div>
            )}
          </>
        )}
      </SidebarLayouts.Section>
    </div>
  );
}

export default function AppSidebar() {
  const t = useTranslations("sidebar");
  const tCraftUpgrade = useTranslations("craft.upgrade");
  const moveChatErrorMessage = t("appSidebar.moveChatError.message");
  const navigation = useNavigation();
  const combinedSettingsData = useSettings();
  const { newTenantInfo, invitationInfo } = useModalContext();
  const { resetNewSession } = useChatShortcutActions();
  useTrackChatRuns();

  // Use SWR hooks for data fetching
  const {
    chatSessions,
    refreshChatSessions,
    isLoading: isLoadingChatSessions,
    hasMore,
    isLoadingMore,
    loadMore,
  } = useChatSessions();
  const {
    projects,
    refreshProjects,
    isLoading: isLoadingProjects,
  } = useProjects();
  // Still need some context for stateful operations
  const { refreshCurrentProjectDetails, currentProjectId } =
    useProjectsContext();

  // State for custom agent modal
  const [pendingMoveChatSession, setPendingMoveChatSession] =
    useState<ChatSession | null>(null);
  const [pendingMoveProjectId, setPendingMoveProjectId] = useState<
    number | null
  >(null);
  const moveCustomAgentModal = useCreateModal();

  // Check if Onyx Craft is enabled via settings (backed by PostHog feature flag)
  // Only explicit true enables the feature; false or undefined = disabled
  const isOnyxCraftEnabled = combinedSettingsData?.onyx_craft_enabled === true;
  const isOnyxCraftUpsell =
    !isOnyxCraftEnabled &&
    combinedSettingsData?.onyx_craft_requires_upgrade === true;
  // Gated like a Business admin page: below that tier the tab is disabled.
  const hasCraftTier = useTierAtLeast(Tier.BUSINESS);
  const tTasks = useTranslations("craft.tasks");
  const unviewedTaskCount = useUnviewedScheduledTaskCount(
    isOnyxCraftEnabled && hasCraftTier
  );
  const tScheduledTasks = useTranslations("scheduledTasks");
  const unviewedChatTaskCount = useUnviewedChatScheduledTaskCount();
  const plans = usePlans();

  // Fetch notifications for build mode intro
  const { notifications, refresh: mutateNotifications } = useNotifications({
    enabled: isOnyxCraftEnabled,
  });

  // Find build_mode feature announcement notification (only if Onyx Craft is enabled)
  const buildModeNotification = isOnyxCraftEnabled
    ? notifications?.find(
        (n) =>
          n.notif_type === NotificationType.FEATURE_ANNOUNCEMENT &&
          n.additional_data?.feature === "build_mode" &&
          !n.dismissed
      )
    : undefined;

  // State for intro animation overlay
  const [showIntroAnimation, setShowIntroAnimation] = useState(false);
  // Track if auto-trigger has fired (prevents race condition during dismiss)
  const hasAutoTriggeredRef = useRef(false);

  // Auto-show intro once when there's an undismissed notification
  // Don't show if tenant/invitation modal is open (e.g., "join existing team" modal)
  // Gated by PostHog feature flag: if `craft-animation-disabled` is true (or
  // PostHog is unavailable), skip the auto-show entirely.
  const isCraftAnimationDisabled = usePHFeatureFlag(
    PHFeatureFlag.CRAFT_ANIMATION_DISABLED
  );
  const hasTenantModal = !!(newTenantInfo || invitationInfo);
  useEffect(() => {
    if (
      isOnyxCraftEnabled &&
      buildModeNotification &&
      !hasAutoTriggeredRef.current &&
      !hasTenantModal &&
      !isCraftAnimationDisabled
    ) {
      hasAutoTriggeredRef.current = true;
      setShowIntroAnimation(true);
    }
  }, [
    buildModeNotification,
    isOnyxCraftEnabled,
    hasTenantModal,
    isCraftAnimationDisabled,
  ]);

  // Dismiss the build mode notification
  const dismissBuildModeNotification = useCallback(async () => {
    if (!buildModeNotification) return;
    try {
      await dismissNotification(buildModeNotification.id);
      mutateNotifications();
    } catch (error) {
      console.error("Error dismissing notification:", error);
    }
  }, [buildModeNotification, mutateNotifications]);

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  // Perform the actual move
  async function performChatMove(
    targetProjectId: number,
    chatSession: ChatSession
  ) {
    try {
      await handleMoveOperation({
        chatSession,
        targetProjectId,
        refreshChatSessions,
        refreshCurrentProjectDetails,
        fetchProjects: refreshProjects,
        currentProjectId,
      });
      const projectRefreshPromise = currentProjectId
        ? refreshCurrentProjectDetails()
        : refreshProjects();
      await Promise.all([refreshChatSessions(), projectRefreshPromise]);
    } catch (error) {
      console.error("Failed to move chat:", error);
      throw error;
    }
  }

  // Handle chat to project drag and drop
  const handleChatProjectDragEnd = useCallback(
    async (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over) return;

      const activeData = active.data.current;
      const overData = over.data.current;

      if (!activeData || !overData) {
        return;
      }

      // Check if we're dragging a chat onto a project
      if (
        activeData?.type === DRAG_TYPES.CHAT &&
        overData?.type === DRAG_TYPES.PROJECT
      ) {
        const chatSession = activeData.chatSession as ChatSession;
        const targetProject = overData.project as Project;
        const sourceProjectId = activeData.projectId;

        // Don't do anything if dropping on the same project
        if (sourceProjectId === targetProject.id) {
          return;
        }

        if (shouldShowMoveModal(chatSession)) {
          setPendingMoveChatSession(chatSession);
          setPendingMoveProjectId(targetProject.id);
          moveCustomAgentModal.toggle(true);
          return;
        }

        try {
          await performChatMove(targetProject.id, chatSession);
        } catch (error) {
          showErrorNotification(moveChatErrorMessage);
        }
      }

      // Check if we're dragging a chat from a project to the Recents section
      if (
        activeData?.type === DRAG_TYPES.CHAT &&
        overData?.type === DRAG_TYPES.RECENTS
      ) {
        const chatSession = activeData.chatSession as ChatSession;
        const sourceProjectId = activeData.projectId;

        // Only remove from project if it was in a project
        if (sourceProjectId) {
          try {
            await removeChatSessionFromProject(chatSession.id);
            const projectRefreshPromise = currentProjectId
              ? refreshCurrentProjectDetails()
              : refreshProjects();
            await Promise.all([refreshChatSessions(), projectRefreshPromise]);
          } catch (error) {
            console.error("Failed to remove chat from project:", error);
          }
        }
      }
    },
    [
      currentProjectId,
      refreshChatSessions,
      refreshCurrentProjectDetails,
      refreshProjects,
      moveChatErrorMessage,
      moveCustomAgentModal.toggle,
    ]
  );

  const { isAdmin } = useUser();
  const activeWindow = sidebarWindow(usePathname());
  const activeSidebarTab = useAppPosition();
  const craftLink = navigation.linkTo(CRAFT_PATH, { scroll: false });
  const createProjectModal = useCreateModal();

  const newProjectButton = (
    <SidebarTab
      icon={SvgFolderPlus}
      onClick={() => createProjectModal.toggle(true)}
      selected={createProjectModal.isOpen}
      variant="sidebar-light"
    >
      {t("appSidebar.newProject.label")}
    </SidebarTab>
  );

  const handleShowBuildIntro = useCallback(() => {
    setShowIntroAnimation(true);
  }, []);

  return (
    <>
      <ChatShortcuts />
      {/* The Chat sidebar renders the menu with its trigger. Elsewhere it
          stays mounted for its ⌘K hotkey. */}
      {activeWindow !== "chat" && (
        <ChatSearchCommandMenu trigger={() => null} />
      )}
      <createProjectModal.Provider>
        <CreateProjectModal />
      </createProjectModal.Provider>

      <moveCustomAgentModal.Provider>
        <MoveCustomAgentChatModal
          onCancel={() => {
            moveCustomAgentModal.toggle(false);
            setPendingMoveChatSession(null);
            setPendingMoveProjectId(null);
          }}
          onConfirm={async (doNotShowAgain: boolean) => {
            if (doNotShowAgain && typeof window !== "undefined") {
              window.localStorage.setItem(
                LOCAL_STORAGE_KEYS.HIDE_MOVE_CUSTOM_AGENT_MODAL,
                "true"
              );
            }
            const chat = pendingMoveChatSession;
            const target = pendingMoveProjectId;
            moveCustomAgentModal.toggle(false);
            setPendingMoveChatSession(null);
            setPendingMoveProjectId(null);
            if (chat && target != null) {
              try {
                await performChatMove(target, chat);
              } catch (error) {
                showErrorNotification(moveChatErrorMessage);
              }
            }
          }}
        />
      </moveCustomAgentModal.Provider>

      {/* Intro animation overlay */}
      <AnimatePresence>
        {showIntroAnimation && (
          <motion.div
            className="fixed inset-0 z-9999"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.5 }}
          >
            <BuildModeIntroBackground />
            <BuildModeIntroContent
              onClose={() => {
                setShowIntroAnimation(false);
                dismissBuildModeNotification();
              }}
              onTryBuildMode={() => {
                setShowIntroAnimation(false);
                dismissBuildModeNotification();
                navigation.go(CRAFT_PATH);
              }}
            />
          </motion.div>
        )}
      </AnimatePresence>

      <SidebarLayouts.Root
        rail={
          <AppRail
            onShowBuildIntro={
              isOnyxCraftEnabled ? handleShowBuildIntro : undefined
            }
          />
        }
        brand={<BrandedSidebarHeader />}
      >
        {activeWindow === "agents" ? (
          <AgentsSidebarContent sensors={sensors} />
        ) : activeWindow === "customize" ? (
          <CustomizeSidebarContent />
        ) : activeWindow === "settings" ? (
          <SettingsSidebarContent />
        ) : (
          <>
            <SidebarLayouts.Header>
              <div data-testid="AppSidebar/new-session">
                <SidebarTab
                  icon={SvgEditBig}
                  href={activeSidebarTab.linkToNewSession().href}
                  selected={activeSidebarTab.isNewSession()}
                  onClick={(event) => {
                    const handledBefore = event.defaultPrevented;
                    activeSidebarTab.linkToNewSession().onClick(event);
                    if (!handledBefore && event.defaultPrevented)
                      resetNewSession();
                  }}
                >
                  {t("appSidebar.newSession.label")}
                </SidebarTab>
              </div>
              <ChatSearchCommandMenu
                trigger={(open, isOpen) => (
                  <SidebarTab
                    icon={SvgSearchMenu}
                    selected={isOpen}
                    onClick={open}
                  >
                    {t("appSidebar.searchChats.label")}
                  </SidebarTab>
                )}
              />
              {(isOnyxCraftEnabled || isOnyxCraftUpsell) && (
                <div data-testid="AppSidebar/build">
                  <Disabled
                    disabled={!hasCraftTier}
                    // Only admins can open billing, so others are told to ask one.
                    tooltip={
                      isAdmin
                        ? plans[Tier.BUSINESS].tooltip
                        : tCraftUpgrade("userDescription")
                    }
                  >
                    <SidebarTab
                      icon={SvgDevKit}
                      href={hasCraftTier ? craftLink.href : undefined}
                      onClick={
                        hasCraftTier
                          ? (event) => {
                              track(AnalyticsEvent.CLICKED_CRAFT_IN_SIDEBAR);
                              craftLink.onClick(event);
                            }
                          : undefined
                      }
                      rightChildren={
                        isOnyxCraftUpsell ? (
                          <PlanTag plan={Tier.BUSINESS} />
                        ) : (
                          <Section
                            flexDirection="row"
                            gap={1.5}
                            width="fit"
                            height="fit"
                          >
                            {unviewedTaskCount > 0 && (
                              <UnseenMarker label={tTasks("unviewedResults")} />
                            )}
                            <BetaTag />
                          </Section>
                        )
                      }
                    >
                      {t("appSidebar.craft.label")}
                    </SidebarTab>
                  </Disabled>
                </div>
              )}
              <div data-testid="AppSidebar/scheduled-tasks">
                <SidebarTab
                  icon={SvgClock}
                  {...navigation.linkTo(SCHEDULED_TASKS_PATH, {
                    scroll: false,
                  })}
                  selected={activeSidebarTab.isScheduledTasks()}
                  rightChildren={
                    unviewedChatTaskCount > 0 ? (
                      <UnseenMarker
                        label={tScheduledTasks("unviewedResults")}
                      />
                    ) : undefined
                  }
                >
                  {t("appSidebar.scheduledTasks.label")}
                </SidebarTab>
              </div>
            </SidebarLayouts.Header>

            <SidebarLayouts.Body scrollKey="app-sidebar">
              <>
                {/* Wrap Projects and Recents in a shared DndContext for chat-to-project drag */}
                <DndContext
                  sensors={sensors}
                  collisionDetection={pointerWithin}
                  modifiers={[
                    restrictToFirstScrollableAncestor,
                    restrictToVerticalAxis,
                  ]}
                  onDragEnd={handleChatProjectDragEnd}
                >
                  {/* Projects */}
                  <SidebarLayouts.Section
                    title={t("appSidebar.projects.title")}
                    action={
                      <OpalButton
                        icon={SvgFolderPlus}
                        prominence="tertiary"
                        size="md"
                        tooltip={t("appSidebar.newProject.tooltip")}
                        onClick={() => createProjectModal.toggle(true)}
                      />
                    }
                  >
                    {isLoadingProjects ? (
                      <SidebarLoader count={2} />
                    ) : (
                      <>
                        {projects.map((project) => (
                          <ProjectFolderButton
                            key={project.id}
                            project={project}
                          />
                        ))}
                        {projects.length === 0 && newProjectButton}
                      </>
                    )}
                  </SidebarLayouts.Section>

                  {/* Recents */}
                  <RecentsSection
                    chatSessions={chatSessions}
                    isLoading={isLoadingChatSessions}
                    hasMore={hasMore}
                    isLoadingMore={isLoadingMore}
                    onLoadMore={loadMore}
                  />
                </DndContext>
              </>
            </SidebarLayouts.Body>
          </>
        )}
      </SidebarLayouts.Root>
    </>
  );
}
