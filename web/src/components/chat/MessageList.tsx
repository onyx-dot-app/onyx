"use client";

import React, {
  useCallback,
  useEffect,
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
import { cn } from "@/lib/utils";
import AIMessage from "@/app/chat/message/messageComponents/AIMessage";
import Spacer from "@/refresh-components/Spacer";
import { TOP_OFFSET } from "@/components/chat/ChatScrollContainer";
import {
  useCurrentMessageHistory,
  useCurrentMessageTree,
  useLoadingError,
  useUncaughtError,
} from "@/app/chat/stores/useChatSessionStore";

export interface MessageListProps {
  liveAssistant: MinimalPersonaSnapshot;
  llmManager: LlmManager;
  setPresentingDocument: (doc: MinimalOnyxDocument | null) => void;
  onMessageSelection: (nodeId: number) => void;
  stopGenerating: () => void;

  // Submit handlers
  onSubmit: (args: {
    message: string;
    messageIdToResend?: number;
    currentMessageFiles: any[];
    deepResearch: boolean;
    modelOverride?: LlmDescriptor;
    regenerationRequest?: {
      messageId: number;
      parentMessage: Message;
      forceSearch?: boolean;
    };
    forceSearch?: boolean;
  }) => Promise<void>;
  deepResearchEnabled: boolean;
  currentMessageFiles: any[];

  onResubmit: () => void;

  /**
   * Node ID of the message to use as scroll anchor.
   * This message will get a data-anchor attribute for ChatScrollContainer.
   */
  anchorNodeId?: number;

  /**
   * When true, disables the backdrop blur effect on the container.
   */
  disableBlur?: boolean;

  /**
   * Whether the assistant is currently streaming a response.
   * Used to apply min-height to the streaming message container.
   */
  isStreaming?: boolean;
}

const MessageList = React.memo(
  ({
    liveAssistant,
    llmManager,
    setPresentingDocument,
    onMessageSelection,
    stopGenerating,
    onSubmit,
    deepResearchEnabled,
    currentMessageFiles,
    onResubmit,
    anchorNodeId,
    disableBlur,
    isStreaming = false,
  }: MessageListProps) => {
    // Get messages and error state from store
    const messages = useCurrentMessageHistory();
    const messageTree = useCurrentMessageTree();
    const error = useUncaughtError();
    const loadError = useLoadingError();
    // Stable fallbacks to avoid changing prop identities on each render
    const emptyDocs = useMemo<OnyxDocument[]>(() => [], []);
    const emptyChildrenIds = useMemo<number[]>(() => [], []);

    // Use refs to keep callbacks stable while always using latest values
    const onSubmitRef = useRef(onSubmit);
    const deepResearchEnabledRef = useRef(deepResearchEnabled);
    const currentMessageFilesRef = useRef(currentMessageFiles);
    onSubmitRef.current = onSubmit;
    deepResearchEnabledRef.current = deepResearchEnabled;
    currentMessageFilesRef.current = currentMessageFiles;

    // Track min-height state separately to delay removal and prevent layout shift
    // Min-height is needed when generation is active (anchorNodeId OR isStreaming)
    const shouldHaveMinHeight = !!(anchorNodeId || isStreaming);
    const [minHeightActive, setMinHeightActive] = useState(shouldHaveMinHeight);

    useEffect(() => {
      if (shouldHaveMinHeight) {
        // Immediately enable min-height when generation starts
        setMinHeightActive(true);
      } else if (minHeightActive) {
        // Delay removal to prevent layout shift when generation ends
        // The scroll container will have time to stabilize
        const timer = setTimeout(() => {
          setMinHeightActive(false);
        }, 100);
        return () => clearTimeout(timer);
      }
    }, [shouldHaveMinHeight, minHeightActive]);

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
      []
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
      []
    );

    return (
      <div
        className={cn(
          "w-[min(50rem,100%)] h-full px-6 rounded-2xl",
          !disableBlur && "backdrop-blur-md"
        )}
      >
        <Spacer />
        {messages.map((message, i) => {
          const messageReactComponentKey = `message-${message.nodeId}`;
          const parentMessage = message.parentNodeId
            ? messageTree?.get(message.parentNodeId)
            : null;
          const isAnchor = message.nodeId === anchorNodeId;

          if (message.type === "user") {
            const nextMessage =
              messages.length > i + 1 ? messages[i + 1] : null;

            return (
              <div
                id={messageReactComponentKey}
                key={messageReactComponentKey}
                data-anchor={isAnchor ? "true" : undefined}
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
                    resubmit={onResubmit}
                    error={error || loadError || ""}
                    errorCode={message.errorCode || undefined}
                    isRetryable={message.isRetryable ?? true}
                    details={message.errorDetails || undefined}
                    stackTrace={message.stackTrace || undefined}
                  />
                </div>
              );
            }

            const previousMessage = i !== 0 ? messages[i - 1] : null;
            const chatStateData = {
              assistant: liveAssistant,
              docs: message.documents ?? emptyDocs,
              citations: message.citations,
              setPresentingDocument,
              overriddenModel: llmManager.currentLlm?.modelName,
              researchType: message.researchType,
            };

            // Apply min-height to the last assistant message during active generation
            // This creates scrollable space to position the anchor at TOP_OFFSET
            // Use minHeightActive which has delayed removal to prevent layout shift
            const isLastMessage = i === messages.length - 1;
            const needsMinHeight = minHeightActive && isLastMessage;

            return (
              <div
                id={`message-${message.nodeId}`}
                key={messageReactComponentKey}
                data-anchor={isAnchor ? "true" : undefined}
                style={{
                  minHeight: needsMinHeight
                    ? `calc(100vh - ${TOP_OFFSET}px)`
                    : undefined,
                }}
              >
                <AIMessage
                  rawPackets={message.packets}
                  packetsVersion={message.packetsVersion}
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
                {/* Marker for actual content end (used for auto-scroll during streaming) */}
                {isStreaming && isLastMessage && (
                  <div data-content-end="true" />
                )}
              </div>
            );
          }
          return null;
        })}

        {/* Spacer to create scrollable space when waiting for AI response */}
        {/* This allows the user message to be positioned at TOP_OFFSET before AI starts streaming */}
        {anchorNodeId &&
          messages.length > 0 &&
          messages[messages.length - 1]?.type === "user" && (
            <div
              style={{ minHeight: `calc(100vh - ${TOP_OFFSET}px)` }}
              aria-hidden="true"
            />
          )}

        {/* Error banner when last message is user message or error type */}
        {(((error !== null || loadError !== null) &&
          messages[messages.length - 1]?.type === "user") ||
          messages[messages.length - 1]?.type === "error") && (
          <div className="p-4">
            <ErrorBanner
              resubmit={onResubmit}
              error={error || loadError || ""}
              errorCode={messages[messages.length - 1]?.errorCode || undefined}
              isRetryable={messages[messages.length - 1]?.isRetryable ?? true}
              details={messages[messages.length - 1]?.errorDetails || undefined}
              stackTrace={
                messages[messages.length - 1]?.stackTrace || undefined
              }
            />
          </div>
        )}
      </div>
    );
  }
);

MessageList.displayName = "MessageList";

export default MessageList;
