import React, { useRef, useState, useCallback, RefObject } from "react";
import { Packet, StopReason } from "@/app/chat/services/streamingModels";
import { FullChatState } from "@/app/chat/message/messageComponents/interfaces";
import { FeedbackType } from "@/app/chat/interfaces";
import { useCurrentChatState } from "@/app/chat/stores/useChatSessionStore";
import { handleCopy } from "@/app/chat/message/copyingUtils";
import { BlinkingDot } from "@/app/chat/message/BlinkingDot";
import { isDisplayPacket, isToolPacket } from "@/app/chat/services/packetUtils";
import { useMessageSwitching } from "@/app/chat/message/messageComponents/hooks/useMessageSwitching";
import MultiToolRenderer from "@/app/chat/message/messageComponents/MultiToolRenderer";
import { RendererComponent } from "@/app/chat/message/messageComponents/renderMessageComponent";
import { usePacketProcessor } from "@/app/chat/message/messageComponents/usePacketProcessor";
import MessageToolbar from "@/app/chat/message/messageComponents/MessageToolbar";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import { LlmDescriptor, LlmManager } from "@/lib/hooks";
import { Message } from "@/app/chat/interfaces";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import FeedbackModal, {
  FeedbackModalProps,
} from "@/app/chat/components/modal/FeedbackModal";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useFeedbackController } from "@/app/chat/hooks/useFeedbackController";
import Text from "@/refresh-components/texts/Text";
import { useTripleClickSelect } from "@/hooks/useTripleClickSelect";

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
  const { popup, setPopup } = usePopup();
  const { handleFeedbackChange } = useFeedbackController({ setPopup });

  // Get the global chat state to know if we're currently streaming
  const globalChatState = useCurrentChatState();

  const modal = useCreateModal();
  const [feedbackModalProps, setFeedbackModalProps] =
    useState<FeedbackModalProps | null>(null);

  // Helper to check if feedback button should be in transient state
  const isFeedbackTransient = useCallback(
    (feedbackType: "like" | "dislike") => {
      const hasCurrentFeedback = currentFeedback === feedbackType;
      if (!modal.isOpen) return hasCurrentFeedback;

      const isModalForThisFeedback =
        feedbackModalProps?.feedbackType === feedbackType;
      const isModalForThisMessage = feedbackModalProps?.messageId === messageId;

      return (
        hasCurrentFeedback || (isModalForThisFeedback && isModalForThisMessage)
      );
    },
    [currentFeedback, modal, feedbackModalProps, messageId]
  );

  // Handler for feedback button clicks with toggle logic
  const handleFeedbackClick = useCallback(
    async (clickedFeedback: "like" | "dislike") => {
      if (!messageId) {
        console.error("Cannot provide feedback - message has no messageId");
        return;
      }

      // Toggle logic
      if (currentFeedback === clickedFeedback) {
        // Clicking same button - remove feedback
        await handleFeedbackChange(messageId, null);
      }

      // Clicking like (will automatically clear dislike if it was active).
      // Check if we need modal for positive feedback.
      else if (clickedFeedback === "like") {
        const predefinedOptions =
          process.env.NEXT_PUBLIC_POSITIVE_PREDEFINED_FEEDBACK_OPTIONS;
        if (predefinedOptions && predefinedOptions.trim()) {
          // Open modal for positive feedback
          setFeedbackModalProps({
            feedbackType: "like",
            messageId,
          });
          modal.toggle(true);
        } else {
          // No modal needed - just submit like (this replaces any existing feedback)
          await handleFeedbackChange(messageId, "like");
        }
      }

      // Clicking dislike (will automatically clear like if it was active).
      // Always open modal for dislike.
      else {
        setFeedbackModalProps({
          feedbackType: "dislike",
          messageId,
        });
        modal.toggle(true);
      }
    },
    [messageId, currentFeedback, handleFeedbackChange, modal]
  );

  // Use the packet processor hook for all streaming packet processing
  const {
    citations,
    citationMap,
    documentMap,
    groupedPackets,
    finalAnswerComing,
    stopPacketSeen,
    stopReason,
    expectedBranchesPerTurn,
    displayComplete,
    setDisplayComplete,
    setFinalAnswerComingOverride,
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

  // Return a list of rendered message components, one for each ind
  return (
    <>
      {popup}

      <modal.Provider>
        <FeedbackModal {...feedbackModalProps!} />
      </modal.Provider>

      <div
        // for e2e tests
        data-testid={displayComplete ? "onyx-ai-message" : undefined}
        className="flex items-start pb-5 md:pt-5"
      >
        <AgentAvatar agent={chatState.assistant} size={24} />
        {/* w-full ensures the MultiToolRenderer non-expanded state takes up the full width */}
        <div className="max-w-message-max break-words pl-4 w-full">
          <div
            ref={markdownRef}
            className="overflow-x-visible max-w-content-max focus:outline-none select-text cursor-text"
            onMouseDown={handleTripleClick}
            onCopy={(e) => {
              if (markdownRef.current) {
                handleCopy(e, markdownRef as RefObject<HTMLDivElement>);
              }
            }}
          >
            {groupedPackets.length === 0 ? (
              // Show blinking dot when no content yet, or stopped message if user cancelled
              stopReason === StopReason.USER_CANCELLED ? (
                <Text as="p" secondaryBody text04>
                  User has stopped generation
                </Text>
              ) : (
                <BlinkingDot addMargin />
              )
            ) : (
              (() => {
                // Simple split: tools vs non-tools
                const toolGroups = groupedPackets.filter(
                  (group) =>
                    group.packets[0] && isToolPacket(group.packets[0], false)
                );

                // Non-tools include messages AND image generation
                const displayGroups =
                  finalAnswerComing || toolGroups.length === 0
                    ? groupedPackets.filter(
                        (group) =>
                          group.packets[0] && isDisplayPacket(group.packets[0])
                      )
                    : [];

                return (
                  <>
                    {/* Render tool groups in multi-tool renderer */}
                    {toolGroups.length > 0 && (
                      <MultiToolRenderer
                        packetGroups={toolGroups}
                        chatState={effectiveChatState}
                        isComplete={finalAnswerComing}
                        isFinalAnswerComing={finalAnswerComingRef.current}
                        stopPacketSeen={stopPacketSeen}
                        stopReason={stopReason}
                        isStreaming={globalChatState === "streaming"}
                        onAllToolsDisplayed={() =>
                          setFinalAnswerComingOverride(true)
                        }
                        expectedBranchesPerTurn={expectedBranchesPerTurn}
                      />
                    )}

                    {/* Render all display groups (messages + image generation) in main area */}
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
                  </>
                );
              })()
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
              onFeedbackClick={handleFeedbackClick}
              isFeedbackTransient={isFeedbackTransient}
              onRegenerate={onRegenerate}
              parentMessage={parentMessage}
              llmManager={llmManager}
              currentModelName={chatState.overriddenModel}
              citations={citations}
              documentMap={documentMap}
            />
          )}
        </div>
      </div>
    </>
  );
}, arePropsEqual);

export default AgentMessage;
