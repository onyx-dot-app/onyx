"use client";

import React, { useCallback, useMemo, useRef } from "react";
import { Message } from "@/app/app/interfaces";
import { OnyxDocument, MinimalOnyxDocument } from "@/lib/search/interfaces";
import HumanMessage from "@/app/app/message/HumanMessage";
import { ErrorBanner } from "@/app/app/message/Resubmit";
import { MinimalPersonaSnapshot } from "@/app/admin/agents/interfaces";
import { LlmDescriptor, LlmManager } from "@/lib/hooks";
import AgentMessage from "@/app/app/message/messageComponents/AgentMessage";
import MultiModelResponseView, {
  MultiModelResponse,
} from "@/app/app/message/MultiModelResponseView";
import { SelectedModel } from "@/refresh-components/popovers/ModelSelector";
import DynamicBottomSpacer from "@/components/chat/DynamicBottomSpacer";
import {
  useCurrentMessageHistory,
  useCurrentMessageTree,
  useLoadingError,
  useUncaughtError,
} from "@/app/app/stores/useChatSessionStore";

const MSG_MAX_W = "max-w-[720px] min-w-[400px]";

export interface ChatUIProps {
  liveAgent: MinimalPersonaSnapshot;
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
  selectedModels: SelectedModel[];
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
  }: ChatUIProps) => {
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
          selectedModels: models.length >= 2 ? models : undefined,
        });
      },
      []
    );

    // Helper to check if a user message has multi-model responses
    const getMultiModelResponses = useCallback(
      (userMessage: Message): MultiModelResponse[] | null => {
        if (!messageTree) return null;

        const childrenNodeIds = userMessage.childrenNodeIds || [];
        if (childrenNodeIds.length < 2) return null;

        const childMessages = childrenNodeIds
          .map((nodeId) => messageTree.get(nodeId))
          .filter(
            (msg): msg is Message =>
              msg !== undefined && msg.type === "assistant"
          );

        if (childMessages.length < 2) return null;

        // Distinguish multi-model from regenerations: multi-model messages
        // have modelDisplayName or overridden_model set. Regenerations don't.
        // During streaming, overridden_model is set. On reload, modelDisplayName is set.
        const multiModelChildren = childMessages.filter(
          (msg) => msg.modelDisplayName || msg.overridden_model
        );
        if (multiModelChildren.length < 2) return null;

        const latestChildNodeId = userMessage.latestChildNodeId;

        return childMessages.map((msg, idx) => {
          // During streaming, overridden_model has the friendly display name.
          // On reload from history, modelDisplayName has the DB-stored name.
          const name = msg.overridden_model || msg.modelDisplayName || "Model";
          return {
            modelIndex: idx,
            provider: "",
            modelName: name,
            displayName: name,
            packets: msg.packets || [],
            packetCount: msg.packetCount || msg.packets?.length || 0,
            nodeId: msg.nodeId,
            messageId: msg.messageId,
            isHighlighted: msg.nodeId === latestChildNodeId,
            currentFeedback: msg.currentFeedback,
            isGenerating: msg.is_generating || false,
          };
        });
      },
      [messageTree]
    );

    return (
      <>
        {/* No max-width on container — individual messages control their own width.
            Multi-model responses use full width while normal messages stay centered. */}
        <div className="flex flex-col w-full h-full pt-4 pb-8 pr-1 gap-12">
          {messages.map((message, i) => {
            const messageReactComponentKey = `message-${message.nodeId}`;
            const parentMessage = message.parentNodeId
              ? messageTree?.get(message.parentNodeId)
              : null;
            if (message.type === "user") {
              const nextMessage =
                messages.length > i + 1 ? messages[i + 1] : null;

              // Check for multi-model responses
              const multiModelResponses = getMultiModelResponses(message);

              return (
                <div
                  id={messageReactComponentKey}
                  key={messageReactComponentKey}
                  className="flex flex-col gap-12 w-full"
                >
                  {/* Human message stays at normal chat width */}
                  <div className={`w-full ${MSG_MAX_W} self-center`}>
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

                  {/* Multi-model response uses full width */}
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
                    className={`p-4 w-full ${MSG_MAX_W} self-center`}
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

              // Check if this assistant message is part of a multi-model response
              // If so, skip rendering since it's already rendered in MultiModelResponseView
              if (
                previousMessage?.type === "user" &&
                getMultiModelResponses(previousMessage)
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
                  className={`w-full ${MSG_MAX_W} self-center`}
                >
                  <AgentMessage
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

          {/* Error banner when last message is user message or error type */}
          {(((error !== null || loadError !== null) &&
            messages[messages.length - 1]?.type === "user") ||
            messages[messages.length - 1]?.type === "error") && (
            <div className={`p-4 w-full ${MSG_MAX_W} self-center`}>
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
