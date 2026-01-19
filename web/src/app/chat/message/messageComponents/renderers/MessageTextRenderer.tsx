import React, { useEffect, useMemo, useRef, useState } from "react";
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

// Target characters per second for smooth streaming display
// 80 chars/sec ≈ fast human reading speed, feels natural
const TARGET_CHARS_PER_SECOND = 80;
// How often to update the display (60fps for smooth animation)
const RENDER_INTERVAL_MS = 16;
// Characters to add per render frame
const CHARS_PER_FRAME = Math.max(
  1,
  Math.round((TARGET_CHARS_PER_SECOND * RENDER_INTERVAL_MS) / 1000)
);

export const MessageTextRenderer: MessageRenderer<
  ChatPacket,
  FullChatState
> = ({
  packets,
  state,
  onComplete,
  renderType,
  animate,
  stopPacketSeen,
  stopReason,
  children,
}) => {
  // Track how many characters we've displayed (for smooth animation)
  const [displayedCharCount, setDisplayedCharCount] = useState(0);
  // Track if we've caught up to show completion state properly
  const lastFullContentLengthRef = useRef(0);

  // Get the full content from all packets
  const fullContent = useMemo(
    () =>
      packets
        .map((packet) => {
          if (
            packet.obj.type === PacketType.MESSAGE_DELTA ||
            packet.obj.type === PacketType.MESSAGE_START
          ) {
            return packet.obj.content;
          }
          return "";
        })
        .join(""),
    [packets]
  );

  // Smooth character-based animation effect
  useEffect(() => {
    if (!animate) {
      // Not animating - show everything immediately
      setDisplayedCharCount(fullContent.length);
      return;
    }

    // If we've displayed everything available, wait for more content
    if (displayedCharCount >= fullContent.length) {
      return;
    }

    // Animate: increment displayed characters at a steady rate
    const timer = setTimeout(() => {
      setDisplayedCharCount((prev) =>
        Math.min(prev + CHARS_PER_FRAME, fullContent.length)
      );
    }, RENDER_INTERVAL_MS);

    return () => clearTimeout(timer);
  }, [animate, displayedCharCount, fullContent.length]);

  // Reset when content shrinks (new message started)
  useEffect(() => {
    if (fullContent.length < lastFullContentLengthRef.current) {
      // Content shrank - new message, reset display
      setDisplayedCharCount(0);
    }
    lastFullContentLengthRef.current = fullContent.length;
  }, [fullContent.length]);

  // Only mark as complete when all content is received AND displayed
  useEffect(() => {
    if (isFinalAnswerComplete(packets)) {
      // If animating, wait until all characters are displayed
      if (animate && displayedCharCount < fullContent.length) {
        return;
      }
      onComplete();
    }
  }, [packets, onComplete, animate, displayedCharCount, fullContent.length]);

  // Get content based on displayed character count
  const content = useMemo(() => {
    if (!animate) {
      return fullContent; // Show all content
    }
    // Show only up to displayedCharCount characters for smooth animation
    return fullContent.slice(0, displayedCharCount);
  }, [animate, displayedCharCount, fullContent]);

  const { renderedContent } = useMarkdownRenderer(
    // the [*]() is a hack to show a blinking dot when the packet is not complete
    stopPacketSeen ? content : content + " [*]() ",
    state,
    "font-main-content-body"
  );

  const wasUserCancelled = stopReason === StopReason.USER_CANCELLED;

  return children({
    icon: null,
    status: null,
    content:
      content.length > 0 || packets.length > 0 ? (
        <>
          {renderedContent}
          {wasUserCancelled && (
            <Text as="p" secondaryBody text04>
              User has stopped generation
            </Text>
          )}
        </>
      ) : (
        <BlinkingDot addMargin />
      ),
  });
};
