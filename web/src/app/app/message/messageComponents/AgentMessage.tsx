"use client";

import { getToolKey } from "@/app/app/message/messageComponents/toolDisplayHelpers";

import React, { useRef, useMemo, useEffect, useLayoutEffect } from "react";
import {
  Packet,
  PacketType,
  StopReason,
  type UserMessage,
  type GeneratedImage,
} from "@/app/app/services/streamingModels";
import CustomToolAuthCard from "@/app/app/message/messageComponents/CustomToolAuthCard";
import { FullChatState } from "@/app/app/message/messageComponents/types";
import { FeedbackType } from "@/app/app/types";
import { Section } from "@opal/layouts";
import { HumanMessageBubble } from "@/app/app/message/HumanMessage";
import type { TurnGroup } from "@/app/app/message/messageComponents/timeline/transformers";
import type { GroupedPacket } from "@/app/app/message/messageComponents/timeline/hooks/packetProcessor";
import { handleCopy } from "@/app/app/message/copyingUtils";
import { useAuthErrors } from "@/app/app/message/messageComponents/hooks/useAuthErrors";
import { getMessageSwitching } from "@/app/app/message/messageComponents/messageSwitching";
import { RendererComponent } from "@/app/app/message/messageComponents/renderMessageComponent";
import { GeneratedImageGrid } from "@/app/app/message/messageComponents/renderers/ImageToolRenderer";
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

// Type for the regeneration factory function passed from ChatUI
export type RegenerationFactory = (regenerationRequest: {
  messageId: number;
  parentMessage: Message;
  preferSearch?: boolean;
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
}

interface ResponseSection {
  userMessage: UserMessage | null;
  turnIndex: number;
  toolGroups: TurnGroup[];
  displayGroups: GroupedPacket[];
  images: GeneratedImage[];
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
    prev.fullWidthChat === next.fullWidthChat
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
  const answerRefs = useRef<(HTMLDivElement | null)[]>([]);

  // Process streaming packets: returns data and callbacks
  // Hook handles all state internally, exposes clean API
  const {
    citations,
    citationMap,
    documentMap,
    toolGroups,
    toolTurnGroups,
    codeModeWorking,
    displayGroups,
    stopPacketSeen,
    stopReason,
    generatedImages,
    isComplete,
    onRenderComplete,
    finalAnswerComing,
    toolProcessingDuration,
    acceptedPacketCount,
  } = usePacketProcessor(rawPackets, nodeId);

  // Show preceding output in full before revealing an accepted user message.
  const visiblePacketCount = Math.max(restoredPacketCount, acceptedPacketCount);
  const visiblePrefix = useRef<{
    nodeId: number;
    lastPacket: Packet | undefined;
    groups: Map<string, number>;
  }>({ nodeId, lastPacket: undefined, groups: new Map() });
  const lastVisiblePacket =
    rawPackets[Math.min(visiblePacketCount, rawPackets.length) - 1];
  const visibleGroups = useMemo(() => {
    if (
      visiblePrefix.current.nodeId === nodeId &&
      visiblePrefix.current.lastPacket === lastVisiblePacket
    ) {
      return visiblePrefix.current.groups;
    }
    const groups = new Map<string, number>();
    for (const packet of rawPackets.slice(0, visiblePacketCount)) {
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
  }, [nodeId, lastVisiblePacket, rawPackets, visiblePacketCount]);
  useEffect(() => {
    visiblePrefix.current = {
      nodeId,
      lastPacket: lastVisiblePacket,
      groups: visibleGroups,
    };
  }, [nodeId, lastVisiblePacket, visibleGroups]);

  // Apply pacing delays between different tool types for smoother visual transitions
  const { pacedTurnGroups, pacedDisplayGroups, pacedFinalAnswerComing } =
    usePacedTurnGroups(
      toolTurnGroups,
      displayGroups,
      stopPacketSeen,
      nodeId,
      finalAnswerComing,
      visibleGroups
    );

  const sections = useMemo(() => {
    const sections: ResponseSection[] = [
      {
        userMessage: null,
        turnIndex: -1,
        toolGroups: [],
        displayGroups: [],
        images: [],
      },
    ];
    let current = sections[0]!;
    for (const group of pacedDisplayGroups) {
      const input = group.packets[0]?.obj;
      if (input?.type === PacketType.USER_MESSAGE) {
        current = {
          userMessage: input,
          turnIndex: group.turn_index,
          toolGroups: [],
          displayGroups: [],
          images: [],
        };
        sections.push(current);
      } else {
        current.displayGroups.push(group);
      }
    }
    let index = 0;
    for (const group of pacedTurnGroups) {
      while (
        index + 1 < sections.length &&
        group.turnIndex > sections[index + 1]!.turnIndex
      ) {
        index++;
      }
      sections[index]!.toolGroups.push(group);
    }
    for (const image of generatedImages) {
      sections
        .findLast((section) => section.turnIndex < image.turnIndex)!
        .images.push(image);
    }
    return sections;
  }, [pacedDisplayGroups, pacedTurnGroups, generatedImages]);
  const lastAnswerGroup = sections.at(-1)!.displayGroups.at(-1);

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
  const { streamTTS, resetTTS, stopTTS, activeMessageNodeId } = useVoiceMode();
  const activeTTSNodeIdRef = useRef(activeMessageNodeId);
  useEffect(() => {
    activeTTSNodeIdRef.current = activeMessageNodeId;
  }, [activeMessageNodeId]);
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

  // Reset TTS when this message unmounts or its nodeId changes, if it is the
  // one speaking. A chat unmounts rows far from the viewport, and that must
  // not stop another message's audio.
  useEffect(() => {
    return () => {
      if (activeTTSNodeIdRef.current === nodeId) resetTTS();
    };
  }, [nodeId, resetTTS]);

  return (
    <div
      className="flex flex-col gap-3"
      data-testid={isComplete ? "onyx-ai-message" : undefined}
    >
      {sections.map((section, sectionIndex) => {
        const isLastSection = sectionIndex === sections.length - 1;
        return (
          <React.Fragment key={section.userMessage?.id ?? "initial"}>
            {section.userMessage && (
              <Section height="fit" alignItems="end" gap={0}>
                <HumanMessageBubble content={section.userMessage.message} />
              </Section>
            )}

            <AgentTimeline
              turnGroups={section.toolGroups}
              chatState={effectiveChatState}
              stopPacketSeen={stopPacketSeen || !isLastSection}
              stopReason={isLastSection ? stopReason : undefined}
              hasDisplayContent={section.displayGroups.length > 0}
              processingDurationSeconds={processingDurationSeconds}
              generatedImageCount={section.images.length}
              finalAnswerComing={!isLastSection || pacedFinalAnswerComing}
              toolProcessingDuration={toolProcessingDuration}
              codeModeWorking={isLastSection && codeModeWorking}
            />

            {/* Row 2: Display content + MessageToolbar */}
            <div
              data-agent-answer
              className={cn(
                "overflow-x-visible focus:outline-hidden select-text cursor-text",
                !fullWidthChat && "px-3"
              )}
              onCopy={(e) => {
                handleCopy(e, { current: e.currentTarget });
              }}
            >
              {/* Images from every image generation step lead the answer */}
              {section.images.length > 0 && (
                <div className="mb-3">
                  <GeneratedImageGrid images={section.images} />
                </div>
              )}
              {section.displayGroups.length > 0 && (
                <div
                  ref={(element) => {
                    answerRefs.current[sectionIndex] = element;
                  }}
                  className="flex flex-col gap-3"
                >
                  {authErrors
                    .filter(
                      (error) =>
                        error.turnIndex > section.turnIndex &&
                        (isLastSection ||
                          error.turnIndex <
                            sections[sectionIndex + 1]!.turnIndex)
                    )
                    .map((authError, i) => (
                      <CustomToolAuthCard
                        key={`auth-error-${i}`}
                        toolName={authError.toolName}
                        toolId={authError.toolId}
                        tools={effectiveChatState.agent.tools}
                        agentId={effectiveChatState.agent.id}
                      />
                    ))}
                  {section.displayGroups.map((displayGroup) => (
                    <RendererComponent
                      key={getToolKey(
                        displayGroup.turn_index,
                        displayGroup.tab_index
                      )}
                      packets={displayGroup.packets}
                      nestedCalls={displayGroup.nestedCalls}
                      streamPackets={displayGroup.streamPackets}
                      chatState={effectiveChatState}
                      messageNodeId={nodeId}
                      hasTimelineThinking={section.toolGroups.length > 0}
                      onComplete={() => {
                        // Only mark complete on the last display group
                        // Hook handles the finalAnswerComing check internally
                        if (displayGroup === lastAnswerGroup) {
                          onRenderComplete();
                        }
                      }}
                      restoredTextLength={visibleGroups.get(
                        getToolKey(
                          displayGroup.turn_index,
                          displayGroup.tab_index
                        )
                      )}
                      animate={!stopPacketSeen && isLastSection}
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
              {isLastSection &&
                section.displayGroups.length === 0 &&
                stopReason === StopReason.USER_CANCELLED && (
                  <Text as="p" font="secondary-body" color="text-04">
                    {t("agentMessage.stoppedGeneration.text")}
                  </Text>
                )}
              {isLastSection &&
                stopPacketSeen &&
                stopReason === StopReason.TIMED_OUT && (
                  <Text as="p" font="secondary-body" color="text-04">
                    {t("agentMessage.timedOut.text")}
                  </Text>
                )}
            </div>
          </React.Fragment>
        );
      })}

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
          answerRefs={answerRefs}
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
