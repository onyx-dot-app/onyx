import React, { RefObject, useCallback, useMemo } from "react";
import { Message } from "../interfaces";
import { OnyxDocument, MinimalOnyxDocument } from "@/lib/search/interfaces";
import { MemoizedHumanMessage } from "../message/MemoizedHumanMessage";
import { ErrorBanner } from "../message/Resubmit";
import { FeedbackType } from "@/app/chat/interfaces";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { LlmDescriptor, LlmManager } from "@/lib/hooks";
import { EnterpriseSettings } from "@/app/admin/settings/interfaces";
import { FileDescriptor } from "@/app/chat/interfaces";
import { MemoizedAIMessage } from "../message/messageComponents/MemoizedAIMessage";
import { ProjectFile } from "../projects/projectsService";

interface MessagesDisplayProps {
  messageHistory: Message[];
  completeMessageTree: Map<number, Message> | null | undefined;
  liveAssistant: MinimalPersonaSnapshot;
  llmManager: LlmManager;
  deepResearchEnabled: boolean;
  currentMessageFiles: ProjectFile[];
  setPresentingDocument: (doc: MinimalOnyxDocument | null) => void;
  setCurrentFeedback: (feedback: [FeedbackType, number] | null) => void;
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
    overrideFileDescriptors?: FileDescriptor[];
  }) => Promise<void>;
  onMessageSelection: (nodeId: number) => void;
  stopGenerating: () => void;
  uncaughtError: string | null;
  loadingError: string | null;
  handleResubmitLastMessage: () => void;
  autoScrollEnabled: boolean;
  getContainerHeight: () => string | undefined;
  lastMessageRef: RefObject<HTMLDivElement>;
  endPaddingRef: RefObject<HTMLDivElement>;
  endDivRef: RefObject<HTMLDivElement>;
  hasPerformedInitialScroll: boolean;
  chatSessionId: string | null;
  enterpriseSettings?: EnterpriseSettings | null;
}

export const MessagesDisplay: React.FC<MessagesDisplayProps> = ({
  messageHistory,
  completeMessageTree,
  liveAssistant,
  llmManager,
  deepResearchEnabled,
  currentMessageFiles,
  setPresentingDocument,
  setCurrentFeedback,
  onSubmit,
  onMessageSelection,
  stopGenerating,
  uncaughtError,
  loadingError,
  handleResubmitLastMessage,
  autoScrollEnabled,
  getContainerHeight,
  lastMessageRef,
  endPaddingRef,
  endDivRef,
  hasPerformedInitialScroll,
  chatSessionId,
  enterpriseSettings,
}) => {
  // Stable fallbacks to avoid changing prop identities on each render
  const emptyDocs = useMemo<OnyxDocument[]>(() => [], []);
  const emptyChildrenIds = useMemo<number[]>(() => [], []);
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

  const handleFeedback = useCallback(
    (feedback: FeedbackType, messageId: number) => {
      setCurrentFeedback([feedback, messageId!]);
    },
    [setCurrentFeedback]
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

  return (
    <div
      style={{ overflowAnchor: "none" }}
      key={chatSessionId}
      className={
        (hasPerformedInitialScroll ? "" : " hidden ") +
        "desktop:-ml-4 w-full mx-auto " +
        "absolute mobile:top-0 desktop:top-0 left-0 " +
        (enterpriseSettings?.two_lines_for_chat_header ? "pt-20 " : "pt-4 ")
      }
    >
      {messageHistory.map((message, i) => {
        const messageTree = completeMessageTree;
        const messageReactComponentKey = `message-${message.nodeId}`;
        const parentMessage = message.parentNodeId
          ? messageTree?.get(message.parentNodeId)
          : null;

        if (message.type === "user") {
          const nextMessage =
            messageHistory.length > i + 1 ? messageHistory[i + 1] : null;

          return (
            <div id={messageReactComponentKey} key={messageReactComponentKey}>
              <MemoizedHumanMessage
                disableSwitchingForStreaming={
                  (nextMessage && nextMessage.is_generating) || false
                }
                stopGenerating={stopGenerating}
                content={message.message}
                files={message.files}
                messageId={message.messageId}
                handleEditWithMessageId={handleEditWithMessageId}
                otherMessagesCanSwitchTo={
                  parentMessage?.childrenNodeIds ?? emptyChildrenIds
                }
                onMessageSelection={onMessageSelection}
              />
            </div>
          );
        } else if (message.type === "assistant") {
          if (
            (uncaughtError || loadingError) &&
            i === messageHistory.length - 1
          ) {
            return (
              <div
                key={`error-${message.nodeId}`}
                className="max-w-message-max mx-auto"
              >
                <ErrorBanner
                  resubmit={handleResubmitLastMessage}
                  error={uncaughtError || loadingError || ""}
                />
              </div>
            );
          }

          // NOTE: it's fine to use the previous entry in messageHistory
          // since this is a "parsed" version of the message tree
          // so the previous message is guaranteed to be the parent of the current message
          const previousMessage = i !== 0 ? messageHistory[i - 1] : null;
          return (
            <div
              className="text-text"
              id={`message-${message.nodeId}`}
              key={messageReactComponentKey}
              ref={i === messageHistory.length - 1 ? lastMessageRef : null}
            >
              <MemoizedAIMessage
                rawPackets={message.packets}
                handleFeedbackWithMessageId={handleFeedback}
                assistant={liveAssistant}
                docs={message.documents ?? emptyDocs}
                citations={message.citations}
                setPresentingDocument={setPresentingDocument}
                createRegenerator={createRegenerator}
                parentMessage={previousMessage!}
                messageId={message.messageId}
                overriddenModel={llmManager.currentLlm?.modelName}
                nodeId={message.nodeId}
                llmManager={llmManager}
                otherMessagesCanSwitchTo={
                  parentMessage?.childrenNodeIds ?? emptyChildrenIds
                }
                onMessageSelection={onMessageSelection}
                researchType={message.researchType}
              />
            </div>
          );
        }
      })}

      {((uncaughtError !== null || loadingError !== null) &&
        messageHistory[messageHistory.length - 1]?.type === "user") ||
        (messageHistory[messageHistory.length - 1]?.type === "error" && (
          <div className="max-w-message-max mx-auto">
            <ErrorBanner
              resubmit={handleResubmitLastMessage}
              error={uncaughtError || loadingError || ""}
            />
          </div>
        ))}

      {messageHistory.length > 0 && (
        <div
          style={{
            height: !autoScrollEnabled ? getContainerHeight() : undefined,
          }}
        />
      )}

      <div ref={endPaddingRef} className="h-[95px]" />
      <div ref={endDivRef} />
    </div>
  );
};
