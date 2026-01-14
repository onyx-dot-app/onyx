import React, { useRef, RefObject } from "react";
import { Packet, StopReason } from "@/app/chat/services/streamingModels";
import { FullChatState } from "@/app/chat/message/messageComponents/interfaces";
import { FeedbackType } from "@/app/chat/interfaces";
import { handleCopy } from "@/app/chat/message/copyingUtils";
import { BlinkingDot } from "@/app/chat/message/BlinkingDot";
import { useMessageSwitching } from "@/app/chat/message/messageComponents/hooks/useMessageSwitching";
import { RendererComponent } from "@/app/chat/message/messageComponents/renderMessageComponent";
import { usePacketProcessor } from "@/app/chat/message/messageComponents/usePacketProcessor";
import MessageToolbar from "@/app/chat/message/messageComponents/MessageToolbar";
import { LlmDescriptor, LlmManager } from "@/lib/hooks";
import { Message } from "@/app/chat/interfaces";
import Text from "@/refresh-components/texts/Text";
import { useTripleClickSelect } from "@/hooks/useTripleClickSelect";
import {
  TimelineIcons,
  TimelineContent,
  StepConnector,
} from "@/app/chat/message/messageComponents/timeline";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";

// Type for the regeneration factory function passed from ChatUI
export type RegenerationFactory = (regenerationRequest: {
  messageId: number;
  parentMessage: Message;
  forceSearch?: boolean;
}) => (modelOverride: LlmDescriptor) => Promise<void>;

export interface AgentMessageProps {
  rawPackets: Packet[];
  chatState: FullChatState;
  nodeId: number;
  messageId?: number;
  currentFeedback?: FeedbackType | null;
  llmManager: LlmManager | null;
  otherMessagesCanSwitchTo?: number[];
  onMessageSelection?: (nodeId: number) => void;
  // Stable regeneration callback - takes (parentMessage) and returns a function that takes (modelOverride)
  onRegenerate?: RegenerationFactory;
  // Parent message needed to construct regeneration request
  parentMessage?: Message | null;
}

// TODO: Consider more robust comparisons:
// - `rawPackets.length` assumes packets are append-only. Could compare the last
//   packet or use a shallow comparison if packets can be modified in place.
// - `chatState.docs`, `chatState.citations`, and `otherMessagesCanSwitchTo` use
//   reference equality. Shallow array/object comparison would be more robust if
//   these are recreated with the same values.
function arePropsEqual(
  prev: AgentMessageProps,
  next: AgentMessageProps
): boolean {
  return (
    prev.nodeId === next.nodeId &&
    prev.messageId === next.messageId &&
    prev.currentFeedback === next.currentFeedback &&
    prev.rawPackets.length === next.rawPackets.length &&
    prev.chatState.assistant?.id === next.chatState.assistant?.id &&
    prev.chatState.docs === next.chatState.docs &&
    prev.chatState.citations === next.chatState.citations &&
    prev.chatState.overriddenModel === next.chatState.overriddenModel &&
    prev.chatState.researchType === next.chatState.researchType &&
    prev.otherMessagesCanSwitchTo === next.otherMessagesCanSwitchTo &&
    prev.onRegenerate === next.onRegenerate &&
    prev.parentMessage?.messageId === next.parentMessage?.messageId &&
    prev.llmManager?.isLoadingProviders === next.llmManager?.isLoadingProviders
    // Skip: chatState.regenerate, chatState.setPresentingDocument,
    //       most of llmManager, onMessageSelection (function/object props)
  );
}

const AgentMessage = React.memo(function AgentMessage({
  rawPackets,
  chatState,
  nodeId,
  messageId,
  currentFeedback,
  llmManager,
  otherMessagesCanSwitchTo,
  onMessageSelection,
  onRegenerate,
  parentMessage,
}: AgentMessageProps) {
  const markdownRef = useRef<HTMLDivElement>(null);
  const finalAnswerRef = useRef<HTMLDivElement>(null);
  const handleTripleClick = useTripleClickSelect(markdownRef);

  // Use the packet processor hook for all streaming packet processing
  // Returns pre-categorized toolTurnGroups and displayGroups ready for rendering
  const {
    citations,
    citationMap,
    documentMap,
    toolGroups,
    toolTurnGroups,
    displayGroups,
    hasSteps,
    finalAnswerComing,
    stopPacketSeen,
    stopReason,
    displayComplete,
    setDisplayComplete,
  } = usePacketProcessor(rawPackets, nodeId);

  // Keep a ref to finalAnswerComing for use in callbacks (to read latest value)
  const finalAnswerComingRef = useRef(finalAnswerComing);
  finalAnswerComingRef.current = finalAnswerComing;

  // Create a chatState that uses streaming citations for immediate rendering
  // This merges the prop citations with streaming citations, preferring streaming ones
  const effectiveChatState: FullChatState = {
    ...chatState,
    citations: {
      ...chatState.citations,
      ...citationMap,
    },
  };

  // Message switching logic
  const {
    currentMessageInd,
    includeMessageSwitcher,
    getPreviousMessage,
    getNextMessage,
  } = useMessageSwitching({
    nodeId,
    otherMessagesCanSwitchTo,
    onMessageSelection,
  });

  return (
    <div
      className="pb-5 md:pt-5 flex flex-col gap-3"
      data-testid={displayComplete ? "onyx-ai-message" : undefined}
    >
      {/* Row 1: Two-column layout for tool steps */}

      <div className="flex items-start px-1">
        {/* Left column: Avatar + Step icons */}
        <div className="flex flex-col items-center flex-shrink-0">
          <AgentAvatar agent={chatState.assistant} size={24} />
          {hasSteps && (
            <>
              <StepConnector className="min-h-3" />
              <TimelineIcons turnGroups={toolTurnGroups} />
            </>
          )}
        </div>

        {/* Right column: Tool steps content */}
        <div className="break-words pl-4 w-full">
          {toolGroups.length === 0 && displayGroups.length === 0 ? (
            // Show blinking dot when no content yet, or stopped message if user cancelled
            stopReason === StopReason.USER_CANCELLED ? (
              <Text as="p" secondaryBody text04>
                User has stopped generation
              </Text>
            ) : (
              <Text as="p" mainUiAction text05 className="animate-pulse">
                Thinking...
              </Text>
            )
          ) : (
            <TimelineContent
              turnGroups={toolTurnGroups}
              chatState={effectiveChatState}
              stopPacketSeen={stopPacketSeen}
              stopReason={stopReason}
            />
          )}
        </div>
      </div>

      {/* Row 2: Display content + MessageToolbar */}
      <div
        ref={markdownRef}
        className="overflow-x-visible focus:outline-none select-text cursor-text px-3"
        onMouseDown={handleTripleClick}
        onCopy={(e) => {
          if (markdownRef.current) {
            handleCopy(e, markdownRef as RefObject<HTMLDivElement>);
          }
        }}
      >
        {(toolGroups.length > 0 || displayGroups.length > 0) && (
          <div ref={finalAnswerRef}>
            {displayGroups.map((displayGroup, index) => (
              <RendererComponent
                key={`${displayGroup.turn_index}-${displayGroup.tab_index}`}
                packets={displayGroup.packets}
                chatState={effectiveChatState}
                onComplete={() => {
                  // if we've reverted to final answer not coming, don't set display complete
                  // this happens when using claude and a tool calling packet comes after
                  // some message packets
                  // Only mark complete on the last display group
                  if (
                    finalAnswerComingRef.current &&
                    index === displayGroups.length - 1
                  ) {
                    setDisplayComplete(true);
                  }
                }}
                animate={false}
                stopPacketSeen={stopPacketSeen}
                stopReason={stopReason}
              >
                {({ content }) => <div>{content}</div>}
              </RendererComponent>
            ))}
            {/* Show stopped message when user cancelled and no display content */}
            {displayGroups.length === 0 &&
              stopReason === StopReason.USER_CANCELLED && (
                <Text as="p" secondaryBody text04>
                  User has stopped generation
                </Text>
              )}
          </div>
        )}
      </div>

      {/* Feedback buttons - only show when streaming is complete */}
      {stopPacketSeen && displayComplete && (
        <MessageToolbar
          nodeId={nodeId}
          messageId={messageId}
          includeMessageSwitcher={includeMessageSwitcher}
          currentMessageInd={currentMessageInd}
          otherMessagesCanSwitchTo={otherMessagesCanSwitchTo}
          getPreviousMessage={getPreviousMessage}
          getNextMessage={getNextMessage}
          onMessageSelection={onMessageSelection}
          rawPackets={rawPackets}
          finalAnswerRef={finalAnswerRef}
          currentFeedback={currentFeedback}
          onRegenerate={onRegenerate}
          parentMessage={parentMessage}
          llmManager={llmManager}
          currentModelName={chatState.overriddenModel}
          citations={citations}
          documentMap={documentMap}
        />
      )}
    </div>
  );
}, arePropsEqual);

export default AgentMessage;
