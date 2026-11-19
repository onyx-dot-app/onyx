"use client";

import React, { useCallback, useEffect, useMemo, useRef } from "react";
import { Message } from "@/app/app/types";
import type { ComposedMessage } from "@/lib/chat/types";
import { OnyxDocument, MinimalOnyxDocument } from "@/lib/search/types";
import HumanMessage from "@/app/app/message/HumanMessage";
import AgentResultsDivider from "@/app/app/message/AgentResultsDivider";
import { ErrorBanner } from "@/app/app/message/Resubmit";
import { MinimalAgent } from "@/lib/agents/types";
import { LlmDescriptor, LlmManager } from "@/lib/hooks";
import AgentMessage from "@/app/app/message/messageComponents/AgentMessage";
import MultiModelResponseView from "@/app/app/message/MultiModelResponseView";
import { MultiModelResponse } from "@/app/app/message/types";
import { getMultiModelResponses } from "@/app/app/message/multiModel";
import { SelectedModel } from "@/sections/model-selector/MultiModelSelector";
import { buildModelProviderLookup } from "@/lib/languageModels/options";
import {
  useCurrentChatState,
  useCurrentMessageHistory,
  useCurrentMessageTree,
  useHasOlderMessages,
  useLoadingError,
  useUncaughtError,
} from "@/app/app/stores/useChatSessionStore";
import { WindowedRow } from "@/lib/chatScroll/components";
import OlderMessagesLoader from "@/sections/chat/OlderMessagesLoader";
import { messageRowId } from "@/lib/chat/rowIds";
import ToolApprovalsRegion from "@/sections/chat/ToolApprovalsRegion";
import ToolQuestionsRegion from "@/sections/chat/ToolQuestionsRegion";
import { cn } from "@opal/utils";
import { CHAT_COLUMN_WIDTH } from "@/lib/chat/layout";

/** Width constraint for normal (non-multi-model) messages. */

/**
 * Rows at the end of the chat mount on the first render. Rows above them
 * mount once they near the viewport.
 */
const INITIALLY_MOUNTED_ROWS = 6;

/** Rows at the end of the chat that never unmount: the latest turn. */
const PINNED_ROWS = 2;

export interface ChatUIProps {
  activeAgent: MinimalAgent;
  llmManager: LlmManager;
  setPresentingDocument: (doc: MinimalOnyxDocument | null) => void;
  onMessageSelection: (nodeId: number) => void;
  stopGenerating: () => void;

  // Submit handlers
  onSubmit: (
    args: ComposedMessage & {
      messageIdToResend?: number;
      currentMessageFiles: any[];
      deepResearch: boolean;
      modelOverride?: LlmDescriptor;
      regenerationRequest?: {
        messageId: number;
        parentMessage: Message;
      };
      selectedModels?: SelectedModel[];
    }
  ) => Promise<void>;
  deepResearchEnabled: boolean;
  currentMessageFiles: any[];

  onResubmit: () => void;

  /** Node ID of the latest user message, the scroll anchor. Its row stays
   *  mounted. */
  anchorNodeId?: number;

  /** Currently selected models for multi-model comparison. */
  selectedModels?: SelectedModel[];

  /**
   * When on, the chat is in full-width mode: messages use its padding layout.
   * Their width comes from the page's `--app-chat-column-width`, not from
   * this prop.
   */
  fullWidthChat?: boolean;
}

const ChatUI = React.memo(
  ({
    activeAgent,
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
    const chatState = useCurrentChatState();
    // Stable fallbacks to avoid changing prop identities on each render
    const emptyDocs = useMemo<OnyxDocument[]>(() => [], []);
    const emptyChildrenIds = useMemo<number[]>(() => [], []);
    const hasOlderMessages = useHasOlderMessages();

    // Reading-width cap on messages, from the page's chat column width.
    const msgWidth = CHAT_COLUMN_WIDTH;

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

    useEffect(() => {
      onSubmitRef.current = onSubmit;
      deepResearchEnabledRef.current = deepResearchEnabled;
      currentMessageFilesRef.current = currentMessageFiles;
      selectedModelsRef.current = selectedModels;
    }, [onSubmit, deepResearchEnabled, currentMessageFiles, selectedModels]);

    const createRegenerator = useCallback(
      (regenerationRequest: { messageId: number; parentMessage: Message }) => {
        return async function (modelOverride: LlmDescriptor) {
          return await onSubmitRef.current({
            message: regenerationRequest.parentMessage.message,
            mentions: regenerationRequest.parentMessage.mentions ?? [],
            currentMessageFiles: currentMessageFilesRef.current,
            deepResearch: deepResearchEnabledRef.current,
            modelOverride,
            messageIdToResend: regenerationRequest.parentMessage.messageId,
            regenerationRequest,
          });
        };
      },
      []
    );

    const handleEditWithMessageId = useCallback(
      (edited: ComposedMessage, msgId: number) => {
        const models = selectedModelsRef.current;
        onSubmitRef.current({
          ...edited,
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
    // across renders. The grouping itself lives in the shared util so the
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
            !fullWidthChat && "md:pe-1"
          )}
        >
          {hasOlderMessages && <OlderMessagesLoader className={msgWidth} />}

          {messages.map((message, i) => {
            const messageReactComponentKey = messageRowId(message);
            const rowsFromEnd = messages.length - i;
            const pinned =
              rowsFromEnd <= PINNED_ROWS ||
              message.is_generating ||
              message.nodeId === anchorNodeId;
            const initiallyMounted = rowsFromEnd <= INITIALLY_MOUNTED_ROWS;
            const parentMessage = message.parentNodeId
              ? messageTree?.get(message.parentNodeId)
              : null;
            if (message.type === "user") {
              const nextMessage =
                messages.length > i + 1 ? messages[i + 1] : null;
              const multiModelResponses =
                getMultiModelResponsesForMessage(message);

              return (
                <WindowedRow
                  id={messageReactComponentKey}
                  key={messageReactComponentKey}
                  className="flex flex-col gap-12 w-full"
                  pinned={pinned}
                  initiallyMounted={initiallyMounted}
                >
                  <div className={cn("w-full self-center", msgWidth)}>
                    <HumanMessage
                      disableSwitchingForStreaming={
                        (nextMessage && nextMessage.is_generating) || false
                      }
                      stopGenerating={stopGenerating}
                      content={message.message}
                      files={message.files}
                      mentions={message.mentions}
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
                        agent: activeAgent,
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
                      selectionDisabled={chatState !== "input"}
                    />
                  )}
                </WindowedRow>
              );
            } else if (message.type === "agent_results") {
              return (
                <WindowedRow
                  id={messageReactComponentKey}
                  key={messageReactComponentKey}
                  className={cn("w-full self-center", msgWidth)}
                  pinned={pinned}
                  initiallyMounted={initiallyMounted}
                >
                  <AgentResultsDivider />
                </WindowedRow>
              );
            } else if (
              message.type === "assistant" ||
              message.type === "error"
            ) {
              const previousMessage = i !== 0 ? messages[i - 1] : null;

              // Skip assistant messages already rendered in MultiModelResponseView
              if (
                previousMessage?.type === "user" &&
                getMultiModelResponsesForMessage(previousMessage)
              ) {
                return null;
              }

              const chatStateData = {
                agent: activeAgent,
                docs: message.documents ?? emptyDocs,
                citations: message.citations,
                setPresentingDocument,
                overriddenModel: llmManager.currentLlm?.modelName,
                researchType: message.researchType,
              };

              return (
                <WindowedRow
                  id={messageReactComponentKey}
                  key={messageReactComponentKey}
                  className={cn("w-full self-center", msgWidth)}
                  pinned={pinned}
                  initiallyMounted={initiallyMounted}
                >
                  {(message.type !== "error" || message.packets.length > 0) && (
                    <AgentMessage
                      rawPackets={message.packets}
                      packetCount={message.packetCount}
                      restoredPacketCount={message.restoredPacketCount}
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
                      hideFooter={message.type === "error"}
                      disableTTS={message.type === "error"}
                    />
                  )}
                  {message.type === "error" && (
                    <ErrorBanner
                      resubmit={
                        chatState === "input" &&
                        previousMessage?.type === "user" &&
                        i === messages.length - 1
                          ? onResubmit
                          : undefined
                      }
                      error={message.errorMessage ?? ""}
                      errorCode={message.errorCode ?? undefined}
                      isRetryable={message.isRetryable ?? true}
                      details={message.errorDetails ?? undefined}
                      stackTrace={message.stackTrace}
                    />
                  )}
                </WindowedRow>
              );
            }
            return null;
          })}

          {/* Approval and question cards that wait for the user follow the
              last message. */}
          <ToolApprovalsRegion
            modelProviderLookup={modelProviderLookup}
            className={cn(
              "w-full self-center",
              msgWidth,
              !fullWidthChat && "px-3"
            )}
          />
          <ToolQuestionsRegion
            className={cn(
              "w-full self-center",
              msgWidth,
              !fullWidthChat && "px-3"
            )}
          />

          {error && (
            <div className={cn("p-4 w-full self-center", msgWidth)}>
              {/* A session error has no saved question to resend. */}
              <ErrorBanner {...error} />
            </div>
          )}
          {!error && loadError && (
            <div className={cn("p-4 w-full self-center", msgWidth)}>
              <ErrorBanner
                resubmit={chatState === "input" ? onResubmit : undefined}
                error={loadError}
              />
            </div>
          )}
        </div>
      </>
    );
  }
);
ChatUI.displayName = "ChatUI";

export default ChatUI;
