"use client";

import { memo, useCallback, useMemo, useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { track, AnalyticsEvent } from "@/lib/analytics/utils";
import {
  useChatSession,
  useSessionId,
  useHasSession,
  useIsRunning,
  useIsInterrupting,
  useWasInterrupted,
  useBuildSessionStore,
  useIsPreProvisioning,
  useIsPreProvisioningFailed,
  usePreProvisionedSessionId,
  useQueuedMessages,
  useViewedSubagentSessionId,
} from "@/app/craft/hooks/useBuildSessionStore";
import { useCraftStreaming } from "@/providers/CraftStreamingProvider";
import { useWakeOnIntent } from "@/app/craft/hooks/useWakeOnIntent";
import { BuildMessageAttachment } from "@/app/craft/types/streamingTypes";
import {
  BuildFile,
  UploadFileStatus,
  useUploadFilesContext,
  UploadFilesProvider,
} from "@/app/craft/contexts/UploadFilesContext";
import { CRAFT_SEARCH_PARAM_NAMES } from "@/app/craft/services/searchParams";
import { CRAFT_PATH } from "@/app/craft/v1/constants";
import { isScheduledRunContextInFlight } from "@/app/craft/v1/tasks/utils";
import { toast } from "@opal/layouts";
import Dropzone from "react-dropzone";
import CraftInputBar, {
  CraftInputBarHandle,
} from "@/app/craft/components/CraftInputBar";
import ModelPickerButton from "@/app/craft/components/ModelPickerButton";
import { useLanguageModels } from "@/lib/languageModels/hooks";
import {
  BuildLlmSelection,
  hasSupportedCraftProvider,
  resolveSessionLlmSelection,
} from "@/app/craft/onboarding/constants";
import { getPreferredLlmSelection } from "@/app/craft/utils/llmPreferences";
import { useUser } from "@/providers/UserProvider";
import ScheduledRunBanner, {
  useScheduledRunContext,
} from "@/app/craft/components/ScheduledRunBanner";
import BuildWelcome from "@/app/craft/components/BuildWelcome";
import BuildMessageList from "@/app/craft/components/BuildMessageList";
import LiveApprovalsRegion from "@/app/craft/components/approvals/LiveApprovalsRegion";
import AgentSwitcher from "@/app/craft/components/AgentSwitcher";
import SubagentView from "@/app/craft/components/SubagentView";
import SandboxStatusIndicator from "@/app/craft/components/SandboxStatusIndicator";
import SkillsStaleNotice from "@/app/craft/components/SkillsStaleNotice";
import { SvgSidebar, SvgChevronDown, SvgStopCircle } from "@opal/icons";
import { Button, MessageCard } from "@opal/components";
import { useBuildContext } from "@/app/craft/contexts/BuildContext";
import useScreenSize from "@/hooks/useScreenSize";
import { cn } from "@opal/utils";
import {
  motion,
  AnimatePresence,
  LayoutGroup,
  useReducedMotion,
} from "motion/react";

interface BuildChatPanelProps {
  /** Session ID from URL - used to prevent welcome flash while loading */
  existingSessionId?: string | null;
  headerControlWidth?: number;
  animateLayout?: boolean;
}

function toMessageAttachments(files: BuildFile[]): BuildMessageAttachment[] {
  return files.flatMap((file) =>
    file.status === UploadFileStatus.COMPLETED && file.path
      ? [
          {
            name: file.name,
            path: file.path,
            mimeType: file.file_type,
          },
        ]
      : []
  );
}

/**
 * BuildChatPanel - Center panel containing the chat interface
 *
 * Handles:
 * - Welcome state (no session)
 * - Message list (when session exists)
 * - Input bar at bottom
 * - Header with output panel toggle
 */
function ChatPanelContent({
  existingSessionId,
  headerControlWidth = 76,
  animateLayout = true,
}: BuildChatPanelProps) {
  const t = useTranslations("craft.chatPanel");
  const router = useRouter();
  const session = useChatSession();
  const sessionId = useSessionId();
  const scheduledSessionId = sessionId ?? existingSessionId ?? null;
  // Gate on origin so interactive sessions don't 404 on scheduled-run-context.
  const scheduledRunSessionId =
    session?.origin === "SCHEDULED" ? scheduledSessionId : null;
  const { data: scheduledRunContext, mutate: mutateScheduledRunContext } =
    useScheduledRunContext(scheduledRunSessionId);
  const scheduledRunInFlight =
    isScheduledRunContextInFlight(scheduledRunContext);
  const shouldStreamScheduledRun = scheduledRunContext?.status === "RUNNING";
  const scheduledRunId = scheduledRunContext?.run_id;
  const hasSession = useHasSession();
  const isRunning = useIsRunning();
  const displayIsRunning = isRunning || scheduledRunInFlight;
  const isRestoring: boolean =
    session?.status === "creating" &&
    !session.activeTurnLocalOwner &&
    !session.activeTurnId;
  const hasInterruptibleTurn =
    (session?.status === "running" || session?.status === "creating") &&
    (session.activeTurnId !== null || session.activeTurnLocalOwner);
  const wasInterrupted = useWasInterrupted();
  const { setLeftSidebarFolded, leftSidebarFolded, videoBackgroundEnabled } =
    useBuildContext();
  const { isMobile } = useScreenSize();
  const onWakeIntent = useWakeOnIntent();

  const { llmProviders, defaultText, defaultCraft } = useLanguageModels();
  // Sessions can outlive the org's supported providers — gate sends until one
  // exists (the model picker stays enabled so admins can connect from it).
  const hasProvider = hasSupportedCraftProvider(llmProviders);
  // Picker shows the session's stored model unless the user picks another.
  // The pick is keyed by session so it can't leak across sessions; only when
  // neither exists does the user's persisted preference (or the recommended
  // default) apply.
  const sessionModel = useMemo<BuildLlmSelection | null>(
    () =>
      resolveSessionLlmSelection(
        session?.agentProvider,
        session?.agentModel,
        llmProviders
      ),
    [session?.agentProvider, session?.agentModel, llmProviders]
  );
  const [modelBySession, setModelBySession] = useState<
    Record<string, BuildLlmSelection>
  >({});
  const { user } = useUser();
  const selectedModel = useMemo(
    () =>
      (sessionId ? modelBySession[sessionId] : undefined) ??
      sessionModel ??
      getPreferredLlmSelection(user?.id, llmProviders, [
        defaultCraft,
        defaultText,
      ]),
    [
      sessionId,
      modelBySession,
      sessionModel,
      user?.id,
      llmProviders,
      defaultCraft,
      defaultText,
    ]
  );

  const contextUsage = useMemo(() => {
    const usage = session?.contextUsage;
    if (!usage) return null;
    let limit: number | null = null;
    if (selectedModel) {
      const provider = llmProviders?.find(
        (candidate) => candidate.id === selectedModel.providerId
      );
      const config = provider?.model_configurations.find(
        (m) => m.name === selectedModel.modelName
      );
      limit = config?.max_input_tokens ?? null;
    }
    return {
      usedTokens: usage.usedTokens,
      contextLimit: limit,
    };
  }, [session?.contextUsage, selectedModel, llmProviders]);

  // Main-column view mode: chat (main agent) vs a subagent transcript.
  const viewedSubagentSessionId = useViewedSubagentSessionId();
  const isViewingSubagent = viewedSubagentSessionId !== null;
  const reduceMotion = useReducedMotion();

  // Access actions directly like chat does - these don't cause re-renders
  const consumePreProvisionedSession = useBuildSessionStore(
    (state) => state.consumePreProvisionedSession
  );
  const createSession = useBuildSessionStore((state) => state.createSession);
  const loadSession = useBuildSessionStore((state) => state.loadSession);
  const retryTurnSettlement = useBuildSessionStore(
    (state) => state.retryTurnSettlement
  );
  const appendMessageToCurrent = useBuildSessionStore(
    (state) => state.appendMessageToCurrent
  );
  const nameBuildSession = useBuildSessionStore(
    (state) => state.nameBuildSession
  );
  const {
    streamMessage,
    interruptStreaming,
    streamScheduledRunEvents,
    retryQueuedMessage,
  } = useCraftStreaming();
  const isInterrupting = useIsInterrupting();
  const sessionQueue = useQueuedMessages();
  const queuedMessages = useMemo(
    () => sessionQueue.filter((message) => message.phase !== "starting"),
    [sessionQueue]
  );
  const queuedSendError =
    !isRunning && !session?.activeTurnId && sessionQueue[0]?.phase === "failed"
      ? session?.error
      : null;
  const settlementError =
    session?.turnSettlement?.phase === "failed"
      ? (session.turnSettlement.error ?? t("settlementError.description"))
      : null;
  const submissionBlocked =
    (!!existingSessionId &&
      !session?.isLoaded &&
      !session?.activeTurnId &&
      !session?.activeTurnLocalOwner) ||
    session?.loadError != null ||
    session?.turnSettlement?.phase === "failed" ||
    sessionQueue[0]?.phase === "failed";
  const recoverableError =
    settlementError ?? queuedSendError ?? session?.loadError;
  const enqueueMessage = useBuildSessionStore((state) => state.enqueueMessage);
  const removeQueuedMessage = useBuildSessionStore(
    (state) => state.removeQueuedMessage
  );
  const activeTurnId = session?.activeTurnId ?? null;
  const nameSessionTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(
    null
  );
  const isPreProvisioning = useIsPreProvisioning();
  const isPreProvisioningFailed = useIsPreProvisioningFailed();
  const preProvisionedSessionId = usePreProvisionedSessionId();

  // Disable input when pre-provisioning is in progress or failed (waiting for retry)
  const sandboxNotReady = isPreProvisioning || isPreProvisioningFailed;
  const {
    currentMessageFiles,
    getCurrentMessageFiles,
    hasUploadingFiles,
    setActiveSession,
    uploadFiles,
  } = useUploadFilesContext();

  // URL sessions identify drafts; provisional sessions provide upload destinations.
  useEffect(() => {
    const activeSession = existingSessionId ?? preProvisionedSessionId ?? null;
    setActiveSession(activeSession, { draftId: existingSessionId ?? null });
  }, [existingSessionId, preProvisionedSessionId, setActiveSession]);

  useEffect(() => {
    if (!scheduledSessionId || !scheduledRunId || !shouldStreamScheduledRun)
      return;

    const controller = new AbortController();
    void streamScheduledRunEvents(
      scheduledSessionId,
      scheduledRunId,
      controller.signal,
      () => {
        void mutateScheduledRunContext();
      }
    );

    return () => controller.abort();
  }, [
    scheduledSessionId,
    scheduledRunId,
    shouldStreamScheduledRun,
    streamScheduledRunEvents,
    mutateScheduledRunContext,
  ]);

  useEffect(() => {
    if (
      !scheduledSessionId ||
      !scheduledRunContext ||
      scheduledRunInFlight ||
      activeTurnId
    ) {
      return;
    }
    const store = useBuildSessionStore.getState();
    const current = store.sessions.get(scheduledSessionId);
    if (current)
      void store.beginTurnSettlement(
        scheduledSessionId,
        { kind: "scheduled", runId: scheduledRunContext.run_id },
        current.turnGeneration
      );
  }, [
    scheduledSessionId,
    scheduledRunContext,
    scheduledRunInFlight,
    activeTurnId,
  ]);

  // Ref to access InputBar methods
  const inputBarRef = useRef<CraftInputBarHandle>(null);

  // Scroll detection for auto-scroll "magnet"
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const prevScrollTopRef = useRef(0);

  // Check if user is at bottom of scroll container
  const checkIfAtBottom = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return true;

    const scrollTop = container.scrollTop;
    const scrollHeight = container.scrollHeight;
    const clientHeight = container.clientHeight;
    const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
    const threshold = 32; // 2rem threshold

    return distanceFromBottom <= threshold;
  }, []);

  // Handle scroll events - only update state on user-initiated scrolling
  const handleScroll = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    const currentScrollTop = container.scrollTop;
    const prevScrollTop = prevScrollTopRef.current;
    const wasAtBottom = checkIfAtBottom();

    // Detect if user scrolled up (scrollTop decreased)
    // This distinguishes user scrolling from content growth
    const scrolledUp = currentScrollTop < prevScrollTop - 5; // 5px threshold

    // Only update state if user scrolled up (definitely user action)
    // If content grows and we're still at bottom, don't change state
    if (scrolledUp) {
      // User scrolled up - release auto-scroll magnet
      setIsAtBottom(wasAtBottom);
    } else if (wasAtBottom) {
      // We're at bottom - ensure button stays hidden (handles content growth)
      setIsAtBottom(true);
    }
    // If scrollTop increased but we're still at bottom, it's content growth - do nothing

    prevScrollTopRef.current = currentScrollTop;
  }, [checkIfAtBottom]);

  // Scroll to bottom and resume auto-scroll
  const scrollToBottom = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    // Use requestAnimationFrame to ensure we scroll after any layout changes
    requestAnimationFrame(() => {
      container.scrollTo({
        top: container.scrollHeight,
        behavior: reduceMotion ? "instant" : "smooth",
      });

      // Update state immediately
      setIsAtBottom(true);
    });
  }, [reduceMotion]);

  // Reset scroll state when session changes
  useEffect(() => {
    setIsAtBottom(true);
    prevScrollTopRef.current = 0;
  }, [sessionId]);

  const sendMessage = useCallback(
    async (
      message: string,
      attachments: BuildMessageAttachment[],
      modelOverride?: BuildLlmSelection | null
    ) => {
      if (submissionBlocked) return;
      if (scheduledRunInFlight) {
        toast.error(t("toast.scheduledRunWait"));
        return;
      }

      track(AnalyticsEvent.SENT_CRAFT_MESSAGE);

      const chosen = modelOverride ?? selectedModel;

      if (hasSession && sessionId) {
        // Existing session flow
        // Check if response is still streaming - show toast like main chat does
        if (isRunning) {
          toast.error(t("toast.operationWait"));
          return;
        }

        // Add user message to state
        appendMessageToCurrent({
          id: `msg-${Date.now()}`,
          type: "user",
          content: message,
          timestamp: new Date(),
          attachments,
        });
        // Stream the response
        await streamMessage(
          sessionId,
          message,
          modelOverride ?? modelBySession[sessionId] ?? null,
          attachments
        );
      } else {
        // New session flow - ALWAYS use pre-provisioned session
        const newSessionId = await consumePreProvisionedSession();

        if (!newSessionId) {
          // This should not happen if UI properly disables input until ready
          console.error("[ChatPanel] No pre-provisioned session available");
          toast.error(t("toast.sandboxWait"));
          return;
        }

        // Pre-provisioned session flow:
        // The backend session already exists (created during pre-provisioning).
        // Files were already uploaded immediately when attached to the pre-provisioned session.
        // Here we initialize the LOCAL Zustand store entry with the right state.
        // Handle files that weren't successfully uploaded yet
        // This handles edge cases where:
        // 1. File is still uploading when user sends message - wait for it
        // 2. File upload failed and needs retry
        // 3. File was attached but upload hasn't started yet

        // Wait for any in-flight uploads to complete (max 5 seconds)
        // Use ref to check current state during polling
        if (hasUploadingFiles) {
          const maxWaitMs = 5000;
          const checkIntervalMs = 100;
          let waited = 0;

          await new Promise<void>((resolve) => {
            const checkUploads = () => {
              // Read accepted uploads without waiting for a React render.
              const stillUploading = getCurrentMessageFiles().some(
                (f) => f.status === UploadFileStatus.UPLOADING
              );
              if (!stillUploading || waited >= maxWaitMs) {
                resolve();
              } else {
                waited += checkIntervalMs;
                setTimeout(checkUploads, checkIntervalMs);
              }
            };
            checkUploads();
          });
        }

        // Note: PENDING files are auto-uploaded by the context when session becomes available
        const userMessage = {
          id: `msg-${Date.now()}`,
          type: "user" as const,
          content: message,
          timestamp: new Date(),
          attachments,
        };
        // Initialize local state (NOT an API call - backend session already exists)
        // - status: "running" disables input immediately
        // - isLoaded: false allows loadSession to fetch sandbox info while preserving messages
        createSession(newSessionId, {
          messages: [userMessage],
          status: "running",
        });

        // Navigate to URL - session controller will set currentSessionId
        router.push(
          `${CRAFT_PATH}?${CRAFT_SEARCH_PARAM_NAMES.SESSION_ID}=${newSessionId}`
        );

        // Schedule naming after delay (message will be saved by then)
        // Note: Don't call refreshSessionHistory() here - it would overwrite the
        // optimistic update from consumePreProvisionedSession() before the message is saved
        if (nameSessionTimeoutRef.current !== null) {
          clearTimeout(nameSessionTimeoutRef.current);
        }
        // Session naming is a store action that must survive unmount. Firing
        // before the 1s save window would name against an unsaved message.
        // oxlint-disable-next-line react-doctor/effect-needs-cleanup
        nameSessionTimeoutRef.current = setTimeout(() => {
          nameSessionTimeoutRef.current = null;
          nameBuildSession(newSessionId);
        }, 1000);

        // Stream the response (uses session ID directly, not currentSessionId)
        await streamMessage(newSessionId, message, chosen, attachments);
      }
    },
    [
      hasSession,
      sessionId,
      isRunning,
      scheduledRunInFlight,
      submissionBlocked,
      appendMessageToCurrent,
      streamMessage,
      consumePreProvisionedSession,
      createSession,
      nameBuildSession,
      router,
      hasUploadingFiles,
      getCurrentMessageFiles,
      selectedModel,
      modelBySession,
      t,
    ]
  );

  const handleSubmit = useCallback(
    (
      message: string,
      files: BuildFile[],
      modelOverride?: BuildLlmSelection | null
    ) => sendMessage(message, toMessageAttachments(files), modelOverride),
    [sendMessage]
  );

  const handleInterrupt = useCallback(() => {
    if (sessionId) void interruptStreaming(sessionId);
  }, [sessionId, interruptStreaming]);

  const handleQueueMessage = useCallback(
    (text: string, files: BuildFile[]) => {
      return (
        !!sessionId &&
        enqueueMessage(
          sessionId,
          text,
          toMessageAttachments(files),
          modelBySession[sessionId] ?? null
        )
      );
    },
    [sessionId, enqueueMessage, modelBySession]
  );

  const handleRemoveQueuedMessage = useCallback(
    (index: number) => {
      const message = queuedMessages[index];
      if (sessionId && message) removeQueuedMessage(sessionId, message.id);
    },
    [sessionId, queuedMessages, removeQueuedMessage]
  );

  return (
    <LayoutGroup id="craft-chat">
      {/* Content wrapper - shrinks when output panel opens. Wrapped in a
          dropzone so files can be dropped anywhere in the chat area. */}
      {/* noPaste: the input bar already uploads pasted files itself. */}
      <Dropzone
        noClick
        noKeyboard
        noPaste
        onDrop={(accepted) => {
          if (accepted.length > 0) uploadFiles(accepted);
        }}
      >
        {({ getRootProps }) => (
          <div
            {...getRootProps()}
            className="flex flex-col h-full w-full outline-hidden"
          >
            {/* Chat header */}
            <div
              className={cn(
                "flex flex-row items-center justify-between gap-2 ps-4 py-3 h-[52px] relative overflow-visible",
                animateLayout &&
                  "transition-[padding-inline-end] duration-180 ease-out motion-reduce:transition-none"
              )}
              style={{ paddingInlineEnd: headerControlWidth || 16 }}
            >
              <div className="flex min-w-0 flex-row items-center gap-2 max-w-[75%]">
                {/* Mobile sidebar toggle - only show on mobile when sidebar is folded */}
                {isMobile && leftSidebarFolded && (
                  <Button
                    icon={SvgSidebar}
                    aria-label={t("openSidebar.ariaLabel")}
                    onClick={() => setLeftSidebarFolded(false)}
                    prominence="tertiary"
                    size="sm"
                  />
                )}
                <AgentSwitcher />
                <ScheduledRunBanner
                  sessionId={scheduledSessionId}
                  context={scheduledRunContext ?? null}
                />
              </div>
              <SandboxStatusIndicator />
              {/* Soft fade border at bottom */}
              {!videoBackgroundEnabled && (
                <div className="absolute bottom-0 start-0 end-0 h-10 bg-linear-to-b from-background-neutral-01 to-transparent pointer-events-none translate-y-full z-10" />
              )}
            </div>

            {/* Main content area — cross-fades when switching between the main
            agent and a subagent (keyed by the viewed agent). */}
            <div
              ref={scrollContainerRef}
              data-testid="craft-chat-scroll"
              onScroll={handleScroll}
              className="flex flex-col flex-1 min-h-0 overflow-y-scroll overflow-x-hidden [scrollbar-color:var(--border-02)_transparent] supports-[selector(::-webkit-scrollbar)]:[scrollbar-color:auto] [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-track]:bg-transparent [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-border-02 [&::-webkit-scrollbar-thumb:hover]:bg-border-03"
              style={{ scrollbarWidth: "auto" }}
            >
              <AnimatePresence mode="wait" initial={false}>
                <motion.div
                  key={viewedSubagentSessionId ?? "main"}
                  initial={reduceMotion ? false : { opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: -4 }}
                  transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
                  className="flex flex-col flex-1 shrink-0"
                >
                  {isViewingSubagent && viewedSubagentSessionId ? (
                    <SubagentView subagentSessionId={viewedSubagentSessionId} />
                  ) : !hasSession && !existingSessionId ? (
                    <BuildWelcome
                      onSubmit={handleSubmit}
                      isRunning={displayIsRunning}
                      sandboxInitializing={sandboxNotReady}
                    />
                  ) : (
                    <BuildMessageList
                      sessionId={sessionId ?? existingSessionId ?? null}
                      attachmentRefreshKey={session?.webappNeedsRefresh}
                      messages={session?.messages ?? []}
                      streamItems={session?.streamItems ?? []}
                      isStreaming={displayIsRunning}
                      autoScrollEnabled={isAtBottom}
                      scrollContainerRef={scrollContainerRef}
                      trailingAssistantSlot={
                        <>
                          {wasInterrupted && !displayIsRunning && (
                            <div className="flex items-center gap-2 text-sm text-text-03">
                              <SvgStopCircle className="size-4 shrink-0 stroke-text-03" />
                              <span>{t("responseStopped.label")}</span>
                            </div>
                          )}
                          <LiveApprovalsRegion
                            sessionId={sessionId ?? existingSessionId ?? null}
                          />
                        </>
                      }
                    />
                  )}
                </motion.div>
              </AnimatePresence>

              {/* Keep the composer inside the scroll viewport so its scrollbar spans the full height. */}
              {(hasSession || existingSessionId) && (
                <div
                  data-testid="craft-chat-composer"
                  className={cn(
                    "sticky bottom-0 z-10 shrink-0 px-4 pb-8 pt-4",
                    !videoBackgroundEnabled && "bg-background-neutral-01"
                  )}
                >
                  {/* Soft fade border at top */}
                  {!videoBackgroundEnabled && (
                    <div className="absolute top-0 start-0 end-0 h-12 bg-linear-to-t from-background-neutral-01 to-transparent pointer-events-none -translate-y-full" />
                  )}
                  <div
                    className="max-w-[720px] mx-auto"
                    onFocusCapture={onWakeIntent}
                    onKeyDownCapture={onWakeIntent}
                  >
                    {/* Scroll to bottom button - shown when user has scrolled away */}
                    {!isAtBottom && (
                      <div className="absolute -top-12 start-1/2 -translate-x-1/2 z-10">
                        <Button
                          icon={SvgChevronDown}
                          size="md"
                          prominence="secondary"
                          tooltip={t("scrollToBottom.label")}
                          aria-label={t("scrollToBottom.label")}
                          onClick={scrollToBottom}
                        />
                      </div>
                    )}
                    {recoverableError && scheduledSessionId && (
                      <div className="pb-2" role="alert">
                        <MessageCard
                          variant="error"
                          title={t(
                            settlementError
                              ? "settlementError.title"
                              : queuedSendError
                                ? "queuedSendError.title"
                                : "loadError.title"
                          )}
                          description={recoverableError}
                          rightChildren={
                            <Button
                              onClick={() => {
                                if (settlementError)
                                  void retryTurnSettlement(scheduledSessionId);
                                else if (queuedSendError)
                                  void retryQueuedMessage(scheduledSessionId);
                                else
                                  void loadSession(scheduledSessionId, {
                                    force: true,
                                  });
                              }}
                            >
                              {t("loadError.retry")}
                            </Button>
                          }
                        />
                      </div>
                    )}
                    {sessionId && session?.skillsStale && (
                      <div className="pb-2">
                        <SkillsStaleNotice
                          sessionId={sessionId}
                          turnActive={isRunning}
                        />
                      </div>
                    )}
                    {/* The selected model is sent with each message, so a
                  switch applies from the next turn. Subagent transcripts
                  cannot send, so they get no picker. */}
                    {session?.isLoaded && !isViewingSubagent && (
                      <div className="flex justify-end pb-2">
                        <ModelPickerButton
                          selection={selectedModel}
                          onChange={(model) => {
                            if (sessionId) {
                              setModelBySession((m) => ({
                                ...m,
                                [sessionId]: model,
                              }));
                            }
                          }}
                        />
                      </div>
                    )}
                    {/* The composer stays in view for subagents (layout consistency)
                  but is disabled — replying to subagents is not supported. */}
                    <motion.div
                      layoutId="craft-composer"
                      transition={{
                        duration: reduceMotion ? 0 : 0.25,
                        ease: "easeOut",
                      }}
                    >
                      <CraftInputBar
                        ref={inputBarRef}
                        onSubmit={handleSubmit}
                        isRunning={displayIsRunning}
                        isInterrupting={isInterrupting}
                        onInterrupt={
                          hasInterruptibleTurn && !scheduledRunInFlight
                            ? handleInterrupt
                            : undefined
                        }
                        disabled={
                          isViewingSubagent ||
                          isRestoring ||
                          submissionBlocked ||
                          scheduledRunInFlight ||
                          !hasProvider
                        }
                        placeholder={
                          isViewingSubagent
                            ? t("input.subagentPlaceholder")
                            : scheduledRunInFlight
                              ? t("input.scheduledRunPlaceholder")
                              : t("input.continuePlaceholder")
                        }
                        queuedMessages={queuedMessages}
                        onQueueMessage={handleQueueMessage}
                        onRemoveQueuedMessage={handleRemoveQueuedMessage}
                        contextUsage={contextUsage}
                      />
                    </motion.div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </Dropzone>
    </LayoutGroup>
  );
}

function BuildChatPanel(props: BuildChatPanelProps) {
  return (
    <UploadFilesProvider>
      <ChatPanelContent {...props} />
    </UploadFilesProvider>
  );
}

export default memo(BuildChatPanel);
