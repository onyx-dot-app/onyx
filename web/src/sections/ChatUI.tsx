"use client";

import React, {
  ForwardedRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import IconButton from "@/refresh-components/buttons/IconButton";
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
  useChatPageLayout,
  useCurrentChatState,
  useCurrentMessageTree,
  useUncaughtError,
} from "@/app/chat/stores/useChatSessionStore";
import useChatSessions from "@/hooks/useChatSessions";
import { useDeepResearchToggle } from "../app/chat/hooks/useDeepResearchToggle";
import { useUser } from "@/components/user/UserProvider";
import { HORIZON_DISTANCE_PX } from "@/lib/constants";
import Spacer from "@/refresh-components/Spacer";
import { SvgChevronDown } from "@opal/icons";

export interface ChatUIHandle {
  scrollToBottom: () => boolean;
  scrollBy: (delta: number) => void;
}

export interface ChatUIProps {
  liveAssistant: MinimalPersonaSnapshot | undefined;
  llmManager: LlmManager;
  currentMessageFiles: ProjectFile[];
  setPresentingDocument: (doc: MinimalOnyxDocument | null) => void;
  onSubmit: (args: {
    message: string;
    messageIdToResend?: number;
    currentMessageFiles: ProjectFile[];
    useAgentSearch: boolean;
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
}

const ChatUI = React.forwardRef(
  (
    {
      liveAssistant,
      llmManager,
      currentMessageFiles,
      setPresentingDocument,
      onSubmit,
      onMessageSelection,
      stopGenerating,
      handleResubmitLastMessage,
    }: ChatUIProps,
    ref: ForwardedRef<ChatUIHandle>
  ) => {
    const { user } = useUser();
    const { currentChatSessionId } = useChatSessions();
    const { deepResearchEnabled } = useDeepResearchToggle({
      chatSessionId: currentChatSessionId,
      assistantId: liveAssistant?.id,
    });
    const { isMobile } = useScreenSize();
    const { messageHistory: messages, loadingError: loadError } =
      useChatPageLayout();
    const error = useUncaughtError();
    const messageTree = useCurrentMessageTree();
    const currentChatState = useCurrentChatState();

    // Stable fallbacks to avoid changing prop identities on each render
    const emptyDocs = useMemo<OnyxDocument[]>(() => [], []);
    const emptyChildrenIds = useMemo<number[]>(() => [], []);

    const scrollContainerRef = useRef<HTMLDivElement>(null);
    const endDivRef = useRef<HTMLDivElement>(null);
    const scrollDist = useRef<number>(0);
    const [aboveHorizon, setAboveHorizon] = useState(false);
    const debounceNumber = 100;

    // Virtualizer for efficient message rendering - only renders visible messages
    const virtualizer = useVirtualizer({
      count: messages.length,
      getScrollElement: () => scrollContainerRef.current,
      estimateSize: () => 200, // Estimated height per message (larger estimate reduces layout shifts)
      overscan: 5, // Render 5 extra items above/below viewport for smooth fast scrolling
      getItemKey: useCallback(
        (index: number) => messages[index]?.nodeId ?? index,
        [messages]
      ),
    });

    const createRegenerator = useCallback(
      (regenerationRequest: {
        messageId: number;
        parentMessage: Message;
        forceSearch?: boolean;
      }) => {
        return async function (modelOverride: LlmDescriptor) {
          return await onSubmit({
            message: regenerationRequest.parentMessage.message,
            currentMessageFiles,
            useAgentSearch: deepResearchEnabled,
            modelOverride,
            messageIdToResend: regenerationRequest.parentMessage.messageId,
            regenerationRequest,
            forceSearch: regenerationRequest.forceSearch,
          });
        };
      },
      [onSubmit, deepResearchEnabled, currentMessageFiles]
    );

    const handleEditWithMessageId = useCallback(
      (editedContent: string, msgId: number) => {
        onSubmit({
          message: editedContent,
          messageIdToResend: msgId,
          currentMessageFiles: [],
          useAgentSearch: deepResearchEnabled,
        });
      },
      [onSubmit, deepResearchEnabled]
    );

    // Throttle state updates during scroll to prevent excessive re-renders
    const lastScrollUpdate = useRef(0);
    const pendingScrollUpdate = useRef<number | null>(null);

    const handleScroll = useCallback(() => {
      const container = scrollContainerRef.current;
      if (!container) return;

      const distanceFromBottom =
        container.scrollHeight - (container.scrollTop + container.clientHeight);

      scrollDist.current = distanceFromBottom;

      // Throttle the aboveHorizon state update to avoid re-renders during fast scroll
      const now = Date.now();
      const newAboveHorizon = distanceFromBottom > HORIZON_DISTANCE_PX;

      if (now - lastScrollUpdate.current > 100) {
        // Update immediately if throttle period has passed
        lastScrollUpdate.current = now;
        setAboveHorizon(newAboveHorizon);
      } else if (!pendingScrollUpdate.current) {
        // Schedule an update for after the throttle period
        pendingScrollUpdate.current = window.setTimeout(() => {
          pendingScrollUpdate.current = null;
          lastScrollUpdate.current = Date.now();
          const currentDistance =
            container.scrollHeight -
            (container.scrollTop + container.clientHeight);
          setAboveHorizon(currentDistance > HORIZON_DISTANCE_PX);
        }, 100);
      }
    }, []);

    // Cleanup pending scroll update on unmount
    useEffect(() => {
      return () => {
        if (pendingScrollUpdate.current) {
          clearTimeout(pendingScrollUpdate.current);
        }
      };
    }, []);

    const scrollToBottom = useCallback(() => {
      if (!endDivRef.current) return false;
      endDivRef.current.scrollIntoView({ behavior: "smooth" });
      return true;
    }, []);

    const scrollBy = useCallback((delta: number) => {
      if (!scrollContainerRef.current) return;
      scrollContainerRef.current.scrollBy({
        behavior: "smooth",
        top: delta,
      });
    }, []);

    useImperativeHandle(
      ref,
      () => ({
        scrollToBottom,
        scrollBy,
      }),
      [scrollToBottom, scrollBy]
    );

    useScrollonStream({
      chatState: currentChatState,
      scrollableDivRef: scrollContainerRef,
      scrollDist,
      endDivRef,
      debounceNumber,
      mobile: isMobile,
      enableAutoScroll: user?.preferences.auto_scroll,
    });

    // Scroll to bottom when new messages are added
    const prevMessagesLength = useRef(messages.length);
    useLayoutEffect(() => {
      if (messages.length > prevMessagesLength.current) {
        // New message was added, scroll to bottom
        virtualizer.scrollToIndex(messages.length - 1, { align: "end" });
      }
      prevMessagesLength.current = messages.length;
    }, [messages.length, virtualizer]);

    // Re-measure items when the last message updates (streaming)
    const lastMessage = messages[messages.length - 1];
    useEffect(() => {
      if (lastMessage?.is_generating) {
        // During streaming, periodically re-measure the last item (200ms to reduce layout thrashing)
        const interval = setInterval(() => {
          virtualizer.measureElement(
            document.querySelector(
              `[data-index="${messages.length - 1}"]`
            ) as HTMLElement | null
          );
        }, 200);
        return () => clearInterval(interval);
      }
    }, [lastMessage?.is_generating, messages.length, virtualizer]);

    if (!liveAssistant) return <div className="flex-1" />;

    // Check if we need to show error banner after the virtualized list
    const showTrailingError =
      ((error !== null || loadError !== null) &&
        messages[messages.length - 1]?.type === "user") ||
      messages[messages.length - 1]?.type === "error";

    const virtualItems = virtualizer.getVirtualItems();

    return (
      <div className="flex flex-col flex-1 w-full relative overflow-hidden">
        {aboveHorizon && (
          <div className="absolute bottom-0 left-1/2 -translate-x-1/2 z-floating-scroll-down-button">
            <IconButton icon={SvgChevronDown} onClick={scrollToBottom} />

            <Spacer />
          </div>
        )}

        <div
          key={currentChatSessionId}
          ref={scrollContainerRef}
          className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden default-scrollbar"
          onScroll={handleScroll}
        >
          {/* Virtualized message list - only visible messages are in the DOM */}
          <div
            style={{
              height: `${virtualizer.getTotalSize()}px`,
              width: "100%",
              position: "relative",
              contain: "strict",
            }}
          >
            {virtualItems.map((virtualItem) => {
              const i = virtualItem.index;
              const message = messages[i];
              if (!message) return null;
              const messageReactComponentKey = `message-${message.nodeId}`;
              const parentMessage = message.parentNodeId
                ? messageTree?.get(message.parentNodeId)
                : null;

              return (
                <div
                  key={messageReactComponentKey}
                  data-index={i}
                  ref={virtualizer.measureElement}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    transform: `translateY(${virtualItem.start}px)`,
                    willChange: "transform",
                    contain: "layout style",
                  }}
                >
                  {message.type === "user" ? (
                    <div id={messageReactComponentKey}>
                      <HumanMessage
                        disableSwitchingForStreaming={
                          messages[i + 1]?.is_generating || false
                        }
                        stopGenerating={stopGenerating}
                        content={message.message}
                        files={message.files}
                        messageId={message.messageId}
                        onEdit={(editedContent) => {
                          if (
                            message.messageId !== undefined &&
                            message.messageId !== null
                          ) {
                            handleEditWithMessageId(
                              editedContent,
                              message.messageId
                            );
                          }
                        }}
                        otherMessagesCanSwitchTo={
                          parentMessage?.childrenNodeIds ?? emptyChildrenIds
                        }
                        onMessageSelection={onMessageSelection}
                      />
                    </div>
                  ) : message.type === "assistant" ? (
                    (error || loadError) && i === messages.length - 1 ? (
                      <div className="max-w-message-max mx-auto">
                        <ErrorBanner
                          resubmit={handleResubmitLastMessage}
                          error={error || loadError || ""}
                          errorCode={message.errorCode || undefined}
                          isRetryable={message.isRetryable ?? true}
                          details={message.errorDetails || undefined}
                          stackTrace={message.stackTrace || undefined}
                        />
                      </div>
                    ) : (
                      <div id={`message-${message.nodeId}`}>
                        <AIMessage
                          rawPackets={message.packets}
                          chatState={{
                            assistant: liveAssistant,
                            docs: message.documents ?? emptyDocs,
                            citations: message.citations,
                            setPresentingDocument,
                            regenerate:
                              message.messageId !== undefined &&
                              i > 0 &&
                              messages[i - 1]
                                ? createRegenerator({
                                    messageId: message.messageId,
                                    parentMessage: messages[i - 1]!,
                                  })
                                : undefined,
                            overriddenModel: llmManager.currentLlm?.modelName,
                            researchType: message.researchType,
                          }}
                          nodeId={message.nodeId}
                          messageId={message.messageId}
                          currentFeedback={message.currentFeedback}
                          llmManager={llmManager}
                          otherMessagesCanSwitchTo={
                            parentMessage?.childrenNodeIds ?? emptyChildrenIds
                          }
                          onMessageSelection={onMessageSelection}
                        />
                      </div>
                    )
                  ) : null}
                </div>
              );
            })}
          </div>

          {/* Error banner for user messages that failed */}
          {showTrailingError && (
            <div className="max-w-message-max mx-auto">
              <ErrorBanner
                resubmit={handleResubmitLastMessage}
                error={error || loadError || ""}
                errorCode={
                  messages[messages.length - 1]?.errorCode || undefined
                }
                isRetryable={messages[messages.length - 1]?.isRetryable ?? true}
                details={
                  messages[messages.length - 1]?.errorDetails || undefined
                }
                stackTrace={
                  messages[messages.length - 1]?.stackTrace || undefined
                }
              />
            </div>
          )}

          <div ref={endDivRef} />
        </div>
      </div>
    );
  }
);
ChatUI.displayName = "ChatUI";

export default ChatUI;
