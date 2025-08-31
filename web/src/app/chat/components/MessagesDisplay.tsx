import React, { RefObject } from "react";
import { Message } from "../interfaces";
import { OnyxDocument, MinimalOnyxDocument } from "@/lib/search/interfaces";
import { HumanMessage } from "../message/HumanMessage";
import { AIMessage } from "../message/messageComponents/AIMessage";
import { ErrorBanner } from "../message/Resubmit";
import { FeedbackType } from "@/app/chat/interfaces";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { LlmDescriptor } from "@/lib/hooks";
import {
  FileResponse,
  FolderResponse,
} from "@/app/chat/my-documents/DocumentsContext";
import { EnterpriseSettings } from "@/app/admin/settings/interfaces";
import { FileDescriptor } from "@/app/chat/interfaces";
import { useWhyDidYouUpdate } from "@/lib/hooks/useWhyDidYouUpdate";

interface MessagesDisplayProps {
  messageHistory: Message[];
  completeMessageTree: Map<number, Message> | null | undefined;
  liveAssistant: MinimalPersonaSnapshot | null;
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
  settings?: {
    isMobile?: boolean;
  } | null;
}

export const MessagesDisplay: React.FC<MessagesDisplayProps> = ({
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
  autoScrollEnabled,
  getContainerHeight,
  lastMessageRef,
  endPaddingRef,
  endDivRef,
  hasPerformedInitialScroll,
  chatSessionId,
  enterpriseSettings,
  settings,
}) => {
  function createRegenerator(regenerationRequest: {
    messageId: number;
    parentMessage: Message;
    forceSearch?: boolean;
  }) {
    return async function (modelOverride: LlmDescriptor) {
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
  }

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
              <HumanMessage
                setPresentingDocument={setPresentingDocument}
                disableSwitchingForStreaming={
                  (nextMessage && nextMessage.is_generating) || false
                }
                stopGenerating={stopGenerating}
                content={message.message}
                files={message.files}
                messageId={message.messageId}
                onEdit={(editedContent) => {
                  onSubmit({
                    message: editedContent,
                    messageIdToResend: message.messageId || undefined,
                    selectedFiles: [],
                    selectedFolders: [],
                    currentMessageFiles: [],
                    useAgentSearch: deepResearchEnabled,
                  });
                }}
                otherMessagesCanSwitchTo={parentMessage?.childrenNodeIds || []}
                onMessageSelection={onMessageSelection}
              />
            </div>
          );
        } else if (message.type === "assistant") {
          const previousMessage = i !== 0 ? messageHistory[i - 1] : null;

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

          return (
            <div
              className="text-text"
              id={`message-${message.nodeId}`}
              key={messageReactComponentKey}
              ref={i === messageHistory.length - 1 ? lastMessageRef : null}
            >
              <AIMessage
                rawPackets={message.packets}
                chatState={{
                  handleFeedback: (feedback) =>
                    setCurrentFeedback([feedback, message.messageId!]),
                  assistant: liveAssistant!,
                  docs: message.documents,
                  userFiles: [],
                  citations: message.citations,
                  setPresentingDocument: setPresentingDocument,
                  regenerate: createRegenerator({
                    messageId: message.messageId!,
                    parentMessage: previousMessage!,
                  }),
                  overriddenModel: llmManager.currentLlm?.modelName,
                }}
                nodeId={message.nodeId}
                otherMessagesCanSwitchTo={parentMessage?.childrenNodeIds || []}
                onMessageSelection={onMessageSelection}
              />
            </div>
          );
        }
      })}

      {((uncaughtError || loadingError) &&
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
