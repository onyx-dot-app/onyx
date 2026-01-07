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
  useCurrentChatState,
  useCurrentMessageHistory,
  useCurrentMessageTree,
  useLoadingError,
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
      const [aboveHorizon, setAboveHorizon] = useState(false);
      const debounceNumber = 100;

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

        const distanceFromBottom =
          container.scrollHeight -
          (container.scrollTop + container.clientHeight);

        scrollDist.current = distanceFromBottom;
        setAboveHorizon(distanceFromBottom > HORIZON_DISTANCE_PX);
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

      // Scroll to bottom on session load and when new messages are added
      useEffect(() => {
        const messageCount = messages.length;
        const isNewSession =
          scrolledForSession.current !== null &&
          scrolledForSession.current !== currentChatSessionId;
        const isNewMessage = messageCount > prevMessageCount.current;

        // Reset tracking when session changes
        if (isNewSession) {
          scrolledForSession.current = null;
          prevMessageCount.current = 0;
        }

        // Determine if we should scroll
        const shouldScrollForSession =
          scrolledForSession.current !== currentChatSessionId &&
          messageCount > 0;
        const shouldScrollForNewMessage = isNewMessage && messageCount > 0;

        if (!shouldScrollForSession && !shouldScrollForNewMessage) {
          prevMessageCount.current = messageCount;
          return;
        }

        if (!scrollContainerRef.current) {
          prevMessageCount.current = messageCount;
          return;
        }

        // Use requestAnimationFrame to ensure DOM is ready
        const rafId = requestAnimationFrame(() => {
          if (scrollContainerRef.current) {
            scrollContainerRef.current.scrollTop =
              scrollContainerRef.current.scrollHeight;
            scrolledForSession.current = currentChatSessionId;
          }
        });

        prevMessageCount.current = messageCount;
        return () => cancelAnimationFrame(rafId);
      }, [messages.length, currentChatSessionId]);

      if (!liveAssistant) return <div className="flex-1" />;

      return (
        <div className="flex flex-col flex-1 w-full relative overflow-hidden">
          {aboveHorizon && (
            <div className="absolute bottom-0 left-1/2 -translate-x-1/2 z-sticky">
              <IconButton icon={SvgChevronDown} onClick={scrollToBottom} />

              <Spacer />
            </div>
          )}

          <div
            key={currentChatSessionId}
            ref={scrollContainerRef}
            className="flex flex-1 justify-center min-h-0 overflow-y-auto overflow-x-hidden default-scrollbar"
            onScroll={handleScroll}
          >
            <div className="w-[min(50rem,100%)] px-4">
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

              <div ref={endDivRef} />
            </div>
          </div>
        </div>
      );
    }
  )
);
ChatUI.displayName = "ChatUI";

export default ChatUI;
