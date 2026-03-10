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
} from "@/app/app/services/streamingModels";
import {
  MessageRenderer,
  FullChatState,
} from "@/app/app/message/messageComponents/interfaces";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import ExpandableTextDisplay from "@/refresh-components/texts/ExpandableTextDisplay";
import {
  mutedTextMarkdownComponents,
  collapsedMarkdownComponents,
} from "@/app/app/message/messageComponents/timeline/renderers/sharedMarkdownComponents";
import { SvgCircle } from "@opal/icons";

const THINKING_MIN_DURATION_MS = 500; // 0.5 second minimum for "Thinking" state

const THINKING_STATUS = "Thinking";

function extractFirstParagraph(content: string): {
  title: string | null;
  remainingContent: string;
} {
  if (!content || content.trim().length === 0) {
    return { title: null, remainingContent: content };
  }

  const trimmed = content.trim();

  // Split by double newline (paragraph break) or single newline
  const lines = trimmed.split(/\n\n|\n/);
  const firstLine = lines[0]?.trim();

  if (!firstLine) {
    return { title: null, remainingContent: content };
  }

  // Only treat as title if it's an actual markdown heading (starts with #)
  const isMarkdownHeading = /^#+\s/.test(firstLine);
  if (!isMarkdownHeading) {
    return { title: null, remainingContent: content };
  }

  // Remove markdown heading markers (# ## ### etc.)
  const cleanTitle = firstLine.replace(/^#+\s*/, "").trim();

  // Only use as title if it's reasonably short (under ~60 chars for UI fit)
  if (cleanTitle.length > 60) {
    return { title: null, remainingContent: content };
  }

  // Remove the first line from content
  const remainingContent = trimmed.slice(firstLine.length).replace(/^\n+/, "");

  return { title: cleanTitle, remainingContent };
}

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

  const { title, remainingContent } = useMemo(
    () => extractFirstParagraph(content),
    [content]
  );

  // Use extracted title if available, otherwise default
  const displayStatus = title || THINKING_STATUS;
  const displayContent = title ? remainingContent : content;

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
  // Uses collapsed components (no spacing) in collapsed view, normal spacing in expanded modal
  const renderMarkdown = useCallback(
    (text: string, isExpanded: boolean) => (
      <MinimalMarkdown
        content={text}
        components={
          isExpanded ? mutedTextMarkdownComponents : collapsedMarkdownComponents
        }
      />
    ),
    []
  );

  if (!hasStart && !hasEnd && content.length === 0) {
    return children([
      { icon: SvgCircle, status: THINKING_STATUS, content: <></> },
    ]);
  }

  const reasoningContent = (
    <div className="pl-[var(--timeline-common-text-padding)]">
      <ExpandableTextDisplay
        title="Full text"
        content={content}
        displayContent={displayContent}
        renderContent={renderMarkdown}
        isStreaming={!hasEnd}
      />
    </div>
  );

  return children([
    {
      icon: SvgCircle,
      status: displayStatus,
      content: reasoningContent,
      expandedText: reasoningContent,
    },
  ]);
};

export default ReasoningRenderer;
