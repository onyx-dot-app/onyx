import React, { RefObject, useState, useCallback } from "react";
import { Packet, StreamingCitation } from "@/app/chat/services/streamingModels";
import { FeedbackType } from "@/app/chat/interfaces";
import { OnyxDocument } from "@/lib/search/interfaces";
import { TooltipGroup } from "@/components/tooltip/CustomTooltip";
import {
  useChatSessionStore,
  useDocumentSidebarVisible,
  useSelectedNodeForDocDisplay,
} from "@/app/chat/stores/useChatSessionStore";
import {
  handleCopy,
  convertMarkdownTablesToTsv,
} from "@/app/chat/message/copyingUtils";
import { getTextContent } from "@/app/chat/services/packetUtils";
import { removeThinkingTokens } from "@/app/chat/services/thinkingTokens";
import MessageSwitcher from "@/app/chat/message/MessageSwitcher";
import CitedSourcesToggle from "@/app/chat/message/messageComponents/CitedSourcesToggle";
import IconButton from "@/refresh-components/buttons/IconButton";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
import LLMPopover from "@/refresh-components/popovers/LLMPopover";
import { parseLlmDescriptor } from "@/lib/llm/utils";
import { LlmDescriptor, LlmManager } from "@/lib/hooks";
import { Message } from "@/app/chat/interfaces";
import { SvgThumbsDown, SvgThumbsUp } from "@opal/icons";
import { RegenerationFactory } from "./AgentMessage";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useFeedbackController } from "@/app/chat/hooks/useFeedbackController";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import FeedbackModal, {
  FeedbackModalProps,
} from "@/app/chat/components/modal/FeedbackModal";

export interface MessageToolbarProps {
  // Message identification
  nodeId: number;
  messageId?: number;

  // Message switching
  includeMessageSwitcher: boolean;
  currentMessageInd: number | null | undefined;
  otherMessagesCanSwitchTo?: number[];
  getPreviousMessage: () => number | undefined;
  getNextMessage: () => number | undefined;
  onMessageSelection?: (nodeId: number) => void;

  // Copy functionality
  rawPackets: Packet[];
  finalAnswerRef: RefObject<HTMLDivElement | null>;

  // Feedback
  currentFeedback?: FeedbackType | null;

  // Regeneration
  onRegenerate?: RegenerationFactory;
  parentMessage?: Message | null;
  llmManager: LlmManager | null;
  currentModelName?: string;

  // Citations
  citations: StreamingCitation[];
  documentMap: Map<string, OnyxDocument>;
}

export default function MessageToolbar({
  nodeId,
  messageId,
  includeMessageSwitcher,
  currentMessageInd,
  otherMessagesCanSwitchTo,
  getPreviousMessage,
  getNextMessage,
  onMessageSelection,
  rawPackets,
  finalAnswerRef,
  currentFeedback,
  onRegenerate,
  parentMessage,
  llmManager,
  currentModelName,
  citations,
  documentMap,
}: MessageToolbarProps) {
  // Document sidebar state - managed internally to reduce prop drilling
  const documentSidebarVisible = useDocumentSidebarVisible();
  const selectedMessageForDocDisplay = useSelectedNodeForDocDisplay();
  const updateCurrentDocumentSidebarVisible = useChatSessionStore(
    (state) => state.updateCurrentDocumentSidebarVisible
  );
  const updateCurrentSelectedNodeForDocDisplay = useChatSessionStore(
    (state) => state.updateCurrentSelectedNodeForDocDisplay
  );

  // Feedback modal state and handlers
  const { popup, setPopup } = usePopup();
  const { handleFeedbackChange } = useFeedbackController({ setPopup });
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
    [currentFeedback, modal.isOpen, feedbackModalProps, messageId]
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

  return (
    <>
      {popup}

      <modal.Provider>
        <FeedbackModal {...feedbackModalProps!} />
      </modal.Provider>

      <div className="flex md:flex-row justify-between items-center w-full mt-1 transition-transform duration-300 ease-in-out transform opacity-100">
        <TooltipGroup>
          <div className="flex items-center gap-x-0.5">
            {includeMessageSwitcher && (
              <div className="-mx-1">
                <MessageSwitcher
                  currentPage={(currentMessageInd ?? 0) + 1}
                  totalPages={otherMessagesCanSwitchTo?.length || 0}
                  handlePrevious={() => {
                    const prevMessage = getPreviousMessage();
                    if (prevMessage !== undefined && onMessageSelection) {
                      onMessageSelection(prevMessage);
                    }
                  }}
                  handleNext={() => {
                    const nextMessage = getNextMessage();
                    if (nextMessage !== undefined && onMessageSelection) {
                      onMessageSelection(nextMessage);
                    }
                  }}
                />
              </div>
            )}

            <CopyIconButton
              getCopyText={() =>
                convertMarkdownTablesToTsv(
                  removeThinkingTokens(getTextContent(rawPackets)) as string
                )
              }
              getHtmlContent={() => finalAnswerRef.current?.innerHTML || ""}
              tertiary
              data-testid="AgentMessage/copy-button"
            />
            <IconButton
              icon={SvgThumbsUp}
              onClick={() => handleFeedbackClick("like")}
              tertiary
              transient={isFeedbackTransient("like")}
              tooltip={
                currentFeedback === "like" ? "Remove Like" : "Good Response"
              }
              data-testid="AgentMessage/like-button"
            />
            <IconButton
              icon={SvgThumbsDown}
              onClick={() => handleFeedbackClick("dislike")}
              tertiary
              transient={isFeedbackTransient("dislike")}
              tooltip={
                currentFeedback === "dislike"
                  ? "Remove Dislike"
                  : "Bad Response"
              }
              data-testid="AgentMessage/dislike-button"
            />

            {onRegenerate &&
              messageId !== undefined &&
              parentMessage &&
              llmManager && (
                <div data-testid="AgentMessage/regenerate">
                  <LLMPopover
                    llmManager={llmManager}
                    currentModelName={currentModelName}
                    onSelect={(modelName) => {
                      const llmDescriptor = parseLlmDescriptor(modelName);
                      const regenerator = onRegenerate({
                        messageId,
                        parentMessage,
                      });
                      regenerator(llmDescriptor);
                    }}
                    folded
                  />
                </div>
              )}

            {nodeId && (citations.length > 0 || documentMap.size > 0) && (
              <CitedSourcesToggle
                citations={citations}
                documentMap={documentMap}
                nodeId={nodeId}
                onToggle={(toggledNodeId) => {
                  // Toggle sidebar if clicking on the same message
                  if (
                    selectedMessageForDocDisplay === toggledNodeId &&
                    documentSidebarVisible
                  ) {
                    updateCurrentDocumentSidebarVisible(false);
                    updateCurrentSelectedNodeForDocDisplay(null);
                  } else {
                    updateCurrentSelectedNodeForDocDisplay(toggledNodeId);
                    updateCurrentDocumentSidebarVisible(true);
                  }
                }}
              />
            )}
          </div>
        </TooltipGroup>
      </div>
    </>
  );
}
