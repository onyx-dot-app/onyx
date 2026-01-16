"use client";

import React, {
  ForwardedRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import { Message } from "@/app/chat/interfaces";
import { OnyxDocument, MinimalOnyxDocument } from "@/lib/search/interfaces";
import HumanMessage from "@/app/chat/message/HumanMessage";
import { ErrorBanner } from "@/app/chat/message/Resubmit";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { LlmDescriptor, LlmManager } from "@/lib/hooks";
import AIMessage from "@/app/chat/message/messageComponents/AIMessage";
import { ProjectFile } from "@/app/chat/projects/projectsService";
import { useScrollonStream } from "@/app/chat/services/lib";
import useScreenSize from "@/hooks/useScreenSize";
import {
  useCurrentChatState,
  useCurrentMessageHistory,
  useCurrentMessageTree,
  useLoadingError,
  useUncaughtError,
} from "@/app/chat/stores/useChatSessionStore";
import useChatSessions from "@/hooks/useChatSessions";
import { useUser } from "@/components/user/UserProvider";
import { cn } from "@/lib/utils";
import Spacer from "@/refresh-components/Spacer";

// Size constants (1rem = 16px)
const MESSAGE_TOP_OFFSET_PX = 16; // 1rem - gap between viewport top and new message
const SCROLL_DEBOUNCE_MS = 100;
const FADE_GRADIENT_THRESHOLD_PX = 80; // 5rem - scroll distance for fade to appear
const FADE_OVERLAY_HEIGHT = "h-8"; // 2rem
const SCROLL_BUTTON_THRESHOLD_PX = 32; // 2rem - scroll distance for button to appear

const FadeOverlay = React.memo(
  ({ show, position }: { show: boolean; position: "top" | "bottom" }) => {
    if (!show) return null;
    const isTop = position === "top";
    return (
      <div
        aria-label={isTop ? "Top fade overlay" : "Bottom fade overlay"}
        className={cn(
          `absolute left-0 right-0 ${FADE_OVERLAY_HEIGHT} z-sticky pointer-events-none`,
          isTop ? "top-0" : "bottom-0"
        )}
        style={{
          background: `linear-gradient(${
            isTop ? "to bottom" : "to top"
          }, var(--background-tint-01) 0%, transparent 100%)`,
        }}
      />
    );
  }
);
FadeOverlay.displayName = "FadeOverlay";

export interface ChatUIHandle {
  scrollToBottom: () => boolean;
}

export interface ChatUIProps {
  liveAssistant: MinimalPersonaSnapshot | undefined;
  llmManager: LlmManager;
  currentMessageFiles: ProjectFile[];
  deepResearchEnabled: boolean;
  setPresentingDocument: (doc: MinimalOnyxDocument | null) => void;
  onSubmit: (args: {
    message: string;
    messageIdToResend?: number;
    currentMessageFiles: ProjectFile[];
    deepResearch: boolean;
    modelOverride?: LlmDescriptor;
    regenerationRequest?: {
      messageId: number;
      parentMessage: Message;
      forceSearch?: boolean;
    };
    forceSearch?: boolean;
    queryOverride?: string;
    isSeededChat?: boolean;
  }) => Promise<void>;
  onMessageSelection: (nodeId: number) => void;
  stopGenerating: () => void;
  handleResubmitLastMessage: () => void;
  onScrollButtonVisibilityChange?: (visible: boolean) => void;
}

const ChatUI = React.memo(
  React.forwardRef(
    (
      {
        liveAssistant,
        llmManager,
        currentMessageFiles,
        deepResearchEnabled,
        setPresentingDocument,
        onSubmit,
        onMessageSelection,
        stopGenerating,
        handleResubmitLastMessage,
        onScrollButtonVisibilityChange,
      }: ChatUIProps,
      ref: ForwardedRef<ChatUIHandle>
    ) => {
      const { user } = useUser();
      const { currentChatSessionId } = useChatSessions();
      const { isMobile } = useScreenSize();
      const loadError = useLoadingError();
      const messages = useCurrentMessageHistory();
      const error = useUncaughtError();
      const messageTree = useCurrentMessageTree();
      const currentChatState = useCurrentChatState();

      // Stable fallbacks to avoid changing prop identities on each render
      const emptyDocs = useMemo<OnyxDocument[]>(() => [], []);
      const emptyChildrenIds = useMemo<number[]>(() => [], []);

      const scrollContainerRef = useRef<HTMLDivElement>(null);
      const endDivRef = useRef<HTMLDivElement>(null);
      const scrollDist = useRef<number>(0);
      const scrolledForSession = useRef<string | null>(null);
      const prevMessageCount = useRef<number>(0);
      const lastUserMessageIdRef = useRef<string | null>(null);
      const [aboveHorizon, setAboveHorizon] = useState(false);
      const [hasContentAbove, setHasContentAbove] = useState(false);
      const [hasContentBelow, setHasContentBelow] = useState(false);
      const [spacerHeight, setSpacerHeight] = useState(0);
      // Track whether initial scroll positioning is complete to prevent flicker
      const [isScrollReady, setIsScrollReady] = useState(false);
      const scrollReadySession = useRef<string | null>(null);

      // Notify parent when scroll button visibility changes
      // Hide button during streaming when auto-scroll is enabled
      useEffect(() => {
        const autoScrollEnabled = user?.preferences.auto_scroll !== false;
        const isStreaming = currentChatState === "streaming";
        const shouldShow = aboveHorizon && !(autoScrollEnabled && isStreaming);
        onScrollButtonVisibilityChange?.(shouldShow);
      }, [
        aboveHorizon,
        onScrollButtonVisibilityChange,
        user?.preferences.auto_scroll,
        currentChatState,
      ]);

      // Watch for content and container size changes to update spacer and scroll button
      useEffect(() => {
        if (!scrollContainerRef.current) return;

        const container = scrollContainerRef.current;
        const autoScrollEnabled = user?.preferences.auto_scroll !== false;
        let rafId: number | null = null;

        const updateSpacerAndHorizon = () => {
          // Throttle updates using requestAnimationFrame
          if (rafId) return;
          rafId = requestAnimationFrame(() => {
            rafId = null;
            if (!lastUserMessageIdRef.current || !endDivRef.current) return;

            const lastUserMsgElement = document.getElementById(
              lastUserMessageIdRef.current
            );
            if (lastUserMsgElement) {
              const contentEnd = endDivRef.current.offsetTop;

              // Only recalculate spacer for auto-scroll OFF mode
              // Auto-scroll ON: content flows naturally, useScrollonStream handles following
              if (!autoScrollEnabled) {
                const contentFromMessage =
                  contentEnd - lastUserMsgElement.offsetTop;
                const neededSpacer = Math.max(
                  0,
                  container.clientHeight -
                    contentFromMessage -
                    MESSAGE_TOP_OFFSET_PX
                );
                setSpacerHeight(neededSpacer);
              }

              // Calculate distance to actual content end (excludes spacer)
              const viewportBottom =
                container.scrollTop + container.clientHeight;
              const contentBelowViewport = contentEnd - viewportBottom;

              setAboveHorizon(
                contentBelowViewport > SCROLL_BUTTON_THRESHOLD_PX
              );
              setHasContentAbove(
                container.scrollTop > FADE_GRADIENT_THRESHOLD_PX
              );
              setHasContentBelow(
                contentBelowViewport > FADE_GRADIENT_THRESHOLD_PX
              );
            }
          });
        };

        // Use MutationObserver to detect new lines during streaming (auto-scroll OFF only)
        let mutationObserver: MutationObserver | null = null;
        if (!autoScrollEnabled) {
          mutationObserver = new MutationObserver(updateSpacerAndHorizon);
          mutationObserver.observe(container, {
            childList: true,
            subtree: true,
            characterData: true,
          });
        }

        // Use ResizeObserver to detect container size changes (both modes)
        const resizeObserver = new ResizeObserver(updateSpacerAndHorizon);
        resizeObserver.observe(container);

        return () => {
          mutationObserver?.disconnect();
          resizeObserver.disconnect();
          if (rafId) cancelAnimationFrame(rafId);
        };
      }, [user?.preferences.auto_scroll]);

      // Use refs to keep callbacks stable while always using latest values
      const onSubmitRef = useRef(onSubmit);
      const deepResearchEnabledRef = useRef(deepResearchEnabled);
      const currentMessageFilesRef = useRef(currentMessageFiles);
      onSubmitRef.current = onSubmit;
      deepResearchEnabledRef.current = deepResearchEnabled;
      currentMessageFilesRef.current = currentMessageFiles;

      const createRegenerator = useCallback(
        (regenerationRequest: {
          messageId: number;
          parentMessage: Message;
          forceSearch?: boolean;
        }) => {
          return async function (modelOverride: LlmDescriptor) {
            return await onSubmitRef.current({
              message: regenerationRequest.parentMessage.message,
              currentMessageFiles: currentMessageFilesRef.current,
              deepResearch: deepResearchEnabledRef.current,
              modelOverride,
              messageIdToResend: regenerationRequest.parentMessage.messageId,
              regenerationRequest,
              forceSearch: regenerationRequest.forceSearch,
            });
          };
        },
        [] // Stable - uses refs for latest values
      );

      const handleEditWithMessageId = useCallback(
        (editedContent: string, msgId: number) => {
          onSubmitRef.current({
            message: editedContent,
            messageIdToResend: msgId,
            currentMessageFiles: [],
            deepResearch: deepResearchEnabledRef.current,
          });
        },
        [] // Stable - uses refs for latest values
      );

      const handleScroll = useCallback(() => {
        const container = scrollContainerRef.current;
        if (!container) return;

        // Calculate distance to actual content end (not including spacer)
        const contentEnd =
          endDivRef.current?.offsetTop ?? container.scrollHeight;
        const viewportBottom = container.scrollTop + container.clientHeight;
        const contentBelowViewport = contentEnd - viewportBottom;

        // Use scrollHeight-based distance for useScrollonStream compatibility
        const distanceFromBottom =
          container.scrollHeight -
          (container.scrollTop + container.clientHeight);
        scrollDist.current = distanceFromBottom;

        // Use content-based calculation for button (excludes spacer)
        setAboveHorizon(contentBelowViewport > SCROLL_BUTTON_THRESHOLD_PX);
        setHasContentAbove(container.scrollTop > FADE_GRADIENT_THRESHOLD_PX);
        setHasContentBelow(contentBelowViewport > FADE_GRADIENT_THRESHOLD_PX);

        // Recalculate spacer for auto-scroll OFF mode as content grows
        if (
          user?.preferences.auto_scroll === false &&
          endDivRef.current &&
          lastUserMessageIdRef.current
        ) {
          const lastUserMsgElement = document.getElementById(
            lastUserMessageIdRef.current
          );
          if (lastUserMsgElement) {
            const contentFromMessage =
              contentEnd - lastUserMsgElement.offsetTop;
            const neededSpacer = Math.max(
              0,
              container.clientHeight -
                contentFromMessage -
                MESSAGE_TOP_OFFSET_PX
            );
            setSpacerHeight(neededSpacer);
          }
        }
      }, [user?.preferences.auto_scroll]);

      const scrollToBottom = useCallback(() => {
        if (!endDivRef.current || !scrollContainerRef.current) return false;
        // Scroll to the end of actual content (endDivRef is before spacer)
        endDivRef.current.scrollIntoView({ behavior: "smooth", block: "end" });
        return true;
      }, []);

      useImperativeHandle(ref, () => ({ scrollToBottom }), [scrollToBottom]);

      useScrollonStream({
        chatState: currentChatState,
        scrollableDivRef: scrollContainerRef,
        scrollDist,
        endDivRef,
        debounceNumber: SCROLL_DEBOUNCE_MS,
        mobile: isMobile,
        enableAutoScroll: user?.preferences.auto_scroll !== false,
      });

      // Scroll handling on session load and when new messages are added
      useEffect(() => {
        const autoScrollEnabled = user?.preferences.auto_scroll !== false;
        const messageCount = messages.length;
        const isNewSession =
          scrolledForSession.current !== null &&
          scrolledForSession.current !== currentChatSessionId;
        const isNewMessage = messageCount > prevMessageCount.current;

        // Helper to calculate spacer height for positioning element at top
        const calcSpacerHeight = (element: HTMLElement): number => {
          if (!endDivRef.current || !scrollContainerRef.current) return 0;
          const contentEnd = endDivRef.current.offsetTop;
          const contentFromElement = contentEnd - element.offsetTop;
          return Math.max(
            0,
            scrollContainerRef.current.clientHeight -
              contentFromElement -
              MESSAGE_TOP_OFFSET_PX
          );
        };

        // Helper to update spacer and scroll-to-bottom button visibility
        const updateSpacerForElement = (elementId: string) => {
          const element = document.getElementById(elementId);
          if (!element || !endDivRef.current || !scrollContainerRef.current)
            return;

          setSpacerHeight(calcSpacerHeight(element));

          const contentEnd = endDivRef.current.offsetTop;
          const distanceFromBottom =
            contentEnd -
            (scrollContainerRef.current.scrollTop +
              scrollContainerRef.current.clientHeight);
          setAboveHorizon(distanceFromBottom > 0);
        };

        // Helper to mark scroll positioning as complete
        const markScrollReady = () => {
          setIsScrollReady(true);
          scrollReadySession.current = currentChatSessionId;
          scrolledForSession.current = currentChatSessionId;
        };

        // Reset tracking when session changes
        if (isNewSession) {
          scrolledForSession.current = null;
          prevMessageCount.current = 0;
          if (scrollReadySession.current !== currentChatSessionId) {
            setIsScrollReady(false);
          }
        }

        const shouldScrollForSession =
          scrolledForSession.current !== currentChatSessionId &&
          messageCount > 0;
        const shouldScrollForNewMessage = isNewMessage && messageCount > 0;

        // Update spacer for auto-scroll OFF during streaming (even when not scrolling)
        if (!autoScrollEnabled && lastUserMessageIdRef.current) {
          updateSpacerForElement(lastUserMessageIdRef.current);
        }

        // Early exit if no scroll needed
        if (
          !scrollContainerRef.current ||
          (!shouldScrollForSession && !shouldScrollForNewMessage)
        ) {
          prevMessageCount.current = messageCount;
          return;
        }

        let timeoutId: ReturnType<typeof setTimeout> | null = null;
        const rafId = requestAnimationFrame(() => {
          const container = scrollContainerRef.current;
          if (!container) return;

          const isInitialLoad = shouldScrollForSession;

          // Position user message at top first, then useScrollonStream handles
          // auto-following content as it generates (when auto-scroll is ON)
          const targetMessage = messages.at(-2) ?? messages[0];

          if (!targetMessage) {
            markScrollReady();
            return;
          }

          const elementId = `message-${targetMessage.nodeId}`;
          const element = document.getElementById(elementId);

          if (!element || !endDivRef.current) {
            markScrollReady();
            return;
          }

          lastUserMessageIdRef.current = elementId;
          const messageTop = element.offsetTop;

          // For auto-scroll OFF: use spacer to keep user message at top
          // For auto-scroll ON: no spacer needed, content flows naturally
          if (!autoScrollEnabled) {
            setSpacerHeight(calcSpacerHeight(element));
          } else {
            setSpacerHeight(0);
          }

          // Loading existing conversation (multiple messages) = instant
          // New messages (including first message of new conversation) = smooth
          const isLoadingExistingConversation =
            isInitialLoad && messageCount > 1;

          // Defer scroll to next tick so spacer height update takes effect
          timeoutId = setTimeout(() => {
            const targetScrollTop = Math.max(
              0,
              messageTop - MESSAGE_TOP_OFFSET_PX
            );

            if (isLoadingExistingConversation) {
              // Instant scroll for loading existing conversations
              container.scrollTop = targetScrollTop;
            } else {
              // Smooth animation for new messages
              container.scrollTo({
                top: targetScrollTop,
                behavior: "smooth",
              });
            }

            // Calculate visibility based on content end (endDivRef), not scrollHeight
            // This excludes the spacer from the calculation
            const contentEnd = endDivRef.current?.offsetTop ?? 0;
            const viewportBottom = targetScrollTop + container.clientHeight;
            const contentBelowViewport = contentEnd - viewportBottom;

            setAboveHorizon(contentBelowViewport > SCROLL_BUTTON_THRESHOLD_PX);
            setHasContentAbove(targetScrollTop > FADE_GRADIENT_THRESHOLD_PX);
            setHasContentBelow(
              contentBelowViewport > FADE_GRADIENT_THRESHOLD_PX
            );
            markScrollReady();
          }, 0);
        });

        prevMessageCount.current = messageCount;

        return () => {
          cancelAnimationFrame(rafId);
          if (timeoutId) clearTimeout(timeoutId);
        };
      }, [messages, currentChatSessionId, user?.preferences.auto_scroll]);

      if (!liveAssistant) return <div className="flex-1" />;

      return (
        <div className="flex flex-col flex-1 min-h-0 w-full relative overflow-hidden mb-[7.5rem]">
          {/* Fade overlays when content extends beyond viewport.
             NOTE: We can't use ShadowDiv here because ChatUI requires direct control
             over the scroll container for custom scroll behavior. */}
          <FadeOverlay show={hasContentAbove} position="top" />
          <FadeOverlay show={hasContentBelow} position="bottom" />

          <div
            key={currentChatSessionId}
            ref={scrollContainerRef}
            className="flex flex-1 justify-center min-h-0 overflow-y-auto overflow-x-hidden default-scrollbar"
            onScroll={handleScroll}
            style={{
              // TODO: remove this once we have a better solution for scroll anchoring
              overflowAnchor: "none",
              // Reserve symmetric space for scrollbar to keep content centered
              scrollbarGutter: "stable both-edges",
            }}
          >
            <div
              className="w-[min(50rem,100%)] px-4 pb-8"
              data-scroll-ready={isScrollReady || messages.length === 0}
              style={{
                // Hide content until scroll positioning is complete to prevent flicker
                visibility:
                  isScrollReady || messages.length === 0 ? "visible" : "hidden",
              }}
            >
              <Spacer />
              {messages.map((message, i) => {
                const messageReactComponentKey = `message-${message.nodeId}`;
                const parentMessage = message.parentNodeId
                  ? messageTree?.get(message.parentNodeId)
                  : null;

                if (message.type === "user") {
                  const nextMessage =
                    messages.length > i + 1 ? messages[i + 1] : null;

                  return (
                    <div
                      id={messageReactComponentKey}
                      key={messageReactComponentKey}
                    >
                      <HumanMessage
                        disableSwitchingForStreaming={
                          (nextMessage && nextMessage.is_generating) || false
                        }
                        stopGenerating={stopGenerating}
                        content={message.message}
                        files={message.files}
                        messageId={message.messageId}
                        nodeId={message.nodeId}
                        onEdit={handleEditWithMessageId}
                        otherMessagesCanSwitchTo={
                          parentMessage?.childrenNodeIds ?? emptyChildrenIds
                        }
                        onMessageSelection={onMessageSelection}
                      />
                    </div>
                  );
                } else if (message.type === "assistant") {
                  if ((error || loadError) && i === messages.length - 1) {
                    return (
                      <div key={`error-${message.nodeId}`} className="p-4">
                        <ErrorBanner
                          resubmit={handleResubmitLastMessage}
                          error={error || loadError || ""}
                          errorCode={message.errorCode || undefined}
                          isRetryable={message.isRetryable ?? true}
                          details={message.errorDetails || undefined}
                          stackTrace={message.stackTrace || undefined}
                        />
                      </div>
                    );
                  }

                  // NOTE: it's fine to use the previous entry in messageHistory
                  // since this is a "parsed" version of the message tree
                  // so the previous message is guaranteed to be the parent of the current message
                  const previousMessage = i !== 0 ? messages[i - 1] : null;
                  const chatStateData = {
                    assistant: liveAssistant,
                    docs: message.documents ?? emptyDocs,
                    citations: message.citations,
                    setPresentingDocument,
                    overriddenModel: llmManager.currentLlm?.modelName,
                    researchType: message.researchType,
                  };
                  return (
                    <div
                      id={`message-${message.nodeId}`}
                      key={messageReactComponentKey}
                    >
                      <AIMessage
                        rawPackets={message.packets}
                        chatState={chatStateData}
                        nodeId={message.nodeId}
                        messageId={message.messageId}
                        currentFeedback={message.currentFeedback}
                        llmManager={llmManager}
                        otherMessagesCanSwitchTo={
                          parentMessage?.childrenNodeIds ?? emptyChildrenIds
                        }
                        onMessageSelection={onMessageSelection}
                        onRegenerate={createRegenerator}
                        parentMessage={previousMessage}
                      />
                    </div>
                  );
                }
              })}

              {(((error !== null || loadError !== null) &&
                messages[messages.length - 1]?.type === "user") ||
                messages[messages.length - 1]?.type === "error") && (
                <div className="p-4">
                  <ErrorBanner
                    resubmit={handleResubmitLastMessage}
                    error={error || loadError || ""}
                    errorCode={
                      messages[messages.length - 1]?.errorCode || undefined
                    }
                    isRetryable={
                      messages[messages.length - 1]?.isRetryable ?? true
                    }
                    details={
                      messages[messages.length - 1]?.errorDetails || undefined
                    }
                    stackTrace={
                      messages[messages.length - 1]?.stackTrace || undefined
                    }
                  />
                </div>
              )}

              {/* End marker - before spacer so we can measure content end */}
              <div ref={endDivRef} />
              {/* Spacer to allow scrolling new messages to top */}
              {spacerHeight > 0 && <Spacer pixels={spacerHeight} />}
            </div>
          </div>
        </div>
      );
    }
  )
);
ChatUI.displayName = "ChatUI";

export default ChatUI;
