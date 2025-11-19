import React, { useEffect, useMemo, useRef, useState } from "react";

import {
  PacketType,
  ReasoningDelta,
  ReasoningPacket,
} from "../../../services/streamingModels";
import { MessageRenderer, FullChatState } from "../interfaces";
import { useMarkdownRenderer } from "../markdownUtils";

const THINKING_MIN_DURATION_MS = 500; // 0.5 second minimum for "Thinking" state

const THINKING_STATUS = "Thinking";

function constructCurrentReasoningState(packets: ReasoningPacket[]) {
  const hasStart = packets.some(
    (p) => p.obj.type === PacketType.REASONING_START
  );
  const hasEnd = packets.some(
    (p) =>
      p.obj.type === PacketType.SECTION_END ||
      // Support either convention for reasoning completion
      (p.obj as any).type === PacketType.REASONING_END
  );
  const deltas = packets
    .filter((p) => p.obj.type === PacketType.REASONING_DELTA)
    .map((p) => p.obj as ReasoningDelta);

  const content = deltas.map((d) => d.reasoning).join("");

  return {
    hasStart,
    hasEnd,
    content,
  };
}

export const ReasoningRenderer: MessageRenderer<
  ReasoningPacket,
  FullChatState
> = ({ packets, state, onComplete, animate, children }) => {
  const { hasStart, hasEnd, content } = useMemo(
    () => constructCurrentReasoningState(packets),
    [packets]
  );

  // Track reasoning timing for minimum display duration
  const [reasoningStartTime, setReasoningStartTime] = useState<number | null>(
    null
  );
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);
  const completionHandledRef = useRef(false);

  // Track when reasoning starts
  useEffect(() => {
    if ((hasStart || hasEnd) && reasoningStartTime === null) {
      setReasoningStartTime(Date.now());
    }
  }, [hasStart, hasEnd, reasoningStartTime]);

  // Handle reasoning completion with minimum duration
  useEffect(() => {
    if (
      hasEnd &&
      reasoningStartTime !== null &&
      !completionHandledRef.current
    ) {
      completionHandledRef.current = true;
      const elapsedTime = Date.now() - reasoningStartTime;
      const minimumThinkingDuration = animate ? THINKING_MIN_DURATION_MS : 0;

      if (elapsedTime >= minimumThinkingDuration) {
        // Enough time has passed, complete immediately
        onComplete();
      } else {
        // Not enough time has passed, delay completion
        const remainingTime = minimumThinkingDuration - elapsedTime;
        timeoutRef.current = setTimeout(() => {
          onComplete();
        }, remainingTime);
      }
    }
  }, [hasEnd, reasoningStartTime, animate, onComplete]);

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  const { renderedContent } = useMarkdownRenderer(
    content,
    state,
    "text-text-03 font-main-ui-body"
  );

  if (!hasStart && !hasEnd && content.length === 0) {
    return children({ icon: null, status: null, content: <></> });
  }

  return children({
    icon: null,
    status: THINKING_STATUS,
    content: renderedContent,
    expandedText: renderedContent,
  });
};

export default ReasoningRenderer;
