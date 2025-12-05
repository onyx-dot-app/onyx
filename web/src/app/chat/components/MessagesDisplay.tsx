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

  // Build a map of responseGroupId -> Messages for multi-model response grouping
  // Uses completeMessageTree to know about ALL response groups across all branches
  // Also track which nodeIds should be skipped (all but the first in each group)
  const { responseGroupMap, nodeIdsToSkip } = useMemo(() => {
    const groupMap = new Map<string, Message[]>();
    const skipNodeIds = new Set<number>();

    // First, build group info from the COMPLETE message tree (all branches)
    // This ensures we know about response groups even when viewing a different branch
    if (completeMessageTree) {
      for (const msg of Array.from(completeMessageTree.values())) {
        if (msg.responseGroupId) {
          const existing = groupMap.get(msg.responseGroupId);
          if (existing) {
            existing.push(msg);
          } else {
            groupMap.set(msg.responseGroupId, [msg]);
          }
        }
      }
    }

    // Also include messages from messageHistory (for streaming/pre-created nodes
    // that might not be in completeMessageTree yet)
    for (const msg of messageHistory) {
      if (msg.responseGroupId) {
        const existing = groupMap.get(msg.responseGroupId);
        if (existing) {
          // Check if this message is already in the group (by nodeId)
          if (!existing.some((m) => m.nodeId === msg.nodeId)) {
            existing.push(msg);
          }
        } else {
          groupMap.set(msg.responseGroupId, [msg]);
        }
      }
    }

    // For each group, sort by nodeId and mark all but the first as "skip"
    for (const [, messages] of Array.from(groupMap.entries())) {
      if (messages.length > 1) {
        // Sort by nodeId for consistent ordering
        messages.sort((a: Message, b: Message) => a.nodeId - b.nodeId);
        // Skip all except the first (representative) message
        for (let i = 1; i < messages.length; i++) {
          const msg = messages[i];
          if (msg) {
            skipNodeIds.add(msg.nodeId);
          }
        }
      }
    }

    // DEBUG: Log grouping result
    if (groupMap.size > 0) {
      console.log(
        "[MessagesDisplay] responseGroupMap:",
        Array.from(groupMap.entries()).map(([k, v]) => ({
          groupId: k,
          messageCount: v.length,
          nodeIds: v.map((m) => m.nodeId),
        }))
      );
    }

    return { responseGroupMap: groupMap, nodeIdsToSkip: skipNodeIds };
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

          // Multi-model response grouping:
          // Skip messages that are not the first in their response group
          if (nodeIdsToSkip.has(message.nodeId)) {
            return null;
          }

          // Build modelResponses from all messages in this response group
          let modelResponses: ModelResponse[] | undefined;
          let responseGroupNodeIds: Set<number> | undefined;

          if (message.responseGroupId) {
            const groupMessages = responseGroupMap.get(message.responseGroupId);
            console.log(
              "[MessagesDisplay] Rendering message with responseGroupId:",
              {
                messageNodeId: message.nodeId,
                responseGroupId: message.responseGroupId,
                groupMessagesCount: groupMessages?.length,
                groupNodeIds: groupMessages?.map((m) => m.nodeId),
              }
            );
            if (groupMessages && groupMessages.length > 1) {
              modelResponses = groupMessages.map((msg) => ({
                model: {
                  name: msg.modelProvider || "",
                  provider: msg.modelProvider || "",
                  modelName: msg.modelName || "",
                },
                // Include the actual message for this model's response
                message: msg,
              }));
              console.log(
                "[MessagesDisplay] Created modelResponses:",
                modelResponses.length
              );
              // Track nodeIds in this group to exclude from branch switching
              responseGroupNodeIds = new Set(
                groupMessages.map((msg) => msg.nodeId)
              );
            }
          }

          // Filter out non-representative messages from ALL response groups for branch switching
          // Each multi-model response group should appear as a single branch option, not 4 separate ones
          const switchableMessages = (() => {
            const allChildren =
              parentMessage?.childrenNodeIds ?? emptyChildrenIds;
            // Filter out all nodeIds that are "non-representative" in their response group
            // nodeIdsToSkip contains all messages except the first one in each response group
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
