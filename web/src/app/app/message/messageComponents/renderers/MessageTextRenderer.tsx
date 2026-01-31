"use client";

import React, { useEffect, useMemo, useRef } from "react";
import Text from "@/refresh-components/texts/Text";

import {
  ChatPacket,
  PacketType,
  StopReason,
} from "../../../services/streamingModels";
import { MessageRenderer, FullChatState } from "../interfaces";
import { isFinalAnswerComplete } from "../../../services/packetUtils";
import { useMarkdownRenderer } from "../markdownUtils";
import { BlinkingDot } from "../../BlinkingDot";
import {
  useSteadyReveal,
  type SteadyRevealOptions,
} from "../hooks/useSteadyReveal";
import { useThrottledValue } from "../hooks/useThrottledValue";

const STREAMING_MARKDOWN_THROTTLE_FAST_MS = 16;
const STREAMING_MARKDOWN_THROTTLE_SLOW_MS = 80;

const STEADY_REVEAL_STREAMING_OPTIONS: SteadyRevealOptions = {
  baseCharsPerSecond: 650,
  catchUpCharsPerSecond: 6000,
  backlogCatchUpThresholdChars: 80,
  maxCharsPerFrame: 4000,
  minCharsPerFrame: 12,
};

function getPacketText(packet: unknown): string {
  const maybe = packet as { obj?: { type?: string; content?: string } };
  if (!maybe?.obj || !maybe.obj.type) {
    throw new Error("Malformed chat packet: missing obj.type");
  }
  const type = maybe?.obj?.type;
  if (type === PacketType.MESSAGE_START || type === PacketType.MESSAGE_DELTA) {
    return maybe.obj?.content ?? "";
  }
  return "";
}

function getFirstMessageStartId(packets: unknown[]): string | null {
  for (const packet of packets) {
    const maybe = packet as { obj?: { type?: string; id?: string } };
    if (!maybe?.obj || !maybe.obj.type) {
      throw new Error("Malformed chat packet: missing obj.type");
    }
    if (maybe?.obj?.type === PacketType.MESSAGE_START) {
      return maybe.obj?.id ?? null;
    }
  }
  return null;
}

export const MessageTextRenderer: MessageRenderer<
  ChatPacket,
  FullChatState
> = ({
  packets,
  state,
  onComplete,
  renderType: _renderType,
  animate,
  stopPacketSeen,
  stopReason,
  children,
}) => {
  // Build text incrementally: avoid re-scanning all packets on every update.
  // Note: packet groups can include non-chat packets (e.g. SECTION_END), so we
  // defensively extract only MESSAGE_START / MESSAGE_DELTA content.
  const accumulatedTextRef = useRef<string>("");
  const processedPacketsRef = useRef<number>(0);
  const messageStartIdRef = useRef<string | null>(null);

  const { fullContent, nextProcessedCount, nextMessageStartId, shouldReset } =
    useMemo(() => {
      const packetsAny = packets as unknown[];
      const currentMessageStartId = getFirstMessageStartId(packetsAny);

      const prevProcessed = processedPacketsRef.current;
      const prevMessageStartId = messageStartIdRef.current;

      const packetsShrank = packetsAny.length < prevProcessed;
      const messageStartIdChanged =
        prevMessageStartId != null &&
        currentMessageStartId != null &&
        prevMessageStartId !== currentMessageStartId;
      const lostMessageStart =
        prevMessageStartId != null && currentMessageStartId == null;

      const shouldReset =
        packetsShrank || messageStartIdChanged || lostMessageStart;

      const baseText = shouldReset ? "" : accumulatedTextRef.current;
      const startIdx = shouldReset ? 0 : prevProcessed;

      let appended = "";
      for (let i = startIdx; i < packetsAny.length; i++) {
        appended += getPacketText(packetsAny[i]);
      }

      return {
        fullContent: baseText + appended,
        nextProcessedCount: packetsAny.length,
        nextMessageStartId: currentMessageStartId,
        shouldReset,
      };
    }, [packets]);

  // Commit refs after render (safe under StrictMode double-invocation).
  useEffect(() => {
    accumulatedTextRef.current = fullContent;
    processedPacketsRef.current = nextProcessedCount;
    messageStartIdRef.current = nextMessageStartId;
  }, [fullContent, nextProcessedCount, nextMessageStartId]);

  const isFinalAnswerSectionComplete = isFinalAnswerComplete(packets);
  const isDone = stopPacketSeen || isFinalAnswerSectionComplete;

  // Reveal at a steady pace while streaming, independent of backend chunk cadence.
  // If `animate` is off, this hook returns the full content immediately (no RAF loop).
  const { revealedText, isCaughtUp } = useSteadyReveal(fullContent, {
    enabled: animate,
    isDone,
    options: STEADY_REVEAL_STREAMING_OPTIONS,
  });

  // Throttle markdown parsing/highlighting work while streaming.
  // Adaptive: keep it snappy for short outputs, but reduce CPU for long/backlogged streams.
  const markdownThrottleMs = useMemo(() => {
    if (isDone) return 0;
    const backlogChars = fullContent.length - revealedText.length;

    // Small content / small backlog: keep up at ~60fps.
    if (fullContent.length <= 800 && backlogChars <= 200) {
      return STREAMING_MARKDOWN_THROTTLE_FAST_MS;
    }

    // Large content or large backlog: throttle more aggressively.
    if (fullContent.length >= 4000 || backlogChars >= 1200) {
      return STREAMING_MARKDOWN_THROTTLE_SLOW_MS;
    }

    // Middle ground.
    return 50;
  }, [isDone, fullContent.length, revealedText.length]);

  const throttledRevealedText = useThrottledValue(
    revealedText,
    markdownThrottleMs
  );

  const { renderedContent } = useMarkdownRenderer(
    throttledRevealedText,
    state,
    "font-main-content-body"
  );

  const wasUserCancelled = stopReason === StopReason.USER_CANCELLED;
  const completionCalledRef = useRef(false);

  // Reset completion tracking when message identity changes.
  const completionMessageStartIdRef = useRef<string | null>(nextMessageStartId);
  useEffect(() => {
    if (
      shouldReset ||
      completionMessageStartIdRef.current !== nextMessageStartId
    ) {
      completionCalledRef.current = false;
      completionMessageStartIdRef.current = nextMessageStartId;
    }
  }, [shouldReset, nextMessageStartId]);

  // Mark as complete when:
  // 1. Normal completion: final answer section is complete AND we have displayed it, OR
  // 2. Edge case: stream stopped before any content was generated (e.g., user cancelled immediately)
  useEffect(() => {
    if (completionCalledRef.current) return;

    // Normal completion: final answer section complete and displayed
    const normalCompletion = isFinalAnswerSectionComplete && isCaughtUp;

    // Edge case: stream stopped before any content was generated
    // (isFinalAnswerComplete returns false if no MESSAGE_START exists)
    const emptyStopCompletion = stopPacketSeen && fullContent.length === 0;

    if (normalCompletion || emptyStopCompletion) {
      completionCalledRef.current = true;
      onComplete();
    }
  }, [
    isFinalAnswerSectionComplete,
    isCaughtUp,
    stopPacketSeen,
    fullContent.length,
    onComplete,
  ]);

  // Keep the typing indicator stable while streaming.
  // If we tie it to "caught up", it will toggle on/off as new packets arrive
  // (we catch up, then the target grows), which looks like flicker.
  const showTypingIndicator = !isDone;
  const typingIndicator = (
    <div
      style={{
        opacity: showTypingIndicator ? 1 : 0,
        visibility: showTypingIndicator ? "visible" : "hidden",
        transition: "opacity 120ms ease-out",
      }}
    >
      <BlinkingDot addMargin />
    </div>
  );

  return children({
    icon: null,
    status: null,
    content:
      throttledRevealedText.length > 0 ? (
        <>
          {renderedContent}
          {typingIndicator}
          {wasUserCancelled && (
            <Text as="p" secondaryBody text04>
              User has stopped generation
            </Text>
          )}
        </>
      ) : wasUserCancelled ? (
        <Text as="p" secondaryBody text04>
          User has stopped generation
        </Text>
      ) : (
        typingIndicator
      ),
  });
};
