"use client";

import { useCallback, useMemo, useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { track, AnalyticsEvent } from "@/lib/analytics/utils";
import {
  useSession,
  useSessionId,
  useHasSession,
  useIsRunning,
  useIsInterrupting,
  useWasInterrupted,
  useOutputPanelOpen,
  useToggleOutputPanel,
  useBuildSessionStore,
  useIsPreProvisioning,
  useIsPreProvisioningFailed,
  usePreProvisionedSessionId,
  useQueuedMessages,
  useViewedSubagentSessionId,
} from "@/app/craft/hooks/useBuildSessionStore";
import { useBuildStreaming } from "@/app/craft/hooks/useBuildStreaming";
import { useUsageLimits } from "@/app/craft/hooks/useUsageLimits";
import { SessionErrorCode } from "@/app/craft/types/streamingTypes";
import {
  BuildFile,
  UploadFileStatus,
  useUploadFilesContext,
} from "@/app/craft/contexts/UploadFilesContext";
import { CRAFT_SEARCH_PARAM_NAMES } from "@/app/craft/services/searchParams";
import { CRAFT_PATH } from "@/app/craft/v1/constants";
import { isScheduledRunContextInFlight } from "@/app/craft/v1/tasks/utils";
import { toast } from "@/hooks/useToast";
import Dropzone from "react-dropzone";
import CraftInputBar, {
  CraftInputBarHandle,
} from "@/app/craft/components/CraftInputBar";
import ModelPickerButton from "@/app/craft/components/ModelPickerButton";
import { useLLMProviders } from "@/lib/languageModels/hooks";
import { BuildLlmSelection } from "@/app/craft/onboarding/constants";
import ScheduledRunBanner, {
  useScheduledRunContext,
} from "@/app/craft/components/ScheduledRunBanner";
import BuildWelcome from "@/app/craft/components/BuildWelcome";
import BuildMessageList from "@/app/craft/components/BuildMessageList";
import LiveApprovalsRegion from "@/app/craft/components/approvals/LiveApprovalsRegion";
import AgentSwitcher from "@/app/craft/components/AgentSwitcher";
import SubagentView from "@/app/craft/components/SubagentView";
import SandboxStatusIndicator from "@/app/craft/components/SandboxStatusIndicator";
import UpgradePlanModal from "@/app/craft/components/UpgradePlanModal";
import IconButton from "@/refresh-components/buttons/IconButton";
import { SvgSidebar, SvgChevronDown, SvgStopCircle } from "@opal/icons";
import { Button as OpalButton, Tooltip } from "@opal/components";
import { useBuildContext } from "@/app/craft/contexts/BuildContext";
import useScreenSize from "@/hooks/useScreenSize";
import { cn } from "@opal/utils";
import { motion, AnimatePresence, useReducedMotion } from "motion/react";

interface BuildChatPanelProps {
  /** Session ID from URL - used to prevent welcome flash while loading */
  existingSessionId?: string | null;
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
export default function BuildChatPanel({
  existingSessionId,
}: BuildChatPanelProps) {
  const router = useRouter();
  const outputPanelOpen = useOutputPanelOpen();
  const session = useSession();
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
  const hasSession = useHasSession();
  const isRunning = useIsRunning();
  const displayIsRunning = isRunning || scheduledRunInFlight;
  const wasInterrupted = useWasInterrupted();
  const { setLeftSidebarFolded, leftSidebarFolded, videoBackgroundEnabled } =
    useBuildContext();
  const { isMobile } = useScreenSize();
  const toggleOutputPanel = useToggleOutputPanel();

  const { llmProviders } = useLLMProviders();
  // Picker shows the session's stored model unless the user picks another.
  // The pick is keyed by session so it can't leak across sessions.
  const sessionModel = useMemo<BuildLlmSelection | null>(() => {
    if (!session?.agentProvider || !session?.agentModel) return null;
    const match = llmProviders?.find(
      (p) => p.provider === session.agentProvider
    );
    return {
      provider: session.agentProvider,
      providerName: match?.name ?? session.agentProvider,
      modelName: session.agentModel,
    };
  }, [session?.agentProvider, session?.agentModel, llmProviders]);
  const [modelBySession, setModelBySession] = useState<
    Record<string, BuildLlmSelection>
  >({});
  const selectedModel =
    (sessionId ? modelBySession[sessionId] : undefined) ?? sessionModel;

  const contextUsage = useMemo(() => {
    const usage = session?.contextUsage;
    if (!usage) return null;
    let limit: number | null = null;
    if (selectedModel) {
      const provider = llmProviders?.find(
        (p) => p.provider === selectedModel.provider
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

  const { limits, refreshLimits } = useUsageLimits();
  const [showUpgradeModal, setShowUpgradeModal] = useState(false);
  const updateSessionData = useBuildSessionStore(
    (state) => state.updateSessionData
  );
  const setCurrentError = useBuildSessionStore(
    (state) => state.setCurrentError
  );

  useEffect(() => {
    if (session?.error === SessionErrorCode.RATE_LIMIT_EXCEEDED) {
      setShowUpgradeModal(true);
      setCurrentError(null);
      refreshLimits();
    }
  }, [session?.error, refreshLimits, setCurrentError]);

  // Access actions directly like chat does - these don't cause re-renders
  const consumePreProvisionedSession = useBuildSessionStore(
    (state) => state.consumePreProvisionedSession
  );
  const createSession = useBuildSessionStore((state) => state.createSession);
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
    streamTurnEvents,
  } = useBuildStreaming();
  const isInterrupting = useIsInterrupting();
  const queuedMessages = useQueuedMessages();
  const enqueueMessage = useBuildSessionStore((state) => state.enqueueMessage);
  const removeQueuedMessage = useBuildSessionStore(
    (state) => state.removeQueuedMessage
  );
  const attachedTurnRef = useRef<{
    turnId: string;
    controller: AbortController;
  } | null>(null);
  const attachCleanupTimerRef = useRef<{
    turnId: string;
    timer: ReturnType<typeof setTimeout>;
  } | null>(null);
  const isPreProvisioning = useIsPreProvisioning();
  const isPreProvisioningFailed = useIsPreProvisioningFailed();
  const preProvisionedSessionId = usePreProvisionedSessionId();

  // Disable input when pre-provisioning is in progress or failed (waiting for retry)
  const sandboxNotReady = isPreProvisioning || isPreProvisioningFailed;
  const {
    currentMessageFiles,
    hasUploadingFiles,
    setActiveSession,
    uploadFiles,
  } = useUploadFilesContext();

  // Ref to access current file state in async callbacks
  const currentFilesRef = useRef(currentMessageFiles);
  useEffect(() => {
    currentFilesRef.current = currentMessageFiles;
  }, [currentMessageFiles]);

  /**
   * Keep the upload context in sync with the active session.
   * The context handles all session change logic internally (fetching attachments,
   * clearing files, auto-uploading pending files).
   */
  useEffect(() => {
    const activeSession = existingSessionId ?? preProvisionedSessionId ?? null;
    setActiveSession(activeSession);
  }, [existingSessionId, preProvisionedSessionId, setActiveSession]);

  const maybeAutoOpenPanelForPreview = useBuildSessionStore(
    (s) => s.maybeAutoOpenPanelForPreview
  );

  // Auto-open the panel the first time webappUrl becomes non-null this session.
  const prevWebappUrlRef = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    const prev = prevWebappUrlRef.current;
    const current = session?.webappUrl ?? null;
    if (prev === null && current !== null && sessionId) {
      maybeAutoOpenPanelForPreview(sessionId);
    }
    prevWebappUrlRef.current = current;
  }, [session?.webappUrl, sessionId, maybeAutoOpenPanelForPreview]);

  useEffect(() => {
    if (!scheduledSessionId || !shouldStreamScheduledRun) return;

    const controller = new AbortController();
    void streamScheduledRunEvents(scheduledSessionId, controller.signal, () => {
      void mutateScheduledRunContext();
    });

    return () => controller.abort();
  }, [
    scheduledSessionId,
    shouldStreamScheduledRun,
    streamScheduledRunEvents,
    mutateScheduledRunContext,
  ]);

  const activeTurnId = session?.activeTurnId ?? null;
  const activeTurnLocalOwner = session?.activeTurnLocalOwner ?? false;
  useEffect(() => {
    const pendingCleanup = attachCleanupTimerRef.current;
    if (pendingCleanup?.turnId === activeTurnId) {
      clearTimeout(pendingCleanup.timer);
      attachCleanupTimerRef.current = null;
    }

    if (
      !scheduledSessionId ||
      !activeTurnId ||
      activeTurnLocalOwner ||
      scheduledRunInFlight
    ) {
      return;
    }

    const scheduleCleanup = (attachment: {
      turnId: string;
      controller: AbortController;
    }) => {
      attachCleanupTimerRef.current = {
        turnId: attachment.turnId,
        timer: setTimeout(() => {
          attachment.controller.abort();
          if (attachedTurnRef.current === attachment) {
            attachedTurnRef.current = null;
          }
          if (attachCleanupTimerRef.current?.turnId === attachment.turnId) {
            attachCleanupTimerRef.current = null;
          }
        }, 0),
      };
    };

    const existingAttachment = attachedTurnRef.current;
    if (existingAttachment?.turnId === activeTurnId) {
      return () => scheduleCleanup(existingAttachment);
    }

    existingAttachment?.controller.abort();
    const controller = new AbortController();
    const attachment = { turnId: activeTurnId, controller };
    attachedTurnRef.current = attachment;
    void streamTurnEvents(
      scheduledSessionId,
      activeTurnId,
      controller.signal,
      () => {
        if (attachedTurnRef.current === attachment) {
          attachedTurnRef.current = null;
        }
      }
    );

    return () => scheduleCleanup(attachment);
  }, [
    scheduledSessionId,
    activeTurnId,
    activeTurnLocalOwner,
    scheduledRunInFlight,
    streamTurnEvents,
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
    updateSessionData(scheduledSessionId, { status: "active" });
  }, [
    scheduledSessionId,
    scheduledRunContext,
    scheduledRunInFlight,
    activeTurnId,
    updateSessionData,
  ]);

  // Ref to access InputBar methods
  const inputBarRef = useRef<CraftInputBarHandle>(null);

  // Scroll detection for auto-scroll "magnet"
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [showScrollButton, setShowScrollButton] = useState(false);
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
      setShowScrollButton(!wasAtBottom);
    } else if (wasAtBottom) {
      // We're at bottom - ensure button stays hidden (handles content growth)
      setIsAtBottom(true);
      setShowScrollButton(false);
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
      if (!container) return;

      // Scroll to a value larger than scrollHeight - browsers will clamp to max
      // This ensures we always reach the absolute bottom
      const targetScroll = container.scrollHeight + 1000; // Add buffer to ensure we go all the way
      container.scrollTo({ top: targetScroll, behavior: "smooth" });

      // Update state immediately
      setIsAtBottom(true);
      setShowScrollButton(false);

      // Update prevScrollTopRef after scroll completes
      setTimeout(() => {
        if (container) {
          prevScrollTopRef.current = container.scrollTop;
        }
      }, 600); // Smooth scroll animation duration
    });
  }, []);

  // Reset scroll state when session changes
  useEffect(() => {
    setIsAtBottom(true);
    setShowScrollButton(false);
  }, [sessionId]);

  const handleSubmit = useCallback(
    async (
      message: string,
      files: BuildFile[],
      modelOverride?: BuildLlmSelection | null
    ) => {
      if (limits?.isLimited) {
        setShowUpgradeModal(true);
        return;
      }

      if (scheduledRunInFlight) {
        toast.error("Please wait for the scheduled run to finish.");
        return;
      }

      track(AnalyticsEvent.SENT_CRAFT_MESSAGE);

      const chosen = modelOverride ?? selectedModel;
      const model = chosen
        ? { provider: chosen.provider, modelName: chosen.modelName }
        : null;

      if (hasSession && sessionId) {
        // Existing session flow
        // Check if response is still streaming - show toast like main chat does
        if (isRunning) {
          toast.error("Please wait for the current operation to complete.");
          return;
        }

        // Add user message to state
        appendMessageToCurrent({
          id: `msg-${Date.now()}`,
          type: "user",
          content: message,
          timestamp: new Date(),
        });
        // Stream the response
        await streamMessage(sessionId, message, model);
        refreshLimits();
      } else {
        // New session flow - ALWAYS use pre-provisioned session
        const newSessionId = await consumePreProvisionedSession();

        if (!newSessionId) {
          // This should not happen if UI properly disables input until ready
          console.error("[ChatPanel] No pre-provisioned session available");
          toast.error("Please wait for sandbox to initialize");
          return;
        }

        // Pre-provisioned session flow:
        // The backend session already exists (created during pre-provisioning).
        // Files were already uploaded immediately when attached to the pre-provisioned session.
        // Here we initialize the LOCAL Zustand store entry with the right state.
        const userMessage = {
          id: `msg-${Date.now()}`,
          type: "user" as const,
          content: message,
          timestamp: new Date(),
        };
        // Initialize local state (NOT an API call - backend session already exists)
        // - status: "running" disables input immediately
        // - isLoaded: false allows loadSession to fetch sandbox info while preserving messages
        createSession(newSessionId, {
          messages: [userMessage],
          status: "running",
        });

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
              // Check current state via ref (updates with each render)
              const stillUploading = currentFilesRef.current.some(
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

        // Navigate to URL - session controller will set currentSessionId
        router.push(
          `${CRAFT_PATH}?${CRAFT_SEARCH_PARAM_NAMES.SESSION_ID}=${newSessionId}`
        );

        // Schedule naming after delay (message will be saved by then)
        // Note: Don't call refreshSessionHistory() here - it would overwrite the
        // optimistic update from consumePreProvisionedSession() before the message is saved
        setTimeout(() => nameBuildSession(newSessionId), 1000);

        // Stream the response (uses session ID directly, not currentSessionId)
        await streamMessage(newSessionId, message, model);
        refreshLimits();
      }
    },
    [
      hasSession,
      sessionId,
      isRunning,
      scheduledRunInFlight,
      appendMessageToCurrent,
      streamMessage,
      consumePreProvisionedSession,
      createSession,
      nameBuildSession,
      router,
      hasUploadingFiles,
      limits,
      refreshLimits,
      selectedModel,
    ]
  );

  const handleInterrupt = useCallback(() => {
    if (sessionId) void interruptStreaming(sessionId);
  }, [sessionId, interruptStreaming]);

  const handleQueueMessage = useCallback(
    (text: string) => {
      if (sessionId) enqueueMessage(sessionId, text);
    },
    [sessionId, enqueueMessage]
  );

  const handleRemoveQueuedMessage = useCallback(
    (index: number) => {
      if (sessionId) removeQueuedMessage(sessionId, index);
    },
    [sessionId, removeQueuedMessage]
  );

  // Auto-send the next queued message FIFO after a run cleanly succeeds (each
  // send re-arms this for the message after). Only fire on a clean completion
  // and when the send is actually eligible — otherwise we'd dequeue a message
  // that a failed/rate-limited run never sends, silently dropping it. The
  // sessionId guard avoids mistaking a session switch for a run completion.
  const sessionStatus = session?.status;
  const sessionError = session?.error;
  const isLimited = limits?.isLimited ?? false;
  const prevIsRunningRef = useRef(isRunning);
  const prevSessionIdRef = useRef(sessionId);
  useEffect(() => {
    const wasRunning = prevIsRunningRef.current;
    const prevSessionId = prevSessionIdRef.current;
    prevIsRunningRef.current = isRunning;
    prevSessionIdRef.current = sessionId;

    const runSucceeded =
      wasRunning &&
      !isRunning &&
      sessionId === prevSessionId &&
      sessionStatus === "active" &&
      !sessionError &&
      !isLimited;
    if (runSucceeded && sessionId && queuedMessages.length > 0) {
      const next = queuedMessages[0];
      if (next) {
        removeQueuedMessage(sessionId, 0);
        void handleSubmit(next.text, []);
      }
    }
  }, [
    isRunning,
    sessionId,
    sessionStatus,
    sessionError,
    isLimited,
    queuedMessages,
    handleSubmit,
    removeQueuedMessage,
  ]);

  return (
    <div className="h-full w-full">
      <UpgradePlanModal
        open={showUpgradeModal}
        onClose={() => setShowUpgradeModal(false)}
        limits={limits}
      />
      {/* Content wrapper - shrinks when output panel opens. Wrapped in a
          dropzone so files can be dropped anywhere in the chat area. */}
      <Dropzone
        noClick
        noKeyboard
        onDrop={(accepted) => {
          if (accepted.length > 0) uploadFiles(accepted);
        }}
      >
        {({ getRootProps }) => (
          <div
            {...getRootProps()}
            className={cn(
              "flex flex-col h-full transition-all duration-300 ease-in-out outline-hidden",
              outputPanelOpen ? "w-1/2 pl-4" : "w-full"
            )}
          >
            {/* Chat header */}
            <div className="flex flex-row items-center justify-between pl-4 pr-4 py-3 relative overflow-visible">
              <div className="flex min-w-0 flex-row items-center gap-2 max-w-[75%]">
                {/* Mobile sidebar toggle - only show on mobile when sidebar is folded */}
                {isMobile && leftSidebarFolded && (
                  <OpalButton
                    icon={SvgSidebar}
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
              {/* Right cluster: sandbox status sits left of the panel toggle. The
              toggle stays pinned to the right edge, so the status chip's width
              changes grow leftward into empty space without shifting anything. */}
              <div className="flex flex-row items-center gap-2 shrink-0">
                <SandboxStatusIndicator />
                {/* Output panel toggle — same icon for open and close */}
                {/* TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved */}
                <IconButton
                  icon={SvgSidebar}
                  onClick={toggleOutputPanel}
                  tooltip={
                    outputPanelOpen ? "Close output panel" : "Open output panel"
                  }
                  tertiary
                  className={cn(
                    "border rounded-full p-2.5!",
                    outputPanelOpen
                      ? "bg-background-tint-02!"
                      : "bg-background-tint-00!"
                  )}
                  iconClassName="stroke-text-04! h-5! w-5!"
                />
              </div>
              {/* Soft fade border at bottom */}
              {!videoBackgroundEnabled && (
                <div className="absolute bottom-0 left-0 right-0 h-10 bg-linear-to-b from-background-neutral-01 to-transparent pointer-events-none translate-y-full z-10" />
              )}
            </div>

            {/* Main content area — cross-fades when switching between the main
            agent and a subagent (keyed by the viewed agent). */}
            <div
              ref={scrollContainerRef}
              onScroll={handleScroll}
              className="flex flex-col flex-1 min-h-0 overflow-auto"
            >
              <AnimatePresence mode="wait" initial={false}>
                <motion.div
                  key={viewedSubagentSessionId ?? "main"}
                  initial={reduceMotion ? false : { opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: -4 }}
                  transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
                  className="flex flex-col flex-1"
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
                              <span>Response stopped</span>
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
            </div>

            {/* Input bar at bottom when session exists. */}
            {(hasSession || existingSessionId) && (
              <div className="px-4 pb-8 pt-4 relative">
                {/* Soft fade border at top */}
                {!videoBackgroundEnabled && (
                  <div className="absolute top-0 left-0 right-0 h-12 bg-linear-to-t from-background-neutral-01 to-transparent pointer-events-none -translate-y-full" />
                )}
                <div className="max-w-[720px] mx-auto">
                  {/* Scroll to bottom button - shown when user has scrolled away */}
                  {showScrollButton && (
                    <div className="absolute -top-12 left-1/2 -translate-x-1/2 z-10">
                      <Tooltip tooltip="Scroll to bottom" delayDuration={200}>
                        <button
                          onClick={scrollToBottom}
                          className={cn(
                            "flex items-center justify-center",
                            "w-8 h-8 rounded-full",
                            "bg-background-neutral-inverted-00 border border-border-01",
                            "shadow-box-01 hover:shadow-box-02",
                            "transition-all duration-200",
                            "hover:bg-background-tint-inverted-01"
                          )}
                          aria-label="Scroll to bottom"
                        >
                          <SvgChevronDown
                            size={20}
                            className="stroke-background-neutral-00"
                          />
                        </button>
                      </Tooltip>
                    </div>
                  )}
                  {/* Model is locked once the session starts — show the picker
                  only before the first message. */}
                  {session?.isLoaded && session.messages.length === 0 && (
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
                        disabled={isViewingSubagent}
                      />
                    </div>
                  )}
                  {/* The composer stays in view for subagents (layout consistency)
                  but is disabled — replying to subagents is not supported. */}
                  <CraftInputBar
                    ref={inputBarRef}
                    onSubmit={handleSubmit}
                    isRunning={displayIsRunning}
                    isInterrupting={isInterrupting}
                    onInterrupt={
                      scheduledRunInFlight ? undefined : handleInterrupt
                    }
                    disabled={isViewingSubagent || scheduledRunInFlight}
                    placeholder={
                      isViewingSubagent
                        ? "Switch to the main agent to send a message"
                        : scheduledRunInFlight
                          ? "Scheduled run in progress..."
                          : "Continue the conversation..."
                    }
                    queuedMessages={queuedMessages}
                    onQueueMessage={handleQueueMessage}
                    onRemoveQueuedMessage={handleRemoveQueuedMessage}
                    contextUsage={contextUsage}
                  />
                </div>
              </div>
            )}
          </div>
        )}
      </Dropzone>
    </div>
  );
}
