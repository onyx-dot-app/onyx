import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  PacketType,
  ReasoningDelta,
  ReasoningPacket,
} from "@/app/chat/services/streamingModels";
import {
  MessageRenderer,
  FullChatState,
} from "@/app/chat/message/messageComponents/interfaces";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import ExpandableTextDisplay from "@/refresh-components/texts/ExpandableTextDisplay";
import { mutedTextMarkdownComponents } from "@/app/chat/message/messageComponents/timeline/renderers/sharedMarkdownComponents";
import { SvgCircle } from "@opal/icons";

const THINKING_MIN_DURATION_MS = 500; // 0.5 second minimum for "Thinking" state

const THINKING_STATUS = "Thinking";

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

  // Markdown renderer callback for ExpandableTextDisplay
  const renderMarkdown = useCallback(
    (text: string) => (
      <MinimalMarkdown
        content={text}
        components={mutedTextMarkdownComponents}
      />
    ),
    []
  );

  if (!hasStart && !hasEnd && content.length === 0) {
    return children({ icon: SvgCircle, status: null, content: <></> });
  }

  const reasoningContent = (
    <ExpandableTextDisplay
      title="Thinking"
      content={content}
      displayContent={content}
      maxLines={5}
      renderContent={renderMarkdown}
    />
  );

  return children({
    icon: SvgCircle,
    status: THINKING_STATUS,
    content: reasoningContent,
    expandedText: reasoningContent,
  });
};

export default ReasoningRenderer;
