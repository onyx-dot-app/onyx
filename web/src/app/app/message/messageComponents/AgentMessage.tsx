"use client";

import {
  getToolKey,
  parseToolKey,
} from "@/app/app/message/messageComponents/toolDisplayHelpers";

import React, { useRef, useMemo, useEffect, useLayoutEffect } from "react";
import {
  Packet,
  PacketType,
  StopReason,
  type UserMessage,
  type GeneratedImage,
} from "@/app/app/services/streamingModels";
import CustomToolAuthCard from "@/app/app/message/messageComponents/CustomToolAuthCard";
import ToolApprovalCard from "@/app/app/message/messageComponents/ToolApprovalCard";
import ToolQuestionCard from "@/app/app/message/messageComponents/ToolQuestionCard";
import { FullChatState } from "@/app/app/message/messageComponents/types";
import { FeedbackType } from "@/app/app/types";
import { Section } from "@opal/layouts";
import { HumanMessageBubble } from "@/app/app/message/HumanMessage";
import type { TurnGroup } from "@/lib/timeline/chat/transformers";
import type {
  GroupedPacket,
  PlacedPublishedFile,
} from "@/lib/timeline/chat/hooks/packetProcessor";
import { handleCopy } from "@/app/app/message/copyingUtils";
import {
  type AuthError,
  useAuthErrors,
} from "@/app/app/message/messageComponents/hooks/useAuthErrors";
import { useToolRequests } from "@/lib/chat/hooks";
import type { ToolRequestRecord } from "@/lib/chat/toolApprovals";
import { getMessageSwitching } from "@/app/app/message/messageComponents/messageSwitching";
import { RendererComponent } from "@/app/app/message/messageComponents/renderMessageComponent";
import { GeneratedImageGrid } from "@/app/app/message/messageComponents/renderers/ImageToolRenderer";
import { PublishedFileCards } from "@/sections/chat/PublishedFileCards";
import { usePacketProcessor } from "@/lib/timeline/chat/hooks/usePacketProcessor";
import { usePacedTurnGroups } from "@/lib/timeline/chat/hooks/usePacedTurnGroups";
import MessageToolbar from "@/app/app/message/messageComponents/MessageToolbar";
import { LlmDescriptor, LlmManager } from "@/lib/hooks";
import { Message } from "@/app/app/types";
import { Text } from "@opal/components";
import { AgentTimeline } from "@/lib/timeline/chat/AgentTimeline";
import { responseCursorItem } from "@/lib/timeline/components/ResponseCursor";
import {
  Response,
  ResponseCursorScope,
  type ResponseItem,
} from "@/lib/timeline/components/Response";
import { useVoiceMode } from "@/providers/VoiceModeProvider";
import { getTextContent } from "@/app/app/services/packetUtils";
import { removeThinkingTokens } from "@/app/app/services/thinkingTokens";
import { useTranslations } from "next-intl";

// Type for the regeneration factory function passed from ChatUI
export type RegenerationFactory = (regenerationRequest: {
  messageId: number;
  parentMessage: Message;
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
}

interface ResponseSection {
  userMessage: UserMessage | null;
  turnIndex: number;
  toolGroups: TurnGroup[];
  /** Text that a later step of this section follows. */
  interimGroups: GroupedPacket[];
  displayGroups: GroupedPacket[];
  images: GeneratedImage[];
  publishedFiles: PlacedPublishedFile[];
  authErrors: AuthError[];
  toolRequests: ToolRequestRecord[];
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
    // A replay or reload replaces the array, possibly at the same length.
    prev.rawPackets === next.rawPackets &&
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
    prev.disableTTS === next.disableTTS
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
    interimDisplayGroups,
    stopPacketSeen,
    stopReason,
    generatedImages,
    publishedFiles,
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

  const authErrors = useAuthErrors(rawPackets);
  const toolRequests = useToolRequests(rawPackets);

  const sections = useMemo(() => {
    const sections: ResponseSection[] = [
      {
        userMessage: null,
        turnIndex: -1,
        toolGroups: [],
        interimGroups: [],
        displayGroups: [],
        images: [],
        publishedFiles: [],
        authErrors: [],
        toolRequests: [],
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
          interimGroups: [],
          displayGroups: [],
          images: [],
          publishedFiles: [],
          authErrors: [],
          toolRequests: [],
        };
        sections.push(current);
      } else {
        current.displayGroups.push(group);
      }
    }
    // A message that the user typed to answer questions shows as the user's
    // message after the questions' records; later output follows it. One
    // message answers every question that waits, and those were asked in
    // one turn.
    for (const record of toolRequests.records) {
      if (
        record.kind !== "question" ||
        record.status.kind !== "answered" ||
        record.status.message === null ||
        sections.some((section) => section.turnIndex === record.turnIndex)
      )
        continue;
      const position = sections.findLastIndex(
        (section) => section.turnIndex < record.turnIndex
      );
      const before = sections[position]!;
      sections.splice(position + 1, 0, {
        userMessage: {
          type: PacketType.USER_MESSAGE,
          id: `question:${record.request.question_request_id}`,
          message: record.status.message,
          mentions: [],
        },
        turnIndex: record.turnIndex,
        toolGroups: [],
        interimGroups: [],
        displayGroups: before.displayGroups.filter(
          (group) => group.turn_index > record.turnIndex
        ),
        images: [],
        publishedFiles: [],
        authErrors: [],
        toolRequests: [],
      });
      before.displayGroups = before.displayGroups.filter(
        (group) => group.turn_index <= record.turnIndex
      );
    }
    let index = 0;
    for (const group of pacedTurnGroups) {
      // Timeline turns are renumbered; compare the packet turn of the step.
      const packetTurn = parseToolKey(group.steps[0]!.groupKey).turn_index;
      while (
        index + 1 < sections.length &&
        packetTurn > sections[index + 1]!.turnIndex
      ) {
        index++;
      }
      sections[index]!.toolGroups.push(group);
    }
    for (const group of interimDisplayGroups) {
      sections
        .findLast((section) => section.turnIndex < group.turn_index)!
        .interimGroups.push(group);
    }
    for (const image of generatedImages) {
      sections
        .findLast((section) => section.turnIndex < image.turnIndex)!
        .images.push(image);
    }
    for (const file of publishedFiles) {
      sections
        .findLast((section) => section.turnIndex < file.turnIndex)!
        .publishedFiles.push(file);
    }
    for (const error of authErrors) {
      sections
        .findLast((section) => section.turnIndex < error.turnIndex)!
        .authErrors.push(error);
    }
    for (const record of toolRequests.records) {
      sections
        .findLast((section) => section.turnIndex < record.turnIndex)!
        .toolRequests.push(record);
    }
    return sections;
  }, [
    pacedDisplayGroups,
    pacedTurnGroups,
    interimDisplayGroups,
    generatedImages,
    publishedFiles,
    authErrors,
    toolRequests.records,
  ]);
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

  // The last section's closing line when the user stopped it or it timed out.
  const statusLines = (isLastSection: boolean): ResponseItem[] => {
    if (!isLastSection) return [];
    const lines: ResponseItem[] = [];
    if (
      sections.at(-1)!.displayGroups.length === 0 &&
      stopReason === StopReason.USER_CANCELLED
    ) {
      lines.push({
        kind: "text",
        key: "stopped",
        node: (
          <Text as="p" font="secondary-body" color="text-04">
            {t("agentMessage.stoppedGeneration.text")}
          </Text>
        ),
      });
    }
    if (stopPacketSeen && stopReason === StopReason.TIMED_OUT) {
      lines.push({
        kind: "text",
        key: "timed-out",
        node: (
          <Text as="p" font="secondary-body" color="text-04">
            {t("agentMessage.timedOut.text")}
          </Text>
        ),
      });
    }
    return lines;
  };

  // Copy joins the text blocks of every section, in order.
  let nextAnswerRef = 0;

  return (
    // One cursor for the whole turn, across its sections.
    <ResponseCursorScope>
      <div
        className="flex flex-col gap-3"
        data-testid={isComplete ? "onyx-ai-message" : undefined}
      >
        {sections.map((section, sectionIndex) => {
          const isLastSection = sectionIndex === sections.length - 1;
          const ended = !isLastSection || isComplete;
          const sectionSegments = buildSectionSegments(
            section,
            toolTurnGroups,
            ended
          );
          return (
            <React.Fragment key={section.userMessage?.id ?? "initial"}>
              {section.userMessage && (
                <Section height="fit" alignItems="end" gap={0}>
                  <HumanMessageBubble
                    content={section.userMessage.message}
                    mentions={section.userMessage.mentions}
                  />
                </Section>
              )}

              <Response
                items={[
                  ...sectionSegments
                    .map((segment, index, segments): ResponseItem | null => {
                      switch (segment.kind) {
                        case "text": {
                          const textIndex = nextAnswerRef++;
                          const { group } = segment;
                          return {
                            kind: "text",
                            key: `text-${segment.key}`,
                            node: (
                              <div
                                ref={(element) => {
                                  answerRefs.current[textIndex] = element;
                                }}
                                className="overflow-x-visible focus:outline-hidden select-text cursor-text"
                                onCopy={(e) => {
                                  handleCopy(e, { current: e.currentTarget });
                                }}
                              >
                                <RendererComponent
                                  packets={group.packets}
                                  nestedCalls={group.nestedCalls}
                                  chatState={effectiveChatState}
                                  messageNodeId={nodeId}
                                  hasTimelineThinking={
                                    section.toolGroups.length > 0
                                  }
                                  onComplete={() => {
                                    // The hook checks finalAnswerComing itself.
                                    if (group === lastAnswerGroup)
                                      onRenderComplete();
                                  }}
                                  restoredTextLength={visibleGroups.get(
                                    segment.key
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
                              </div>
                            ),
                          };
                        }
                        case "record":
                          return {
                            kind: "card",
                            key:
                              segment.record.kind === "approval"
                                ? segment.record.request.approval_id
                                : segment.record.request.question_request_id,
                            node:
                              segment.record.kind === "approval" ? (
                                <ToolApprovalCard approval={segment.record} />
                              ) : (
                                <ToolQuestionCard question={segment.record} />
                              ),
                          };
                        case "extras":
                          return {
                            kind: "card",
                            key: "extras",
                            node: (
                              <div className="flex flex-col gap-3">
                                {/* Generated images lead the answer. */}
                                {section.images.length > 0 && (
                                  <GeneratedImageGrid images={section.images} />
                                )}
                                {section.authErrors.map((authError, i) => (
                                  <CustomToolAuthCard
                                    key={`auth-error-${i}`}
                                    toolName={authError.toolName}
                                    toolId={authError.toolId}
                                  />
                                ))}
                              </div>
                            ),
                          };
                        case "files":
                          return {
                            kind: "card",
                            key: "files",
                            node: (
                              <PublishedFileCards
                                files={section.publishedFiles}
                              />
                            ),
                          };
                        case "run": {
                          const awaitingUser = isLastSection
                            ? toolRequests.awaiting
                            : null;
                          // Before its first step, a working response shows
                          // the cursor, as in Craft. A wait for the user and a
                          // running program keep their card.
                          if (
                            segment.turnGroups.length === 0 &&
                            awaitingUser === null &&
                            !(isLastSection && codeModeWorking)
                          ) {
                            const working =
                              isLastSection &&
                              !stopPacketSeen &&
                              !segments.some((s) => s.kind === "text");
                            return working ? responseCursorItem() : null;
                          }
                          const isLiveRun =
                            segments.findLastIndex((s) => s.kind === "run") ===
                            index;
                          if (!isLiveRun) {
                            // A run that text follows has settled.
                            return {
                              kind: "run",
                              key: `run-${segment.key}`,
                              node: (
                                <AgentTimeline
                                  turnGroups={segment.turnGroups}
                                  chatState={effectiveChatState}
                                  stopPacketSeen
                                  hasDisplayContent
                                  finalAnswerComing
                                />
                              ),
                            };
                          }
                          return {
                            kind: "run",
                            key: `run-${segment.key}`,
                            node: (
                              <AgentTimeline
                                turnGroups={segment.turnGroups}
                                chatState={effectiveChatState}
                                stopPacketSeen={
                                  stopPacketSeen || !isLastSection
                                }
                                stopReason={
                                  isLastSection ? stopReason : undefined
                                }
                                // The empty run of a text-only section comes after
                                // the text, which still counts.
                                hasDisplayContent={(segment.turnGroups
                                  .length === 0
                                  ? segments
                                  : segments.slice(index + 1)
                                ).some((s) => s.kind === "text")}
                                processingDurationSeconds={
                                  processingDurationSeconds
                                }
                                generatedImageCount={section.images.length}
                                finalAnswerComing={
                                  !isLastSection || pacedFinalAnswerComing
                                }
                                toolProcessingDuration={toolProcessingDuration}
                                codeModeWorking={
                                  isLastSection && codeModeWorking
                                }
                                awaitingUser={awaitingUser}
                              />
                            ),
                          };
                        }
                      }
                    })
                    .filter((item): item is ResponseItem => item !== null),
                  ...(isLastSection &&
                  !stopPacketSeen &&
                  toolRequests.awaiting === null &&
                  endsWithRun(sectionSegments)
                    ? [responseCursorItem()]
                    : []),
                  ...statusLines(isLastSection),
                ]}
              />
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
    </ResponseCursorScope>
  );
}, arePropsEqual);

export default AgentMessage;

/**
 * The section ends with a run: the turn's cursor waits under it, while its
 * steps run and until what comes next.
 */
function endsWithRun(segments: SectionSegment[]): boolean {
  const last = segments.at(-1);
  return last?.kind === "run" && last.turnGroups.length > 0;
}

type SectionSegment =
  | { kind: "run"; key: string; turnGroups: TurnGroup[] }
  | { kind: "text"; key: string; group: GroupedPacket }
  /** An approval or a question card. */
  | { kind: "record"; record: ToolRequestRecord }
  /** Generated images and auth cards, which lead the section's answer. */
  | { kind: "extras" }
  /** Files from every publish_files call, after the ended section's answer. */
  | { kind: "files" };

/** The packet turn of a timeline turn; code mode renumbers timeline turns. */
function packetTurn(group: TurnGroup): number {
  const step = group.steps[0];
  return step ? parseToolKey(step.groupKey).turn_index : group.turnIndex;
}

/** The key of a section's first run, and of its waiting card before that. */
const LIVE_RUN_KEY = "live";

/**
 * Lays out one response section the way Craft lays out a turn: steps, text,
 * and approval and question cards in arrival (turn) order. Consecutive steps
 * form one run. Text between steps shows once every earlier step of the
 * section is revealed, so it never appears ahead of the steps before it; an
 * earlier section's steps never gate it. The last run holds the live header;
 * a section with no run gets an empty one, which shows the cursor while the
 * response works, and a card while a program runs or it waits for the user.
 * The files that the section published show last, once it `ended`: its
 * response stopped and its answer rendered, or a later section began.
 */
function buildSectionSegments(
  section: ResponseSection,
  allTurnGroups: TurnGroup[],
  ended: boolean
): SectionSegment[] {
  const revealed = new Set(
    section.toolGroups.flatMap((group) => group.steps.map((step) => step.key))
  );
  const interim = section.interimGroups.filter((text) =>
    allTurnGroups.every(
      (group) =>
        packetTurn(group) < section.turnIndex ||
        packetTurn(group) >= text.turn_index ||
        group.steps.every((step) => revealed.has(step.key))
    )
  );

  // At one turn, a step comes before its text, and text before its card.
  type Item =
    | { turn: number; rank: 0; group: TurnGroup }
    | { turn: number; rank: 1; text: GroupedPacket }
    | { turn: number; rank: 2; record: ToolRequestRecord };
  const items: Item[] = [
    ...section.toolGroups.map((group) => ({
      turn: packetTurn(group),
      rank: 0 as const,
      group,
    })),
    ...[...interim, ...section.displayGroups].map((text) => ({
      turn: text.turn_index,
      rank: 1 as const,
      text,
    })),
    ...section.toolRequests.map((record) => ({
      turn: record.turnIndex,
      rank: 2 as const,
      record,
    })),
  ].sort((a, b) => a.turn - b.turn || a.rank - b.rank);

  const segments: SectionSegment[] = [];
  for (const item of items) {
    if ("text" in item) {
      segments.push({
        kind: "text",
        key: getToolKey(item.text.turn_index, item.text.tab_index),
        group: item.text,
      });
    } else if ("record" in item) {
      segments.push({ kind: "record", record: item.record });
    } else {
      const last = segments[segments.length - 1];
      if (last?.kind === "run") last.turnGroups.push(item.group);
      else
        segments.push({
          kind: "run",
          // The first run keeps the waiting card's key, so a wait for the
          // user becomes that run's card instead of being replaced by a new
          // one.
          key: segments.some((s) => s.kind === "run")
            ? (item.group.steps[0]?.key ?? String(item.turn))
            : LIVE_RUN_KEY,
          turnGroups: [item.group],
        });
    }
  }

  if (section.images.length > 0 || section.authErrors.length > 0) {
    // The extras lead the answer: the text after the last run.
    const lastRun = segments.findLastIndex((s) => s.kind === "run");
    const answer = segments.findIndex(
      (s, i) => i > lastRun && s.kind === "text"
    );
    segments.splice(answer === -1 ? segments.length : answer, 0, {
      kind: "extras",
    });
  }
  if (!segments.some((s) => s.kind === "run")) {
    segments.push({ kind: "run", key: LIVE_RUN_KEY, turnGroups: [] });
  }
  if (ended && section.publishedFiles.length > 0) {
    segments.push({ kind: "files" });
  }
  return segments;
}
