import React, { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import {
  PacketType,
  ReasoningDelta,
  ReasoningPacket,
} from "@/app/app/services/streamingModels";
import {
  MessageRenderer,
  FullChatState,
} from "@/app/app/message/messageComponents/types";
import {
  ThinkingBody,
  splitThinkingTitle,
} from "@/lib/timeline/components/bodies/ThinkingBody";
import { SvgCircle } from "@opal/icons";

const THINKING_MIN_DURATION_MS = 500; // 0.5 second minimum for "Thinking" state

function constructCurrentReasoningState(packets: ReasoningPacket[]) {
  const hasStart = packets.some(
    (p) => p.obj.type === PacketType.REASONING_START
  );
  const hasEnd = packets.some(
    (p) =>
      p.obj.type === PacketType.SECTION_END ||
      p.obj.type === PacketType.ERROR ||
      // Support reasoning_done from backend
      (p.obj as any).type === PacketType.REASONING_DONE
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
> = ({ packets, onComplete, animate, children }) => {
  const t = useTranslations("chat.messages.timeline");
  const thinkingStatus = t("reasoning.thinking.status");

  const { hasStart, hasEnd, content } = useMemo(
    () => constructCurrentReasoningState(packets),
    [packets]
  );

  const { title, remainingContent } = useMemo(
    () => splitThinkingTitle(content),
    [content]
  );

  // Use extracted title if available, otherwise default
  const displayStatus = title || thinkingStatus;
  const displayContent = title ? remainingContent : content;

  // Track reasoning timing for minimum display duration
  const [reasoningStartTime, setReasoningStartTime] = useState<number | null>(
    null
  );
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
      !hasEnd ||
      reasoningStartTime === null ||
      completionHandledRef.current
    ) {
      return;
    }

    const complete = () => {
      if (!completionHandledRef.current) {
        completionHandledRef.current = true;
        onComplete();
      }
    };

    const elapsedTime = Date.now() - reasoningStartTime;
    const minimumThinkingDuration = animate ? THINKING_MIN_DURATION_MS : 0;

    if (elapsedTime >= minimumThinkingDuration) {
      complete();
      return;
    }

    const remainingTime = minimumThinkingDuration - elapsedTime;
    const timeout = setTimeout(complete, remainingTime);
    return () => clearTimeout(timeout);
  }, [hasEnd, reasoningStartTime, animate, onComplete]);

  if (!hasStart && !hasEnd && content.length === 0) {
    return children([
      {
        icon: SvgCircle,
        status: thinkingStatus,
        content: <></>,
        noPaddingRight: true,
      },
    ]);
  }

  const reasoningContent = (
    <ThinkingBody
      content={content}
      displayContent={displayContent}
      isStreaming={!hasEnd}
    />
  );

  return children([
    {
      icon: SvgCircle,
      status: displayStatus,
      content: reasoningContent,
      expandedText: reasoningContent,
      noPaddingRight: true,
    },
  ]);
};

export default ReasoningRenderer;
