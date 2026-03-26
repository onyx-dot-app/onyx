import React, { useEffect, useMemo, useRef, useState } from "react";
// TODO(@raunakab): migrate this `refresh-components/Text` to `@opal/components` Text
import Text from "@/refresh-components/texts/Text";

import {
  ChatPacket,
  PacketType,
  StopReason,
} from "../../../services/streamingModels";
import { MessageRenderer, FullChatState } from "../interfaces";
import { isFinalAnswerComplete } from "../../../services/packetUtils";
import { useMarkdownRenderer } from "../markdownUtils";
import { BlinkingBar } from "../../BlinkingBar";
import { useVoiceMode } from "@/providers/VoiceModeProvider";

/**
 * Maps a cleaned character position to the corresponding position in markdown text.
 * This allows progressive reveal to work with markdown formatting.
 */
function getRevealPosition(markdown: string, cleanChars: number): number {
  // Skip patterns that don't contribute to visible character count
  const skipChars = new Set(["*", "`", "#"]);
  let cleanIndex = 0;
  let mdIndex = 0;

  while (cleanIndex < cleanChars && mdIndex < markdown.length) {
    const char = markdown[mdIndex];

    // Skip markdown formatting characters
    if (char !== undefined && skipChars.has(char)) {
      mdIndex++;
      continue;
    }

    // Handle link syntax [text](url) - skip the (url) part but count the text
    if (
      char === "]" &&
      mdIndex + 1 < markdown.length &&
      markdown[mdIndex + 1] === "("
    ) {
      const closeIdx = markdown.indexOf(")", mdIndex + 2);
      if (closeIdx > 0) {
        mdIndex = closeIdx + 1;
        continue;
      }
    }

    cleanIndex++;
    mdIndex++;
  }

  // Extend to word boundary to avoid cutting mid-word
  while (
    mdIndex < markdown.length &&
    markdown[mdIndex] !== " " &&
    markdown[mdIndex] !== "\n"
  ) {
    mdIndex++;
  }

  return mdIndex;
}

// Control the rate of packet streaming (packets per second)
const PACKET_DELAY_MS = 10;

export const MessageTextRenderer: MessageRenderer<
  ChatPacket,
  FullChatState
> = ({
  packets,
  state,
  messageNodeId,
  hasTimelineThinking,
  onComplete,
  renderType,
  animate,
  stopPacketSeen,
  stopReason,
  children,
}) => {
  // If we're animating and the final answer is already complete, show more packets initially
  const initialPacketCount = animate
    ? packets.length > 0
      ? 1 // Otherwise start with 1 packet
      : 0
    : -1; // Show all if not animating

  const [displayedPacketCount, setDisplayedPacketCount] =
    useState(initialPacketCount);
  const lastStableSyncedContentRef = useRef("");
  const lastVisibleContentRef = useRef("");

  // Get voice mode context for progressive text reveal synced with audio
  const {
    revealedCharCount,
    autoPlayback,
    isAudioSyncActive,
    activeMessageNodeId,
    isAwaitingAutoPlaybackStart,
  } = useVoiceMode();

  // Get the full content from all packets
  const fullContent = packets
    .map((packet) => {
      if (
        packet.obj.type === PacketType.MESSAGE_DELTA ||
        packet.obj.type === PacketType.MESSAGE_START
      ) {
        return packet.obj.content;
      }
      return "";
    })
    .join("");

  const shouldUseAutoPlaybackSync =
    autoPlayback &&
    typeof messageNodeId === "number" &&
    activeMessageNodeId === messageNodeId;

  // Animation effect - gradually increase displayed packets at controlled rate
  useEffect(() => {
    if (!animate) {
      setDisplayedPacketCount(-1); // Show all packets
      return;
    }

    if (displayedPacketCount >= 0 && displayedPacketCount < packets.length) {
      const timer = setTimeout(() => {
        setDisplayedPacketCount((prev) => Math.min(prev + 1, packets.length));
      }, PACKET_DELAY_MS);

      return () => clearTimeout(timer);
    }
  }, [animate, displayedPacketCount, packets.length]);

  // Reset displayed count when packet array changes significantly (e.g., new message)
  useEffect(() => {
    if (animate && packets.length < displayedPacketCount) {
      const resetCount = isFinalAnswerComplete(packets)
        ? Math.min(10, packets.length)
        : packets.length > 0
          ? 1
          : 0;
      setDisplayedPacketCount(resetCount);
    }
  }, [animate, packets.length, displayedPacketCount]);

  // Only mark as complete when all packets are received AND displayed
  useEffect(() => {
    if (isFinalAnswerComplete(packets)) {
      // If animating, wait until all packets are displayed
      if (
        animate &&
        displayedPacketCount >= 0 &&
        displayedPacketCount < packets.length
      ) {
        return;
      }
      onComplete();
    }
  }, [packets, onComplete, animate, displayedPacketCount]);

  // Get content based on displayed packet count or audio progress
  const computedContent = useMemo(() => {
    // Hold response in "thinking" state only while autoplay startup is pending.
    if (shouldUseAutoPlaybackSync && isAwaitingAutoPlaybackStart) {
      return "";
    }

    // Sync text with audio only for the message currently being spoken.
    if (shouldUseAutoPlaybackSync && isAudioSyncActive) {
      const MIN_REVEAL_CHARS = 12;
      if (revealedCharCount < MIN_REVEAL_CHARS) {
        return "";
      }

      // Reveal text progressively based on audio progress
      const revealPos = getRevealPosition(fullContent, revealedCharCount);
      return fullContent.slice(0, Math.max(revealPos, 0));
    }

    // During an active synced turn, if sync temporarily drops, keep current reveal
    // instead of jumping to full content or blanking.
    if (shouldUseAutoPlaybackSync && !stopPacketSeen) {
      return lastStableSyncedContentRef.current;
    }

    // Standard behavior when auto-playback is off
    if (!animate || displayedPacketCount === -1) {
      return fullContent; // Show all content
    }

    // Packet-based reveal (when auto-playback is disabled)
    return packets
      .slice(0, displayedPacketCount)
      .map((packet) => {
        if (
          packet.obj.type === PacketType.MESSAGE_DELTA ||
          packet.obj.type === PacketType.MESSAGE_START
        ) {
          return packet.obj.content;
        }
        return "";
      })
      .join("");
  }, [
    animate,
    displayedPacketCount,
    fullContent,
    packets,
    revealedCharCount,
    autoPlayback,
    isAudioSyncActive,
    activeMessageNodeId,
    isAwaitingAutoPlaybackStart,
    messageNodeId,
    shouldUseAutoPlaybackSync,
    stopPacketSeen,
  ]);

  // Keep synced text monotonic: once visible, never regress or disappear between chunks.
  const content = useMemo(() => {
    const wasUserCancelled = stopReason === StopReason.USER_CANCELLED;

    // On user cancel, freeze at exactly what was already visible.
    if (wasUserCancelled) {
      return lastVisibleContentRef.current;
    }

    if (!shouldUseAutoPlaybackSync) {
      return computedContent;
    }

    if (computedContent.length === 0) {
      return lastStableSyncedContentRef.current;
    }

    const last = lastStableSyncedContentRef.current;
    if (computedContent.startsWith(last)) {
      return computedContent;
    }

    // If content shape changed unexpectedly mid-stream, prefer the stable version
    // to avoid flicker/dumps.
    if (!stopPacketSeen || wasUserCancelled) {
      return last;
    }

    // For normal completed responses, allow final full content.
    return computedContent;
  }, [computedContent, shouldUseAutoPlaybackSync, stopPacketSeen, stopReason]);

  // Sync the stable ref outside of useMemo to avoid side effects during render.
  useEffect(() => {
    if (stopReason === StopReason.USER_CANCELLED) {
      return;
    }
    if (!shouldUseAutoPlaybackSync) {
      lastStableSyncedContentRef.current = "";
    } else if (content.length > 0) {
      lastStableSyncedContentRef.current = content;
    }
  }, [content, shouldUseAutoPlaybackSync, stopReason]);

  // Track last actually rendered content so cancel can freeze without dumping buffered text.
  useEffect(() => {
    if (content.length > 0) {
      lastVisibleContentRef.current = content;
    }
  }, [content]);

  const shouldShowThinkingPlaceholder =
    shouldUseAutoPlaybackSync &&
    isAwaitingAutoPlaybackStart &&
    !hasTimelineThinking &&
    !stopPacketSeen;

  const shouldShowSpeechWarmupIndicator =
    shouldUseAutoPlaybackSync &&
    !isAwaitingAutoPlaybackStart &&
    content.length === 0 &&
    fullContent.length > 0 &&
    !hasTimelineThinking &&
    !stopPacketSeen;

  const shouldShowCursor =
    content.length > 0 &&
    (!stopPacketSeen ||
      (shouldUseAutoPlaybackSync && content.length < fullContent.length));

  const { renderedContent } = useMarkdownRenderer(
    // the [*]() is a hack to show a blinking dot when the packet is not complete
    shouldShowCursor ? content + " [*]() " : content,
    state,
    "font-main-content-body"
  );

  return children([
    {
      icon: null,
      status: null,
      content:
        shouldShowThinkingPlaceholder || shouldShowSpeechWarmupIndicator ? (
          <Text as="span" secondaryBody text04 className="italic">
            Thinking
          </Text>
        ) : content.length > 0 ? (
          <>{renderedContent}</>
        ) : (
          <BlinkingBar addMargin />
        ),
    },
  ]);
};
