"use client";

import React, {
  useRef,
  RefObject,
  useMemo,
  useEffect,
  useLayoutEffect,
} from "react";
import { Packet, StopReason } from "@/app/app/services/streamingModels";
import CustomToolAuthCard from "@/app/app/message/messageComponents/CustomToolAuthCard";
import { FullChatState } from "@/app/app/message/messageComponents/interfaces";
import { FeedbackType } from "@/app/app/interfaces";
import { handleCopy } from "@/app/app/message/copyingUtils";
import { useAuthErrors } from "@/app/app/message/messageComponents/hooks/useAuthErrors";
import { useMessageSwitching } from "@/app/app/message/messageComponents/hooks/useMessageSwitching";
import { RendererComponent } from "@/app/app/message/messageComponents/renderMessageComponent";
import { usePacketProcessor } from "@/app/app/message/messageComponents/timeline/hooks/usePacketProcessor";
import { usePacedTurnGroups } from "@/app/app/message/messageComponents/timeline/hooks/usePacedTurnGroups";
import MessageToolbar from "@/app/app/message/messageComponents/MessageToolbar";
import { LlmDescriptor, LlmManager } from "@/lib/hooks";
import { Message } from "@/app/app/interfaces";
import Text from "@/refresh-components/texts/Text";
import { AgentTimeline } from "@/app/app/message/messageComponents/timeline/AgentTimeline";
import { useVoiceMode } from "@/providers/VoiceModeProvider";
import { getTextContent } from "@/app/app/services/packetUtils";
import { removeThinkingTokens } from "@/app/app/services/thinkingTokens";

// Type for the regeneration factory function passed from ChatUI
export type RegenerationFactory = (regenerationRequest: {
  messageId: number;
  parentMessage: Message;
  forceSearch?: boolean;
}) => (modelOverride: LlmDescriptor) => Promise<void>;

export interface AgentMessageProps {
  rawPackets: Packet[];
  packetCount?: number; // Tracked separately for React memo comparison (avoids reading from mutated array)
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
  // Duration in seconds for processing this message (agent messages only)
  processingDurationSeconds?: number;
  /** Hide the feedback/toolbar footer (used in multi-model non-preferred panels) */
  hideFooter?: boolean;
  /** Skip TTS streaming (used in multi-model where voice doesn't apply) */
  disableTTS?: boolean;
}

// TODO: Consider more robust comparisons:
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
    // Compare packetCount (primitive) instead of rawPackets.length
    // The array is mutated in place, so reading .length from prev and next would return same value
    prev.packetCount === next.packetCount &&
    prev.chatState.agent?.id === next.chatState.agent?.id &&
    prev.chatState.docs === next.chatState.docs &&
    prev.chatState.citations === next.chatState.citations &&
    prev.chatState.overriddenModel === next.chatState.overriddenModel &&
    prev.chatState.researchType === next.chatState.researchType &&
    prev.otherMessagesCanSwitchTo === next.otherMessagesCanSwitchTo &&
    prev.onRegenerate === next.onRegenerate &&
    prev.parentMessage?.messageId === next.parentMessage?.messageId &&
    prev.llmManager?.isLoadingProviders ===
      next.llmManager?.isLoadingProviders &&
    prev.processingDurationSeconds === next.processingDurationSeconds &&
    prev.hideFooter === next.hideFooter
    // Skip: chatState.regenerate, chatState.setPresentingDocument,
    //       most of llmManager, onMessageSelection (function/object props)
  );
}

const AgentMessage = React.memo(function AgentMessage({
  rawPackets,
  packetCount,
  chatState,
  nodeId,
  messageId,
  currentFeedback,
  llmManager,
  otherMessagesCanSwitchTo,
  onMessageSelection,
  onRegenerate,
  parentMessage,
  processingDurationSeconds,
  hideFooter,
  disableTTS,
}: AgentMessageProps) {
  const markdownRef = useRef<HTMLDivElement>(null);
  const finalAnswerRef = useRef<HTMLDivElement>(null);

  // Process streaming packets: returns data and callbacks
  // Hook handles all state internally, exposes clean API
  const {
    citations,
    citationMap,
    documentMap,
    toolGroups,
    toolTurnGroups,
    displayGroups,
    hasSteps,
    stopPacketSeen,
    stopReason,
    isGeneratingImage,
    generatedImageCount,
    isComplete,
    onRenderComplete,
    finalAnswerComing,
    toolProcessingDuration,
  } = usePacketProcessor(rawPackets, nodeId);

  // Apply pacing delays between different tool types for smoother visual transitions
  const { pacedTurnGroups, pacedDisplayGroups, pacedFinalAnswerComing } =
    usePacedTurnGroups(
      toolTurnGroups,
      displayGroups,
      stopPacketSeen,
      nodeId,
      finalAnswerComing
    );

  // Memoize merged citations separately to avoid creating new object when neither source changed
  const mergedCitations = useMemo(
    () => ({
      ...chatState.citations,
      ...citationMap,
    }),
    [chatState.citations, citationMap]
  );

  // Create a chatState that uses streaming citations for immediate rendering
  // This merges the prop citations with streaming citations, preferring streaming ones
  // Memoized with granular dependencies to prevent cascading re-renders
  // Note: chatState object is recreated upstream on every render, so we depend on
  // individual fields instead of the whole object for proper memoization
  const effectiveChatState = useMemo<FullChatState>(
    () => ({
      ...chatState,
      citations: mergedCitations,
    }),
    [
      chatState.agent,
      chatState.docs,
      chatState.setPresentingDocument,
      chatState.overriddenModel,
      chatState.researchType,
      mergedCitations,
    ]
  );

  const authErrors = useAuthErrors(rawPackets);

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

  // Streaming TTS integration
  const { streamTTS, resetTTS, stopTTS } = useVoiceMode();
  const ttsCompletedRef = useRef(false);
  const hasStreamedIncompleteRef = useRef(false);
  const hasObservedPacketGrowthRef = useRef(false);
  const lastSeenPacketCountRef = useRef(packetCount ?? rawPackets.length);
  const streamTTSRef = useRef(streamTTS);

  // Keep streamTTS ref in sync without triggering effect re-runs
  useEffect(() => {
    streamTTSRef.current = streamTTS;
  }, [streamTTS]);

  // Stream TTS as text content arrives - only for messages still streaming
  // Uses ref for streamTTS to avoid re-triggering when its identity changes
  // Note: packetCount is used instead of rawPackets because the array is mutated in place
  useLayoutEffect(() => {
    const effectivePacketCount = packetCount ?? rawPackets.length;
    if (effectivePacketCount > lastSeenPacketCountRef.current) {
      hasObservedPacketGrowthRef.current = true;
    }
    lastSeenPacketCountRef.current = effectivePacketCount;

    // Skip if we've already finished TTS for this message
    if (ttsCompletedRef.current) return;

    // Multi-model: skip TTS entirely
    if (disableTTS) return;

    // If user cancelled generation, do not send more text to TTS.
    if (stopPacketSeen && stopReason === StopReason.USER_CANCELLED) {
      ttsCompletedRef.current = true;
      return;
    }

    const textContent = removeThinkingTokens(getTextContent(rawPackets));
    if (!(typeof textContent === "string" && textContent.length > 0)) return;

    // Only autoplay messages that were observed streaming in this lifecycle.
    // Prevents historical, already-complete chats from re-triggering read-aloud on mount.
    if (!isComplete) {
      if (!hasObservedPacketGrowthRef.current) {
        return;
      }
      hasStreamedIncompleteRef.current = true;
      streamTTSRef.current(textContent, false, nodeId);
      return;
    }

    if (hasStreamedIncompleteRef.current) {
      streamTTSRef.current(textContent, true, nodeId);
      ttsCompletedRef.current = true;
    }
  }, [packetCount, isComplete, rawPackets, nodeId, stopPacketSeen, stopReason]); // packetCount triggers on new packets since rawPackets is mutated in place

  // Stop TTS immediately when user cancels generation.
  useEffect(() => {
    if (stopPacketSeen && stopReason === StopReason.USER_CANCELLED) {
      stopTTS({ manual: true });
    }
  }, [stopPacketSeen, stopReason, stopTTS]);

  // Reset TTS completed flag when nodeId changes (new message)
  useEffect(() => {
    ttsCompletedRef.current = false;
    hasStreamedIncompleteRef.current = false;
    hasObservedPacketGrowthRef.current = false;
    lastSeenPacketCountRef.current = packetCount ?? rawPackets.length;
  }, [nodeId]);

  // Reset TTS when component unmounts or nodeId changes
  useEffect(() => {
    return () => {
      resetTTS();
    };
  }, [nodeId, resetTTS]);

  return (
    <div
      className="flex flex-col gap-3"
      data-testid={isComplete ? "onyx-ai-message" : undefined}
    >
      {/* Row 1: Two-column layout for tool steps */}

      <AgentTimeline
        turnGroups={pacedTurnGroups}
        chatState={effectiveChatState}
        stopPacketSeen={stopPacketSeen}
        stopReason={stopReason}
        hasDisplayContent={pacedDisplayGroups.length > 0}
        processingDurationSeconds={processingDurationSeconds}
        isGeneratingImage={isGeneratingImage}
        generatedImageCount={generatedImageCount}
        finalAnswerComing={pacedFinalAnswerComing}
        toolProcessingDuration={toolProcessingDuration}
      />

      {/* Row 2: Display content + MessageToolbar */}
      <div
        ref={markdownRef}
        className="overflow-x-visible focus:outline-none select-text cursor-text px-3"
        onCopy={(e) => {
          if (markdownRef.current) {
            handleCopy(e, markdownRef as RefObject<HTMLDivElement>);
          }
        }}
      >
        {pacedDisplayGroups.length > 0 && (
          <div ref={finalAnswerRef} className="flex flex-col gap-3">
            {authErrors.map((authError, i) => (
              <CustomToolAuthCard
                key={`auth-error-${i}`}
                toolName={authError.toolName}
                toolId={authError.toolId}
                tools={effectiveChatState.agent.tools}
                agentId={effectiveChatState.agent.id}
              />
            ))}
            {pacedDisplayGroups.map((displayGroup, index) => (
              <RendererComponent
                key={`${displayGroup.turn_index}-${displayGroup.tab_index}`}
                packets={displayGroup.packets}
                chatState={effectiveChatState}
                messageNodeId={nodeId}
                hasTimelineThinking={pacedTurnGroups.length > 0 || hasSteps}
                onComplete={() => {
                  // Only mark complete on the last display group
                  // Hook handles the finalAnswerComing check internally
                  if (index === pacedDisplayGroups.length - 1) {
                    onRenderComplete();
                  }
                }}
                animate={!stopPacketSeen}
                stopPacketSeen={stopPacketSeen}
                stopReason={stopReason}
              >
                {(results) => (
                  <>
                    {results.map((r, i) => (
                      <div key={i}>{r.content}</div>
                    ))}
                  </>
                )}
              </RendererComponent>
            ))}
          </div>
        )}
        {/* Show stopped message when user cancelled and no display content */}
        {pacedDisplayGroups.length === 0 &&
          stopReason === StopReason.USER_CANCELLED && (
            <Text as="p" secondaryBody text04>
              User has stopped generation
            </Text>
          )}
      </div>

      {/* Feedback buttons - only show when streaming and rendering complete */}
      {isComplete && !hideFooter && (
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
