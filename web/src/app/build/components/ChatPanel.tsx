"use client";

import { useCallback, useState, useEffect, useRef, useMemo } from "react";
import { useRouter } from "next/navigation";
import {
  useSession,
  useSessionId,
  useHasSession,
  useIsRunning,
  useOutputPanelOpen,
  useToggleOutputPanel,
  useBuildSessionStore,
  useIsPreProvisioning,
  usePreProvisionedSessionId,
  useFollowupSuggestions,
  useSuggestionsLoading,
} from "@/app/build/hooks/useBuildSessionStore";
import { useBuildStreaming } from "@/app/build/hooks/useBuildStreaming";
import {
  BuildFile,
  UploadFileStatus,
  useUploadFilesContext,
} from "@/app/build/contexts/UploadFilesContext";
import { uploadFile } from "@/app/build/services/apiServices";
import { BUILD_SEARCH_PARAM_NAMES } from "@/app/build/services/searchParams";
import { usePopup } from "@/components/admin/connectors/Popup";
import InputBar, { InputBarHandle } from "@/app/build/components/InputBar";
import BuildWelcome from "@/app/build/components/BuildWelcome";
import BuildMessageList from "@/app/build/components/BuildMessageList";
import SuggestionBubbles from "@/app/build/components/SuggestionBubbles";
import ConnectorBannersRow from "@/app/build/components/ConnectorBannersRow";
import SandboxStatusIndicator from "@/app/build/components/SandboxStatusIndicator";
import IconButton from "@/refresh-components/buttons/IconButton";
import { SvgSidebar, SvgChevronDown } from "@opal/icons";
import { useBuildContext } from "@/app/build/contexts/BuildContext";
import useScreenSize from "@/hooks/useScreenSize";
import { cn } from "@/lib/utils";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";

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
  const { popup, setPopup } = usePopup();
  const outputPanelOpen = useOutputPanelOpen();
  const session = useSession();
  const sessionId = useSessionId();
  const hasSession = useHasSession();
  const isRunning = useIsRunning();
  const { setLeftSidebarFolded, leftSidebarFolded } = useBuildContext();
  const { isMobile } = useScreenSize();
  const toggleOutputPanel = useToggleOutputPanel();

  // Track when output panel is fully closed (after animation completes)
  // This prevents the "open panel" button from appearing during the close animation
  const [isOutputPanelFullyClosed, setIsOutputPanelFullyClosed] =
    useState(!outputPanelOpen);

  useEffect(() => {
    if (outputPanelOpen) {
      // Panel opening - immediately mark as not fully closed
      setIsOutputPanelFullyClosed(false);
    } else {
      // Panel closing - wait for 300ms animation to complete
      const timer = setTimeout(() => setIsOutputPanelFullyClosed(true), 300);
      return () => clearTimeout(timer);
    }
  }, [outputPanelOpen]);

  // Access actions directly like chat does - these don't cause re-renders
  const consumePreProvisionedSession = useBuildSessionStore(
    (state) => state.consumePreProvisionedSession
  );
  const createNewSession = useBuildSessionStore(
    (state) => state.createNewSession
  );
  const createSession = useBuildSessionStore((state) => state.createSession);
  const appendMessageToCurrent = useBuildSessionStore(
    (state) => state.appendMessageToCurrent
  );
  const appendMessageToSession = useBuildSessionStore(
    (state) => state.appendMessageToSession
  );
  const nameBuildSession = useBuildSessionStore(
    (state) => state.nameBuildSession
  );
  const { streamMessage } = useBuildStreaming();
  const isPreProvisioning = useIsPreProvisioning();
  const preProvisionedSessionId = usePreProvisionedSessionId();
  const { currentMessageFiles, hasUploadingFiles } = useUploadFilesContext();
  const followupSuggestions = useFollowupSuggestions();
  const suggestionsLoading = useSuggestionsLoading();
  const clearFollowupSuggestions = useBuildSessionStore(
    (state) => state.clearFollowupSuggestions
  );

  // Ref to access current file state in async callbacks
  const currentFilesRef = useRef(currentMessageFiles);
  useEffect(() => {
    currentFilesRef.current = currentMessageFiles;
  }, [currentMessageFiles]);

  // Ref to access InputBar methods
  const inputBarRef = useRef<InputBarHandle>(null);

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

  // Handle suggestion bubble click - populate InputBar with the suggestion
  const handleSuggestionSelect = useCallback((text: string) => {
    inputBarRef.current?.setMessage(text);
  }, []);

  // Check if assistant has finished streaming at least one message
  // Show banner only after first assistant message completes streaming
  const shouldShowConnectorBanner = useMemo(() => {
    // Don't show if currently streaming
    if (isRunning) {
      return false;
    }
    // Check if there's at least one assistant message in the session
    const hasAssistantMessage = session?.messages?.some(
      (msg) => msg.type === "assistant"
    );
    return hasAssistantMessage ?? false;
  }, [isRunning, session?.messages]);

  const handleSubmit = useCallback(
    async (message: string, files: BuildFile[], demoDataEnabled: boolean) => {
      if (hasSession && sessionId) {
        // Existing session flow
        // Check if response is still streaming - show toast like main chat does
        if (isRunning) {
          setPopup({
            message: "Please wait for the current operation to complete.",
            type: "error",
          });
          return;
        }

        // Clear follow-up suggestions when user sends a new message
        clearFollowupSuggestions(sessionId);

        // Add user message to state
        appendMessageToCurrent({
          id: `msg-${Date.now()}`,
          type: "user",
          content: message,
          timestamp: new Date(),
        });
        // Stream the response
        await streamMessage(sessionId, message);
      } else {
        // New session flow - get pre-provisioned session or fall back to creating new one
        const newSessionId = await consumePreProvisionedSession();

        if (!newSessionId) {
          // Fallback: createNewSession handles everything including navigation
          const fallbackSessionId = await createNewSession(message);
          if (fallbackSessionId) {
            // Upload files that weren't already uploaded (no path means not yet uploaded)
            const filesToUpload = files.filter((f) => f.file && !f.path);
            if (filesToUpload.length > 0) {
              await Promise.all(
                filesToUpload.map((f) => uploadFile(fallbackSessionId, f.file!))
              );
            }
            await streamMessage(fallbackSessionId, message);
          }
        } else {
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

          // Fallback: Handle files that weren't successfully uploaded yet
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

          // Upload any files that need to be uploaded:
          // - PENDING: Was attached before session existed, needs upload now
          // - FAILED: Previous upload failed, retry
          // - No path + not currently uploading: Edge case fallback
          const currentFiles = currentFilesRef.current;
          const filesToUpload = currentFiles.filter(
            (f) =>
              f.file &&
              (f.status === UploadFileStatus.PENDING ||
                f.status === UploadFileStatus.FAILED ||
                (!f.path && f.status !== UploadFileStatus.UPLOADING))
          );
          if (filesToUpload.length > 0) {
            await Promise.all(
              filesToUpload.map((f) => uploadFile(newSessionId, f.file!))
            );
          }

          // Navigate to URL - session controller will set currentSessionId
          router.push(
            `/build/v1?${BUILD_SEARCH_PARAM_NAMES.SESSION_ID}=${newSessionId}`
          );

          // Schedule naming after delay (message will be saved by then)
          // Note: Don't call refreshSessionHistory() here - it would overwrite the
          // optimistic update from consumePreProvisionedSession() before the message is saved
          setTimeout(() => nameBuildSession(newSessionId), 500);

          // Stream the response (uses session ID directly, not currentSessionId)
          await streamMessage(newSessionId, message);
        }
      }
    },
    [
      hasSession,
      sessionId,
      isRunning,
      setPopup,
      appendMessageToCurrent,
      streamMessage,
      consumePreProvisionedSession,
      createNewSession,
      createSession,
      appendMessageToSession,
      nameBuildSession,
      router,
      clearFollowupSuggestions,
    ]
  );

  return (
    <div className="h-full w-full">
      {popup}
      {/* Content wrapper - shrinks when output panel opens */}
      <div
        className={cn(
          "flex flex-col h-full transition-all duration-300 ease-in-out",
          outputPanelOpen ? "w-1/2 pl-4" : "w-full"
        )}
      >
        {/* Chat header */}
        <div className="flex flex-row items-center justify-between pl-4 pr-4 py-3 relative overflow-visible max-w-[75%]">
          <div className="flex flex-row items-center gap-2">
            {/* Mobile sidebar toggle - only show on mobile when sidebar is folded */}
            {isMobile && leftSidebarFolded && (
              <IconButton
                icon={SvgSidebar}
                onClick={() => setLeftSidebarFolded(false)}
                internal
              />
            )}
            <SandboxStatusIndicator />
          </div>
          {/* Output panel toggle - only show when panel is fully closed (after animation) */}
          {isOutputPanelFullyClosed && (
            <IconButton
              icon={SvgSidebar}
              onClick={toggleOutputPanel}
              tooltip="Open output panel"
              tertiary
              className="!bg-background-tint-00 border rounded-full"
              iconClassName="!stroke-text-04"
            />
          )}
          {/* Soft fade border at bottom */}
          <div className="absolute bottom-0 left-0 right-0 h-10 bg-gradient-to-b from-background-neutral-01 to-transparent pointer-events-none translate-y-full z-10" />
        </div>

        {/* Main content area */}
        <div
          ref={scrollContainerRef}
          onScroll={handleScroll}
          className="flex-1 overflow-auto"
        >
          {!hasSession && !existingSessionId ? (
            <BuildWelcome
              onSubmit={handleSubmit}
              isRunning={isRunning}
              sandboxInitializing={isPreProvisioning}
              preProvisionedSessionId={preProvisionedSessionId}
            />
          ) : (
            <BuildMessageList
              messages={session?.messages ?? []}
              streamItems={session?.streamItems ?? []}
              isStreaming={isRunning}
              autoScrollEnabled={isAtBottom}
            />
          )}
        </div>

        {/* Input bar at bottom when session exists */}
        {(hasSession || existingSessionId) && (
          <div className="px-4 pb-8 pt-4 relative">
            {/* Soft fade border at top */}
            <div className="absolute top-0 left-0 right-0 h-12 bg-gradient-to-t from-background-neutral-01 to-transparent pointer-events-none -translate-y-full" />
            <div className="max-w-2xl mx-auto">
              {/* Scroll to bottom button - shown when user has scrolled away */}
              {showScrollButton && (
                <div className="absolute -top-12 left-1/2 -translate-x-1/2 z-10">
                  <SimpleTooltip tooltip="Scroll to bottom" delayDuration={200}>
                    <button
                      onClick={scrollToBottom}
                      className={cn(
                        "flex items-center justify-center",
                        "w-8 h-8 rounded-full",
                        "bg-background-neutral-inverted-00 border border-border-01",
                        "shadow-01 hover:shadow-02",
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
                  </SimpleTooltip>
                </div>
              )}
              {/* Follow-up suggestion bubbles - show after first assistant message */}
              {(followupSuggestions || suggestionsLoading) && (
                <div className="mb-3">
                  <SuggestionBubbles
                    suggestions={followupSuggestions ?? []}
                    loading={suggestionsLoading}
                    onSelect={handleSuggestionSelect}
                  />
                </div>
              )}
              {/* Connector banners - show after first assistant message finishes streaming */}
              {shouldShowConnectorBanner && (
                <ConnectorBannersRow className="" />
              )}
              <InputBar
                ref={inputBarRef}
                onSubmit={handleSubmit}
                isRunning={isRunning}
                placeholder="Continue the conversation..."
                sessionId={sessionId ?? undefined}
                preProvisionedSessionId={preProvisionedSessionId}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
