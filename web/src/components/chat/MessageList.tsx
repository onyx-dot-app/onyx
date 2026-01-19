"use client";

import React, { useCallback, useMemo, useRef } from "react";
import { Message } from "@/app/chat/interfaces";
import { OnyxDocument, MinimalOnyxDocument } from "@/lib/search/interfaces";
import HumanMessage from "@/app/chat/message/HumanMessage";
import { ErrorBanner } from "@/app/chat/message/Resubmit";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { LlmDescriptor, LlmManager } from "@/lib/hooks";
import AIMessage from "@/app/chat/message/messageComponents/AIMessage";
import Spacer from "@/refresh-components/Spacer";
import AgentMessage, {
  RegenerationFactory,
} from "@/app/chat/message/messageComponents/AgentMessage";
import { FeedbackType } from "@/app/chat/interfaces";
import { FullChatState } from "@/app/chat/message/messageComponents/interfaces";

/**
 * Memoized wrapper component for AgentMessage.
 *
 * WHY A SEPARATE COMPONENT (instead of useMemo inside MessageList.map):
 * React hooks CANNOT be called inside loops or callbacks. This is invalid:
 *   messages.map((message) => {
 *     const chatState = useMemo(...); // INVALID - hooks can't be in map()
 *     return <AgentMessage chatState={chatState} />;
 *   });
 *
 * By extracting to a separate component, we CAN use hooks:
 *   - useMemo creates a stable chatState that only changes when dependencies change
 *   - React.memo() prevents re-renders when props are equal
 *   - AgentMessage receives stable props, so its arePropsEqual works correctly
 *
 * Without this wrapper, chatState was created inline in the map(), producing a
 * NEW object on every render, which broke AgentMessage's memoization entirely.
 */
interface AgentMessageWrapperProps {
  message: Message;
  liveAssistant: MinimalPersonaSnapshot;
  emptyDocs: OnyxDocument[];
  setPresentingDocument: (doc: MinimalOnyxDocument | null) => void;
  overriddenModel: string | undefined;
  llmManager: LlmManager;
  parentMessage: Message | null | undefined;
  emptyChildrenIds: number[];
  onMessageSelection: (nodeId: number) => void;
  createRegenerator: RegenerationFactory;
}

const AgentMessageWrapper = React.memo(function AgentMessageWrapper({
  message,
  liveAssistant,
  emptyDocs,
  setPresentingDocument,
  overriddenModel,
  llmManager,
  parentMessage,
  emptyChildrenIds,
  onMessageSelection,
  createRegenerator,
}: AgentMessageWrapperProps) {
  const chatState = useMemo<FullChatState>(
    () => ({
      assistant: liveAssistant,
      docs: message.documents ?? emptyDocs,
      citations: message.citations,
      setPresentingDocument,
      overriddenModel,
      researchType: message.researchType,
    }),
    [
      liveAssistant,
      message.documents,
      message.citations,
      setPresentingDocument,
      overriddenModel,
      message.researchType,
      emptyDocs,
    ]
  );

  return (
    <AgentMessage
      rawPackets={message.packets}
      packetCount={message.packets.length}
      chatState={chatState}
      nodeId={message.nodeId}
      messageId={message.messageId}
      currentFeedback={message.currentFeedback}
      llmManager={llmManager}
      otherMessagesCanSwitchTo={
        parentMessage?.childrenNodeIds ?? emptyChildrenIds
      }
      onMessageSelection={onMessageSelection}
      onRegenerate={createRegenerator}
      parentMessage={parentMessage}
    />
  );
});

export interface MessageListProps {
  messages: Message[];
  messageTree: Map<number, Message> | undefined;
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

  // Error state
  error: string | null;
  loadError: string | null;
  onResubmit: () => void;

  /**
   * Node ID of the message to use as scroll anchor.
   * This message will get a data-anchor attribute for ChatScrollContainer.
   */
  anchorNodeId?: number;
}

const MessageList = React.memo(
  ({
    messages,
    messageTree,
    liveAssistant,
    llmManager,
    setPresentingDocument,
    onMessageSelection,
    stopGenerating,
    onSubmit,
    deepResearchEnabled,
    currentMessageFiles,
    error,
    loadError,
    onResubmit,
    anchorNodeId,
  }: MessageListProps) => {
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
      <>
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

            return (
              <div
                id={`message-${message.nodeId}`}
                key={messageReactComponentKey}
                data-anchor={isAnchor ? "true" : undefined}
              >
                <AgentMessageWrapper
                  message={message}
                  liveAssistant={liveAssistant}
                  emptyDocs={emptyDocs}
                  setPresentingDocument={setPresentingDocument}
                  overriddenModel={llmManager.currentLlm?.modelName}
                  llmManager={llmManager}
                  parentMessage={parentMessage}
                  emptyChildrenIds={emptyChildrenIds}
                  onMessageSelection={onMessageSelection}
                  createRegenerator={createRegenerator}
                />
              </div>
            );
          }
          return null;
        })}

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
      </>
    );
  }
);

MessageList.displayName = "MessageList";

export default MessageList;
