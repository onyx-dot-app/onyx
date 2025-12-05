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
import { ModelResponse } from "../message/messageComponents/ModelResponseTabs";

interface MessagesDisplayProps {
  messageHistory: Message[];
  completeMessageTree: Map<number, Message> | null | undefined;
  liveAssistant: MinimalPersonaSnapshot | undefined;
  llmManager: LlmManager;
  deepResearchEnabled: boolean;
  currentMessageFiles: ProjectFile[];
  setPresentingDocument: (doc: MinimalOnyxDocument | null) => void;
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
  lastMessageRef: RefObject<HTMLDivElement | null>;
  endPaddingRef: RefObject<HTMLDivElement | null>;
  endDivRef: RefObject<HTMLDivElement | null>;
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

  // Build a map of parentNodeId -> sibling assistant Messages for multi-model/regeneration grouping
  // Uses completeMessageTree to know about ALL sibling groups across all branches
  // Also track which nodeIds should be skipped (all but the first in each group)
  const { siblingGroupMap, nodeIdsToSkip } = useMemo(() => {
    const groupMap = new Map<number, Message[]>();
    const skipNodeIds = new Set<number>();

    // First, build group info from the COMPLETE message tree (all branches)
    // This ensures we know about sibling groups even when viewing a different branch
    if (completeMessageTree) {
      for (const msg of Array.from(completeMessageTree.values())) {
        if (msg.type === "assistant" && msg.parentNodeId !== null) {
          const existing = groupMap.get(msg.parentNodeId);
          if (existing) {
            existing.push(msg);
          } else {
            groupMap.set(msg.parentNodeId, [msg]);
          }
        }
      }
    }

    // Also include messages from messageHistory (for streaming/pre-created nodes
    // that might not be in completeMessageTree yet)
    for (const msg of messageHistory) {
      if (msg.type === "assistant" && msg.parentNodeId !== null) {
        const existing = groupMap.get(msg.parentNodeId);
        if (existing) {
          // Check if this message is already in the group (by nodeId)
          if (!existing.some((m) => m.nodeId === msg.nodeId)) {
            existing.push(msg);
          }
        } else {
          groupMap.set(msg.parentNodeId, [msg]);
        }
      }
    }

    // For each group with multiple siblings, sort for consistent ordering
    // Primary sort: by model name (for consistent order after refresh)
    // Fallback sort: by nodeId (for stable order during streaming when model names aren't set yet)
    for (const [, messages] of Array.from(groupMap.entries())) {
      if (messages.length > 1) {
        messages.sort((a: Message, b: Message) => {
          const aName = `${a.modelProvider || ""}:${a.modelName || ""}`;
          const bName = `${b.modelProvider || ""}:${b.modelName || ""}`;
          // If both have model names, sort by model name
          // Otherwise, fall back to nodeId for stable ordering during streaming
          if (aName !== ":" && bName !== ":") {
            return aName.localeCompare(bName);
          }
          return a.nodeId - b.nodeId;
        });
        // Skip all except the first (representative) message
        for (let i = 1; i < messages.length; i++) {
          const msg = messages[i];
          if (msg) {
            skipNodeIds.add(msg.nodeId);
          }
        }
      }
    }

    return { siblingGroupMap: groupMap, nodeIdsToSkip: skipNodeIds };
  }, [messageHistory, completeMessageTree]);
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

  // require assistant to be present before rendering
  if (!liveAssistant) {
    return null;
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
              <MemoizedHumanMessage
                disableSwitchingForStreaming={
                  (nextMessage && nextMessage.is_generating) || false
                }
                stopGenerating={stopGenerating}
                content={message.message}
                files={message.files}
                messageId={message.messageId}
                nodeId={message.nodeId}
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

          // For assistant messages, we need to find the actual parent (user message)
          // by looking up parentNodeId, since messageHistory may contain sibling
          // assistant messages (multi-model or regenerations) that share the same parent
          const previousMessage = (() => {
            if (i === 0) return null;
            // For assistant messages, find the parent by parentNodeId
            if (message.type === "assistant" && message.parentNodeId !== null) {
              return (
                messageHistory.find((m) => m.nodeId === message.parentNodeId) ??
                null
              );
            }
            // For user messages, the previous entry is the parent
            return messageHistory[i - 1] ?? null;
          })();

          // Multi-model/regeneration sibling grouping:
          // Skip messages that are not the first in their sibling group
          if (nodeIdsToSkip.has(message.nodeId)) {
            return null;
          }

          // Build modelResponses from all sibling messages with the same parent
          let modelResponses: ModelResponse[] | undefined;

          if (message.type === "assistant" && message.parentNodeId !== null) {
            const siblingMessages = siblingGroupMap.get(message.parentNodeId);
            if (siblingMessages && siblingMessages.length > 1) {
              modelResponses = siblingMessages.map((msg) => ({
                model: {
                  name: msg.modelProvider || "",
                  provider: msg.modelProvider || "",
                  modelName: msg.modelName || "",
                },
                // Include the actual message for this model's response
                message: msg,
              }));
            }
          }

          // Filter out non-representative messages from ALL sibling groups for branch switching
          // Each multi-model/regeneration group should appear as a single branch option
          const switchableMessages = (() => {
            const allChildren =
              parentMessage?.childrenNodeIds ?? emptyChildrenIds;
            // Filter out all nodeIds that are "non-representative" in their sibling group
            // nodeIdsToSkip contains all messages except the first one in each group
            return allChildren.filter((nodeId) => !nodeIdsToSkip.has(nodeId));
          })();

          return (
            <div
              className="text-text"
              id={`message-${message.nodeId}`}
              key={messageReactComponentKey}
              ref={i === messageHistory.length - 1 ? lastMessageRef : null}
            >
              <MemoizedAIMessage
                rawPackets={message.packets}
                assistant={liveAssistant}
                docs={message.documents ?? emptyDocs}
                citations={message.citations}
                setPresentingDocument={setPresentingDocument}
                createRegenerator={createRegenerator}
                parentMessage={previousMessage!}
                messageId={message.messageId}
                currentFeedback={message.currentFeedback}
                overriddenModel={llmManager.currentLlm?.modelName}
                nodeId={message.nodeId}
                llmManager={llmManager}
                otherMessagesCanSwitchTo={switchableMessages}
                onMessageSelection={onMessageSelection}
                researchType={message.researchType}
                modelResponses={modelResponses}
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
