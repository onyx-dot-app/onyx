"use client";

import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
} from "react";
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
import WindowedRow, {
  ESTIMATED_ROW_HEIGHT_PX,
} from "@/lib/chatScroll/components/WindowedRow";
import OlderMessagesLoader from "@/sections/chat/OlderMessagesLoader";
import { useOptionalScrollContainer } from "@/lib/chatScroll/components/ScrollContainerContext";
import ToolApprovalsRegion from "@/sections/chat/ToolApprovalsRegion";
import ToolQuestionsRegion from "@/sections/chat/ToolQuestionsRegion";
import { cn } from "@opal/utils";
import { CHAT_COLUMN_WIDTH } from "@/lib/chat/layout";
import { messageRowId } from "@/lib/chat/rowIds";
import { getChatScrollMemory } from "@/lib/chatScroll/scrollMemory";

/** Width constraint for normal (non-multi-model) messages. */

/**
 * Rows at the end of the chat mount on the first render. Rows above them
 * mount once they near the viewport.
 */
const INITIALLY_MOUNTED_ROWS = 6;

/** Rows at the end of the chat that never unmount: the latest turn. */
const PINNED_ROWS = 2;

/**
 * Rows above a saved position that mount on the first render. Below it, rows
 * mount until their cached heights cover the viewport.
 */
const SAVED_ROW_NEIGHBORS = 4;

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
    const scrollContainer = useOptionalScrollContainer();
    const scrollContainerRef = scrollContainer?.scrollContainerRef;
    // Kept per chat, so a chat opened again lays out its windowed rows at
    // their real heights and its saved position lands exactly. This component
    // remounts per chat, so the first render's chat is the one shown.
    const fallbackRowHeights = useRef(new Map<string, number>()).current;
    const scrollMemory = scrollContainer?.sessionId
      ? getChatScrollMemory(scrollContainer.sessionId)
      : null;
    const rowHeightCache = scrollMemory?.rowHeights ?? fallbackRowHeights;
    // The rows around a saved position mount on the first render, so a chat
    // opened there paints no blank placeholders.
    const savedRowRef = useRef(
      scrollMemory?.position?.kind === "row" ? scrollMemory.position : null
    );

    // A page of older messages goes in above the first row. Keep the view
    // still: scroll by the distance the former first row moved. Native scroll
    // anchoring cannot be relied on: Safari has none, and Chrome skips it at
    // the very top, where a page most often arrives.
    const lastScrollTopRef = useRef(0);
    useEffect(() => {
      const root = scrollContainerRef?.current;
      if (!root) return;
      const onScroll = () => {
        lastScrollTopRef.current = root.scrollTop;
      };
      onScroll();
      root.addEventListener("scroll", onScroll, { passive: true });
      return () => root.removeEventListener("scroll", onScroll);
    }, [scrollContainerRef]);

    // Rows are found by their DOM id, which can be the id first shown
    // (messageRowId), not `message-${nodeId}`.
    const firstRowRef = useRef<{ rowId: string; top: number } | null>(null);
    const firstMessage = messages[0];
    const firstRowId = firstMessage ? messageRowId(firstMessage) : undefined;
    useLayoutEffect(() => {
      const root = scrollContainerRef?.current;
      if (firstRowId === undefined) return;

      // Record the first row even before the scroll root attaches (they can
      // mount in the same commit); only the correction needs the root.
      const previous = firstRowRef.current;
      if (root && previous && previous.rowId !== firstRowId) {
        const previousRow = document.getElementById(previous.rowId);
        if (previousRow) {
          // A no-op where the browser's anchoring already moved it.
          const target =
            lastScrollTopRef.current + previousRow.offsetTop - previous.top;
          if (Math.abs(root.scrollTop - target) > 1) root.scrollTop = target;
        }
      }

      const firstRow = document.getElementById(firstRowId);
      firstRowRef.current = firstRow
        ? { rowId: firstRowId, top: firstRow.offsetTop }
        : null;
    }, [scrollContainerRef, firstRowId]);

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

    const savedRow = savedRowRef.current;
    const savedRowIndex = savedRow
      ? messages.findIndex(
          (message) => messageRowId(message) === savedRow.rowId
        )
      : -1;
    // The last row to mount below the saved row: the first one whose bottom
    // reaches the viewport's bottom, by cached heights.
    let savedRowMountEnd = savedRowIndex;
    // Scroll memory is per page, so a saved row only exists in the browser.
    if (savedRow && savedRowIndex >= 0 && typeof window !== "undefined") {
      const viewportHeight = window.innerHeight;
      let covered = savedRow.rowOffset;
      while (
        savedRowMountEnd < messages.length - 1 &&
        covered < viewportHeight
      ) {
        const message = messages[savedRowMountEnd];
        if (!message) break;
        const previous = messages[savedRowMountEnd - 1];
        // A multi-model reply renders in its user message's row, not its own.
        const ownRow = !(
          (message.type === "assistant" || message.type === "error") &&
          previous?.type === "user" &&
          getMultiModelResponsesForMessage(previous)
        );
        if (ownRow) {
          covered +=
            rowHeightCache.get(messageRowId(message)) ??
            ESTIMATED_ROW_HEIGHT_PX;
        }
        savedRowMountEnd += 1;
      }
    }

    const renderRow = (message: Message, i: number) => {
      const messageReactComponentKey = messageRowId(message);
      const rowsFromEnd = messages.length - i;
      const pinned =
        rowsFromEnd <= PINNED_ROWS ||
        message.is_generating ||
        message.nodeId === anchorNodeId;
      const initiallyMounted =
        rowsFromEnd <= INITIALLY_MOUNTED_ROWS ||
        (savedRowIndex >= 0 &&
          i >= savedRowIndex - SAVED_ROW_NEIGHBORS &&
          i <= savedRowMountEnd);
      const parentMessage = message.parentNodeId
        ? messageTree?.get(message.parentNodeId)
        : null;
      if (message.type === "user") {
        const nextMessage = messages.length > i + 1 ? messages[i + 1] : null;
        const multiModelResponses = getMultiModelResponsesForMessage(message);

        return (
          <WindowedRow
            id={messageReactComponentKey}
            key={messageReactComponentKey}
            className="flex flex-col gap-12 w-full"
            pinned={pinned}
            initiallyMounted={initiallyMounted}
            heightCache={rowHeightCache}
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
            heightCache={rowHeightCache}
          >
            <AgentResultsDivider />
          </WindowedRow>
        );
      } else if (message.type === "assistant" || message.type === "error") {
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
            heightCache={rowHeightCache}
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
                processingDurationSeconds={message.processingDurationSeconds}
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
    };

    // Each turn (a user message and its replies) is one group, so a row never
    // changes parent when a turn arrives. The latest turn fills the viewport
    // less the 1rem anchor offset and the list's 2rem bottom padding: at the
    // end of the chat, its user message sits 1rem below the top. Pure layout,
    // so it is the same in every browser and tab.
    const turns: { key: string; start: number; end: number }[] = [];
    messages.forEach((message, i) => {
      const last = turns[turns.length - 1];
      if (!last || message.type === "user") {
        turns.push({ key: messageRowId(message), start: i, end: i + 1 });
      } else {
        last.end = i + 1;
      }
    });

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

          {turns.map((turn, turnIndex) => (
            <div
              key={turn.key}
              data-chat-turn
              className="flex flex-col w-full gap-12"
              style={
                turnIndex === turns.length - 1
                  ? { minHeight: "calc(100cqh - 3rem)" }
                  : undefined
              }
            >
              {messages
                .slice(turn.start, turn.end)
                .map((message, offset) =>
                  renderRow(message, turn.start + offset)
                )}
            </div>
          ))}

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
