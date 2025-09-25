import React, { RefObject, useCallback, useMemo } from "react";
import { Message } from "@/app/chat/interfaces";
import { OnyxDocument, MinimalOnyxDocument } from "@/lib/search/interfaces";
import { MemoizedHumanMessage } from "@/app/chat/message/MemoizedHumanMessage";
import { ErrorBanner } from "@/app/chat/message/Resubmit";
import { FeedbackType } from "@/app/chat/interfaces";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { LlmDescriptor } from "@/lib/hooks";
import {
  FileResponse,
  FolderResponse,
} from "@/app/chat/my-documents/DocumentsContext";
import { EnterpriseSettings } from "@/app/admin/settings/interfaces";
import { FileDescriptor } from "@/app/chat/interfaces";
import { MemoizedAIMessage } from "@/app/chat/message/messageComponents/MemoizedAIMessage";
import { cn } from "@/lib/utils";

interface MessagesDisplayProps {
  messageHistory: Message[];
  completeMessageTree: Map<number, Message> | null | undefined;
  liveAssistant: MinimalPersonaSnapshot;
  llmManager: { currentLlm: LlmDescriptor | null };
  deepResearchEnabled: boolean;
  selectedFiles: FileResponse[];
  selectedFolders: FolderResponse[];
  currentMessageFiles: FileDescriptor[];
  setPresentingDocument: (doc: MinimalOnyxDocument | null) => void;
  setCurrentFeedback: (feedback: [FeedbackType, number] | null) => void;
  onSubmit: (args: {
    message: string;
    messageIdToResend?: number;
    selectedFiles: FileResponse[];
    selectedFolders: FolderResponse[];
    currentMessageFiles: FileDescriptor[];
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

export function MessagesDisplay({
  messageHistory,
  completeMessageTree,
  liveAssistant,
  llmManager,
  deepResearchEnabled,
  selectedFiles,
  selectedFolders,
  currentMessageFiles,
  setPresentingDocument,
  setCurrentFeedback,
  onSubmit,
  onMessageSelection,
  stopGenerating,
  uncaughtError,
  loadingError,
  handleResubmitLastMessage,
  lastMessageRef,
  endDivRef,
  hasPerformedInitialScroll,
  chatSessionId,
}: MessagesDisplayProps) {
  // Stable fallbacks to avoid changing prop identities on each render
  const emptyDocs = useMemo<OnyxDocument[]>(() => [], []);
  const emptyChildrenIds = useMemo<number[]>(() => [], []);
  const createRegenerator = useCallback(
    (regenerationRequest: {
      messageId: number;
      parentMessage: Message;
      forceSearch?: boolean;
    }) => {
      return async (modelOverride: LlmDescriptor) => {
        return await onSubmit({
          message: regenerationRequest.parentMessage.message,
          selectedFiles,
          selectedFolders,
          currentMessageFiles,
          useAgentSearch: deepResearchEnabled,
          modelOverride,
          messageIdToResend: regenerationRequest.parentMessage.messageId,
          regenerationRequest,
          forceSearch: regenerationRequest.forceSearch,
        });
      };
    },
    [
      onSubmit,
      deepResearchEnabled,
      selectedFiles,
      selectedFolders,
      currentMessageFiles,
    ]
  );

  const handleFeedback = useCallback(
    (feedback: FeedbackType, messageId: number) => {
      setCurrentFeedback([feedback, messageId!]);
    },
    [setCurrentFeedback]
  );

  const handleEditWithMessageId = useCallback(
    (editedContent: string, msgId: number | null | undefined) => {
      onSubmit({
        message: editedContent,
        messageIdToResend: msgId || undefined,
        selectedFiles: [],
        selectedFolders: [],
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
      className={cn(
        "w-full mx-auto dbg-red",
        !hasPerformedInitialScroll && "hidden",
      )}
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
                setPresentingDocument={setPresentingDocument}
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
                otherMessagesCanSwitchTo={
                  parentMessage?.childrenNodeIds ?? emptyChildrenIds
                }
                onMessageSelection={onMessageSelection}
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

      <div ref={endDivRef} />
    </div>
  );
}
