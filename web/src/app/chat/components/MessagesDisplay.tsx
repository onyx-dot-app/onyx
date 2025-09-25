import React, { RefObject, useCallback, useMemo } from "react";
import { Message } from "@/app/chat/interfaces";
import { OnyxDocument } from "@/lib/search/interfaces";
import { MemoizedHumanMessage } from "@/app/chat/message/MemoizedHumanMessage";
import { ErrorBanner } from "@/app/chat/message/Resubmit";
import { FeedbackType } from "@/app/chat/interfaces";
import { LlmDescriptor, useLlmManager } from "@/lib/hooks";
import {
  FileResponse,
  FolderResponse,
  useDocumentsContext,
} from "@/app/chat/my-documents/DocumentsContext";
import { FileDescriptor } from "@/app/chat/interfaces";
import { MemoizedAIMessage } from "@/app/chat/message/messageComponents/MemoizedAIMessage";
import {
  useCurrentMessageHistory,
  useCurrentMessageTree,
  useLoadingError,
} from "../stores/useChatSessionStore";
import { useChatContext } from "@/components/context/ChatContext";
import { useAgentsContext } from "@/components-2/context/AgentsContext";
import { useDeepResearchToggle } from "../hooks/useDeepResearchToggle";

interface RegenerationRequest {
  messageId: number;
  parentMessage: Message;
  forceSearch?: boolean;
}

interface OnSubmitArgs {
  message: string;
  messageIdToResend?: number;
  selectedFiles: FileResponse[];
  selectedFolders: FolderResponse[];
  currentMessageFiles: FileDescriptor[];
  useAgentSearch: boolean;
  modelOverride?: LlmDescriptor;
  regenerationRequest?: RegenerationRequest;
  forceSearch?: boolean;
  queryOverride?: string;
  isSeededChat?: boolean;
  overrideFileDescriptors?: FileDescriptor[];
}

interface MessagesDisplayProps {
  setCurrentFeedback: (feedback: [FeedbackType, number] | null) => void;
  onSubmit: (args: OnSubmitArgs) => Promise<void>;
  onMessageSelection: (nodeId: number) => void;
  stopGenerating: () => void;
  uncaughtError: string | null;
  handleResubmitLastMessage: () => void;
  // autoScrollEnabled: boolean;
  lastMessageRef: RefObject<HTMLDivElement>;
  endDivRef: RefObject<HTMLDivElement>;
  // hasPerformedInitialScroll: boolean;
  // chatSessionId: string | null;
  // enterpriseSettings?: EnterpriseSettings | null;
}

export function MessagesDisplay({
  setCurrentFeedback,
  onSubmit,
  onMessageSelection,
  stopGenerating,
  uncaughtError,
  // loadingError,
  handleResubmitLastMessage,
  // autoScrollEnabled,
  lastMessageRef,
  endDivRef,
  // hasPerformedInitialScroll,
  // chatSessionId,
  // enterpriseSettings,
}: MessagesDisplayProps) {
  const { currentChat, currentChatId, llmProviders } = useChatContext();
  const messageHistory = useCurrentMessageHistory();
  const completeMessageTree = useCurrentMessageTree();
  const {
    currentAgent: currentAgentOrNone,
    unifiedAgent,
    pinnedAgents,
    agents,
  } = useAgentsContext();

  const currentAgent =
    currentAgentOrNone || unifiedAgent || pinnedAgents?.[0] || agents?.[0];
  if (!currentAgent)
    throw new Error(
      "At least one agent should be specified before reaching this point"
    );

  const { deepResearchEnabled } = useDeepResearchToggle({
    chatSessionId: currentChatId,
    assistantId: currentAgent?.id,
  });

  const llmManager = useLlmManager(llmProviders, currentChat!, currentAgent!);
  const {
    selectedFiles,
    selectedFolders,
    currentMessageFiles,
    setPresentingDocument,
  } = useDocumentsContext();
  const loadingError = useLoadingError();

  // Stable fallbacks to avoid changing prop identities on each render
  const emptyDocs = useMemo<OnyxDocument[]>(() => [], []);
  const emptyChildrenIds = useMemo<number[]>(() => [], []);
  const createRegenerator = useCallback(
    (regenerationRequest: RegenerationRequest) => {
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
    <>
      <div>
        {messageHistory.map((message, index) => {
          const messageTree = completeMessageTree;
          const messageReactComponentKey = `message-${message.nodeId}`;
          const parentMessage = message.parentNodeId
            ? messageTree?.get(message.parentNodeId)
            : null;

          if (message.type === "user") {
            const nextMessage =
              messageHistory.length > index + 1
                ? messageHistory[index + 1]
                : null;

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
              index === messageHistory.length - 1
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
            const previousMessage =
              index !== 0 ? messageHistory[index - 1] : null;
            return (
              <div
                id={`message-${message.nodeId}`}
                key={messageReactComponentKey}
                ref={
                  index === messageHistory.length - 1 ? lastMessageRef : null
                }
              >
                <MemoizedAIMessage
                  rawPackets={message.packets}
                  handleFeedbackWithMessageId={handleFeedback}
                  assistant={currentAgent}
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
      </div>

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
    </>
  );
}
