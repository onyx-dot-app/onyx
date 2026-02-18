"use client";

import React, { RefObject, useState, useCallback, useMemo } from "react";
import { Packet, StreamingCitation } from "@/app/app/services/streamingModels";
import { FeedbackType } from "@/app/app/interfaces";
import { OnyxDocument } from "@/lib/search/interfaces";
import { TooltipGroup } from "@/components/tooltip/CustomTooltip";
import {
  useChatSessionStore,
  useDocumentSidebarVisible,
  useSelectedNodeForDocDisplay,
} from "@/app/app/stores/useChatSessionStore";
import { convertMarkdownTablesToTsv } from "@/app/app/message/copyingUtils";
import { getTextContent } from "@/app/app/services/packetUtils";
import { removeThinkingTokens } from "@/app/app/services/thinkingTokens";
import MessageSwitcher from "@/app/app/message/MessageSwitcher";
import SourceTag from "@/refresh-components/buttons/source-tag/SourceTag";
import { citationsToSourceInfoArray } from "@/refresh-components/buttons/source-tag/sourceTagUtils";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
import LLMPopover from "@/refresh-components/popovers/LLMPopover";
import { parseLlmDescriptor } from "@/lib/llm/utils";
import { LlmManager } from "@/lib/hooks";
import { Message } from "@/app/app/interfaces";
import { SvgThumbsDown, SvgThumbsUp } from "@opal/icons";
import { RegenerationFactory } from "./AgentMessage";
import useFeedbackController from "@/hooks/useFeedbackController";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import FeedbackModal, {
  FeedbackModalProps,
} from "@/sections/modals/FeedbackModal";
import { Button } from "@opal/components";

// Wrapper component for SourceTag in toolbar to handle memoization
const SourcesTagWrapper = React.memo(function SourcesTagWrapper({
  citations,
  documentMap,
  nodeId,
  selectedMessageForDocDisplay,
  documentSidebarVisible,
  updateCurrentDocumentSidebarVisible,
  updateCurrentSelectedNodeForDocDisplay,
}: {
  citations: StreamingCitation[];
  documentMap: Map<string, OnyxDocument>;
  nodeId: number;
  selectedMessageForDocDisplay: number | null;
  documentSidebarVisible: boolean;
  updateCurrentDocumentSidebarVisible: (visible: boolean) => void;
  updateCurrentSelectedNodeForDocDisplay: (nodeId: number | null) => void;
}) {
  // Convert citations to SourceInfo array
  const sources = useMemo(
    () => citationsToSourceInfoArray(citations, documentMap),
    [citations, documentMap]
  );

  // Handle click to toggle sidebar
  const handleSourceClick = useCallback(() => {
    if (selectedMessageForDocDisplay === nodeId && documentSidebarVisible) {
      updateCurrentDocumentSidebarVisible(false);
      updateCurrentSelectedNodeForDocDisplay(null);
    } else {
      updateCurrentSelectedNodeForDocDisplay(nodeId);
      updateCurrentDocumentSidebarVisible(true);
    }
  }, [
    nodeId,
    selectedMessageForDocDisplay,
    documentSidebarVisible,
    updateCurrentDocumentSidebarVisible,
    updateCurrentSelectedNodeForDocDisplay,
  ]);

  if (sources.length === 0) return null;

  return (
    <SourceTag
      displayName="Sources"
      sources={sources}
      onSourceClick={handleSourceClick}
      toggleSource
    />
  );
});

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
  const { handleFeedbackChange } = useFeedbackController();
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
      // Open modal for positive feedback.
      else if (clickedFeedback === "like") {
        setFeedbackModalProps({
          feedbackType: "like",
          messageId,
        });
        modal.toggle(true);
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
      <modal.Provider>
        <FeedbackModal {...feedbackModalProps!} />
      </modal.Provider>

      <div
        data-testid="AgentMessage/toolbar"
        className="flex md:flex-row justify-between items-center w-full transition-transform duration-300 ease-in-out transform opacity-100 pl-1"
      >
        <TooltipGroup>
          <div className="flex items-center">
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
              data-testid="AgentMessage/copy-button"
            />
            <Button
              icon={SvgThumbsUp}
              onClick={() => handleFeedbackClick("like")}
              variant="select"
              selected={isFeedbackTransient("like")}
              tooltip={
                currentFeedback === "like" ? "Remove Like" : "Good Response"
              }
              data-testid="AgentMessage/like-button"
            />
            <Button
              icon={SvgThumbsDown}
              onClick={() => handleFeedbackClick("dislike")}
              variant="select"
              selected={isFeedbackTransient("dislike")}
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
              <SourcesTagWrapper
                citations={citations}
                documentMap={documentMap}
                nodeId={nodeId}
                selectedMessageForDocDisplay={selectedMessageForDocDisplay}
                documentSidebarVisible={documentSidebarVisible}
                updateCurrentDocumentSidebarVisible={
                  updateCurrentDocumentSidebarVisible
                }
                updateCurrentSelectedNodeForDocDisplay={
                  updateCurrentSelectedNodeForDocDisplay
                }
              />
            )}
          </div>
        </TooltipGroup>
      </div>
    </>
  );
}
