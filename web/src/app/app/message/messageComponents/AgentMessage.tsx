"use client";

import { getToolKey } from "@/app/app/message/messageComponents/toolDisplayHelpers";

import React, {
  useRef,
  RefObject,
  useMemo,
  useEffect,
  useLayoutEffect,
} from "react";
import {
  Packet,
  PacketType,
  StopReason,
} from "@/app/app/services/streamingModels";
import CustomToolAuthCard from "@/app/app/message/messageComponents/CustomToolAuthCard";
import { FullChatState } from "@/app/app/message/messageComponents/types";
import { FeedbackType } from "@/app/app/types";
import { handleCopy } from "@/app/app/message/copyingUtils";
import { useAuthErrors } from "@/app/app/message/messageComponents/hooks/useAuthErrors";
import { getMessageSwitching } from "@/app/app/message/messageComponents/messageSwitching";
import { RendererComponent } from "@/app/app/message/messageComponents/renderMessageComponent";
import { usePacketProcessor } from "@/app/app/message/messageComponents/timeline/hooks/usePacketProcessor";
import { usePacedTurnGroups } from "@/app/app/message/messageComponents/timeline/hooks/usePacedTurnGroups";
import MessageToolbar from "@/app/app/message/messageComponents/MessageToolbar";
import { LlmDescriptor, LlmManager } from "@/lib/hooks";
import { Message } from "@/app/app/types";
import { Text } from "@opal/components";
import { AgentTimeline } from "@/app/app/message/messageComponents/timeline/AgentTimeline";
import { useVoiceMode } from "@/providers/VoiceModeProvider";
import { getTextContent } from "@/app/app/services/packetUtils";
import { removeThinkingTokens } from "@/app/app/services/thinkingTokens";
import { cn } from "@opal/utils";
import { useTranslations } from "next-intl";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { getLatestMessageChain } from "@/app/app/services/messageTree";

// Type for the regeneration factory function passed from ChatUI
export type RegenerationFactory = (regenerationRequest: {
  messageId: number;
  parentMessage: Message;
  forceSearch?: boolean;
}) => (modelOverride: LlmDescriptor) => Promise<void>;

export interface AgentMessageProps {
  rawPackets: Packet[];
  restoredPacketCount?: number;
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
  /** Disable autoplay for non-primary or failed responses. */
  disableTTS?: boolean;
  /** When on, drop the message's reading-width padding so it sits flush with the chat edge. */
  fullWidthChat?: boolean;
  onComplete?: (nodeId: number) => void;
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
    prev.restoredPacketCount === next.restoredPacketCount &&
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
    prev.hideFooter === next.hideFooter &&
    prev.disableTTS === next.disableTTS &&
    prev.fullWidthChat === next.fullWidthChat &&
    prev.onComplete === next.onComplete
    // Skip: chatState.regenerate, chatState.setPresentingDocument,
    //       most of llmManager, onMessageSelection (function/object props)
  );
}

const AgentMessage = React.memo(function AgentMessage({
  rawPackets,
  packetCount,
  restoredPacketCount: replayPacketCount = 0,
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
  fullWidthChat,
  onComplete,
}: AgentMessageProps) {
  // Returning to a mounted session restores its retained output immediately.
  const mountedPrefix = useRef({ nodeId, count: rawPackets.length });
  const mounted =
    mountedPrefix.current.nodeId === nodeId
      ? mountedPrefix.current
      : { nodeId, count: rawPackets.length };
  useEffect(() => {
    mountedPrefix.current = mounted;
  }, [mounted]);
  const restoredPacketCount = Math.max(replayPacketCount, mounted.count);
  const t = useTranslations("chat.messages");
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

  const sessionIdAtMount = useRef(
    useChatSessionStore.getState().currentSessionId
  );
  const requestAtMount = useRef(
    useChatSessionStore.getState().sessions.get(sessionIdAtMount.current ?? "")
      ?.abortController
  );
  useEffect(() => {
    if (!isComplete) return;
    if (onComplete) {
      onComplete(nodeId);
      return;
    }
    const sessionId = sessionIdAtMount.current;
    if (!sessionId) return;
    const store = useChatSessionStore.getState();
    const session = store.sessions.get(sessionId);
    if (
      !session ||
      session.abortController !== requestAtMount.current ||
      session.chatState === "loading"
    )
      return;
    if (getLatestMessageChain(session.messageTree).at(-1)?.nodeId === nodeId) {
      store.setLatestMessageRenderComplete(sessionId, true);
    }
  }, [isComplete, nodeId, onComplete]);

  const restoredPrefix = useRef<{
    nodeId: number;
    lastPacket: Packet | undefined;
    groups: Map<string, number>;
  }>({ nodeId, lastPacket: undefined, groups: new Map() });
  const lastRestoredPacket =
    rawPackets[Math.min(restoredPacketCount, rawPackets.length) - 1];
  const restoredGroups = useMemo(() => {
    if (
      restoredPrefix.current.nodeId === nodeId &&
      restoredPrefix.current.lastPacket === lastRestoredPacket
    ) {
      return restoredPrefix.current.groups;
    }
    const groups = new Map<string, number>();
    for (const packet of rawPackets.slice(0, restoredPacketCount)) {
      const key = getToolKey(
        packet.placement.turn_index,
        packet.placement.tab_index
      );
      const textLength =
        packet.obj.type === PacketType.MESSAGE_DELTA ||
        packet.obj.type === PacketType.MESSAGE_START
          ? (packet.obj.content?.length ?? 0)
          : 0;
      groups.set(key, (groups.get(key) ?? 0) + textLength);
    }
    return groups;
  }, [nodeId, lastRestoredPacket, rawPackets, restoredPacketCount]);
  useEffect(() => {
    restoredPrefix.current = {
      nodeId,
      lastPacket: lastRestoredPacket,
      groups: restoredGroups,
    };
  }, [nodeId, lastRestoredPacket, restoredGroups]);

  // Apply pacing delays between different tool types for smoother visual transitions
  const { pacedTurnGroups, pacedDisplayGroups, pacedFinalAnswerComing } =
    usePacedTurnGroups(
      toolTurnGroups,
      displayGroups,
      stopPacketSeen,
      nodeId,
      finalAnswerComing,
      restoredGroups
    );

  // Merge streaming citation/document data with chatState props.
  // NOTE: citationMap and documentMap from usePacketProcessor are mutated in
  // place (same object reference), so we use citations.length / documentMap.size
  // as change-detection proxies to bust the memo cache when new data arrives.
  const mergedCitations = useMemo(
    () => ({
      ...chatState.citations,
      ...citationMap,
    }),
    [chatState.citations, citationMap, citations.length]
  );

  // Merge streaming documentMap into chatState.docs so inline citation chips
  // can resolve [1] → document even when chatState.docs is empty (multi-model).
  const mergedDocs = useMemo(() => {
    const propDocs = chatState.docs ?? [];
    if (documentMap.size === 0) return propDocs;
    const seen = new Set(propDocs.map((d) => d.document_id));
    const extras = Array.from(documentMap.values()).filter(
      (d) => !seen.has(d.document_id)
    );
    return extras.length > 0 ? [...propDocs, ...extras] : propDocs;
  }, [chatState.docs, documentMap, documentMap.size]);

  // Create a chatState that uses streaming citations and documents for immediate rendering.
  // Memoized with granular dependencies to prevent cascading re-renders.
  // Note: chatState object is recreated upstream on every render, so we depend on
  // individual fields instead of the whole object for proper memoization.
  const effectiveChatState = useMemo<FullChatState>(
    () => ({
      ...chatState,
      citations: mergedCitations,
      docs: mergedDocs,
    }),
    [
      chatState.agent,
      chatState.setPresentingDocument,
      chatState.overriddenModel,
      chatState.researchType,
      mergedCitations,
      mergedDocs,
    ]
  );

  const authErrors = useAuthErrors(rawPackets);

  const {
    currentMessageInd,
    includeMessageSwitcher,
    getPreviousMessage,
    getNextMessage,
  } = getMessageSwitching({
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

    // A failed answer must close any autoplay session it already started.
    if (disableTTS) {
      if (hasStreamedIncompleteRef.current) {
        stopTTS();
        ttsCompletedRef.current = true;
      }
      return;
    }
    // Autoplay belongs to locally started answers, not restored history.
    if (replayPacketCount > 0) return;

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
  }, [
    disableTTS,
    stopTTS,
    packetCount,
    replayPacketCount,
    isComplete,
    rawPackets,
    nodeId,
    stopPacketSeen,
    stopReason,
  ]); // packetCount triggers on new packets since rawPackets is mutated in place

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
        className={cn(
          "overflow-x-visible focus:outline-hidden select-text cursor-text",
          !fullWidthChat && "px-3"
        )}
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
                key={getToolKey(
                  displayGroup.turn_index,
                  displayGroup.tab_index
                )}
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
                restoredTextLength={restoredGroups.get(
                  getToolKey(displayGroup.turn_index, displayGroup.tab_index)
                )}
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
            <Text as="p" font="secondary-body" color="text-04">
              {t("agentMessage.stoppedGeneration.text")}
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
          currentModelProvider={chatState.overriddenModelProvider}
          citations={citations}
          documentMap={documentMap}
        />
      )}
    </div>
  );
}, arePropsEqual);

export default AgentMessage;
