"use client";

import React, { useCallback, useMemo, useRef } from "react";
import { Message } from "@/app/app/interfaces";
import { OnyxDocument, MinimalOnyxDocument } from "@/lib/search/interfaces";
import HumanMessage from "@/app/app/message/HumanMessage";
import { ErrorBanner } from "@/app/app/message/Resubmit";
import { MinimalAgent } from "@/lib/agents/types";
import { LlmDescriptor, LlmManager } from "@/lib/hooks";
import AgentMessage from "@/app/app/message/messageComponents/AgentMessage";
import MultiModelResponseView from "@/app/app/message/MultiModelResponseView";
import { MultiModelResponse } from "@/app/app/message/interfaces";
import { getMultiModelResponses } from "@/app/app/message/multiModel";
import { SelectedModel } from "@/sections/model-selector/MultiModelSelector";
import { buildModelProviderLookup } from "@/lib/languageModels/options";
import DynamicBottomSpacer from "@/components/chat/DynamicBottomSpacer";
import {
  useCurrentMessageHistory,
  useCurrentMessageTree,
  useLoadingError,
  useUncaughtError,
} from "@/app/app/stores/useChatSessionStore";
import { cn } from "@opal/utils";

/** Width constraint for normal (non-multi-model) messages. */
const MSG_MAX_W = "max-w-[720px] min-w-[400px]";

export interface ChatUIProps {
  liveAgent: MinimalAgent;
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
    selectedModels?: SelectedModel[];
  }) => Promise<void>;
  deepResearchEnabled: boolean;
  currentMessageFiles: any[];

  onResubmit: () => void;

  /**
   * Node ID of the message to use as scroll anchor.
   * Used by DynamicBottomSpacer to position the push-up effect.
   */
  anchorNodeId?: number;

  /** Currently selected models for multi-model comparison. */
  selectedModels?: SelectedModel[];

  /** When on, messages drop the reading-width cap and fill the window. */
  fullWidthChat?: boolean;
}

const ChatUI = React.memo(
  ({
    liveAgent,
    llmManager,
    setPresentingDocument,
    onMessageSelection,
    stopGenerating,
    onSubmit,
    deepResearchEnabled,
    currentMessageFiles,
    onResubmit,
    anchorNodeId,
    selectedModels,
    fullWidthChat,
  }: ChatUIProps) => {
    // Get messages and error state from store
    const messages = useCurrentMessageHistory();
    const messageTree = useCurrentMessageTree();
    const error = useUncaughtError();
    const loadError = useLoadingError();
    // Stable fallbacks to avoid changing prop identities on each render
    const emptyDocs = useMemo<OnyxDocument[]>(() => [], []);
    const emptyChildrenIds = useMemo<number[]>(() => [], []);

    // Reading-width cap on messages; dropped in full-width mode.
    const msgWidth = fullWidthChat ? undefined : MSG_MAX_W;

    // Lookup: model identifier → provider slug (for icon resolution).
    const modelProviderLookup = useMemo(
      () => buildModelProviderLookup(llmManager.llmProviders),
      [llmManager.llmProviders]
    );

    // Use refs to keep callbacks stable while always using latest values
    const onSubmitRef = useRef(onSubmit);
    const deepResearchEnabledRef = useRef(deepResearchEnabled);
    const currentMessageFilesRef = useRef(currentMessageFiles);
    const selectedModelsRef = useRef(selectedModels);
    onSubmitRef.current = onSubmit;
    deepResearchEnabledRef.current = deepResearchEnabled;
    currentMessageFilesRef.current = currentMessageFiles;
    selectedModelsRef.current = selectedModels;

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
        const models = selectedModelsRef.current;
        onSubmitRef.current({
          message: editedContent,
          messageIdToResend: msgId,
          currentMessageFiles: [],
          deepResearch: deepResearchEnabledRef.current,
          selectedModels: models && models.length >= 2 ? models : undefined,
        });
      },
      []
    );

    // Group a user message's sibling assistant responses into multi-model
    // panels. Memoized on the tree + provider lookup so identity is stable
    // across renders; the grouping itself lives in the shared util so the
    // read-only shared view can reuse it.
    const getMultiModelResponsesForMessage = useCallback(
      (userMessage: Message): MultiModelResponse[] | null =>
        messageTree
          ? getMultiModelResponses(
              userMessage,
              messageTree,
              modelProviderLookup
            )
          : null,
      [messageTree, modelProviderLookup]
    );

    return (
      <>
        {/* No max-width on container — individual messages control their own width.
            Multi-model responses use full width while normal messages stay centered. */}
        <div
          className={cn(
            "flex flex-col w-full h-full pt-4 pb-8 gap-12",
            !fullWidthChat && "pr-1"
          )}
        >
          {messages.map((message, i) => {
            const messageReactComponentKey = `message-${message.nodeId}`;
            const parentMessage = message.parentNodeId
              ? messageTree?.get(message.parentNodeId)
              : null;
            if (message.type === "user") {
              const nextMessage =
                messages.length > i + 1 ? messages[i + 1] : null;
              const multiModelResponses =
                getMultiModelResponsesForMessage(message);

              return (
                <div
                  id={messageReactComponentKey}
                  key={messageReactComponentKey}
                  className="flex flex-col gap-12 w-full"
                >
                  <div className={cn("w-full self-center", msgWidth)}>
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

                  {/* Multi-model responses use full width */}
                  {multiModelResponses && (
                    <MultiModelResponseView
                      responses={multiModelResponses}
                      chatState={{
                        agent: liveAgent,
                        docs: emptyDocs,
                        citations: undefined,
                        setPresentingDocument,
                        overriddenModel: llmManager.currentLlm?.modelName,
                      }}
                      llmManager={llmManager}
                      onRegenerate={createRegenerator}
                      parentMessage={message}
                      otherMessagesCanSwitchTo={
                        parentMessage?.childrenNodeIds ?? emptyChildrenIds
                      }
                      onMessageSelection={onMessageSelection}
                    />
                  )}
                </div>
              );
            } else if (message.type === "assistant") {
              if ((error || loadError) && i === messages.length - 1) {
                return (
                  <div
                    key={`error-${message.nodeId}`}
                    className={cn("p-4 w-full self-center", msgWidth)}
                  >
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

              // Skip assistant messages already rendered in MultiModelResponseView
              if (
                previousMessage?.type === "user" &&
                getMultiModelResponsesForMessage(previousMessage)
              ) {
                return null;
              }

              const chatStateData = {
                agent: liveAgent,
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
                  className={cn("w-full self-center", msgWidth)}
                >
                  <AgentMessage
                    fullWidthChat={fullWidthChat}
                    rawPackets={message.packets}
                    packetCount={message.packetCount}
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
                    processingDurationSeconds={
                      message.processingDurationSeconds
                    }
                  />
                </div>
              );
            }
            return null;
          })}

          {/* Error banner when last message is user message or error type.
              Skip for multi-model per-panel errors — those are shown in
              their own panel, not as a global banner. */}
          {(((error !== null || loadError !== null) &&
            messages[messages.length - 1]?.type === "user") ||
            (messages[messages.length - 1]?.type === "error" &&
              !messages[messages.length - 1]?.modelDisplayName)) && (
            <div className={cn("p-4 w-full self-center", msgWidth)}>
              <ErrorBanner
                resubmit={onResubmit}
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
        </div>
        {/* Dynamic spacer for "fresh chat" effect - pushes content up when new message is sent */}
        <DynamicBottomSpacer anchorNodeId={anchorNodeId} />
      </>
    );
  }
);
ChatUI.displayName = "ChatUI";

export default ChatUI;
