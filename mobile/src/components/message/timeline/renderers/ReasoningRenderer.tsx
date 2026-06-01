/* eslint-disable react-hooks/set-state-in-effect -- the 500ms minimum-display
   timing intentionally records the reasoning start time via setState in an
   effect; ported verbatim from web ReasoningRenderer. */
// ReasoningRenderer.tsx — the "thinking" block. Native mirror of web ReasoningRenderer.
// Reduces ReasoningPackets to {hasStart,hasEnd,content}; extracts an optional
// markdown-heading title as the status label; enforces a 500ms minimum
// "Thinking" display; renders content via ExpandableTextDisplay + Markdown.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { View } from "react-native";

import { PacketType, type ReasoningDelta, type ReasoningPacket } from "@/lib/types";
import type { MessageRendererProps } from "@/components/message/interfaces";
import { Markdown } from "@/components/markdown";
import { ExpandableTextDisplay } from "@/components/message/ExpandableTextDisplay";
import { timelineTokens as T } from "@/theme/timelineTokens";

const THINKING_MIN_DURATION_MS = 500;
const THINKING_STATUS = "Thinking";

function extractFirstParagraph(content: string): {
  title: string | null;
  remainingContent: string;
} {
  if (!content || content.trim().length === 0) {
    return { title: null, remainingContent: content };
  }
  const trimmed = content.trim();
  const lines = trimmed.split(/\n\n|\n/);
  const firstLine = lines[0]?.trim();
  if (!firstLine) return { title: null, remainingContent: content };

  const isMarkdownHeading = /^#+\s/.test(firstLine);
  if (!isMarkdownHeading) return { title: null, remainingContent: content };

  const cleanTitle = firstLine.replace(/^#+\s*/, "").trim();
  if (cleanTitle.length > 60) return { title: null, remainingContent: content };

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
      p.obj.type === PacketType.REASONING_DONE
  );
  const deltas = packets
    .filter((p) => p.obj.type === PacketType.REASONING_DELTA)
    .map((p) => p.obj as ReasoningDelta);
  const content = deltas.map((d) => d.reasoning).join("");
  return { hasStart, hasEnd, content };
}

export function ReasoningRenderer({
  packets,
  onComplete,
  animate,
  children,
}: MessageRendererProps<ReasoningPacket>) {
  const { hasStart, hasEnd, content } = useMemo(
    () => constructCurrentReasoningState(packets),
    [packets]
  );

  const { title, remainingContent } = useMemo(
    () => extractFirstParagraph(content),
    [content]
  );

  const displayStatus = title || THINKING_STATUS;
  const displayContent = title ? remainingContent : content;

  const [reasoningStartTime, setReasoningStartTime] = useState<number | null>(
    null
  );
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const completionHandledRef = useRef(false);

  useEffect(() => {
    if ((hasStart || hasEnd) && reasoningStartTime === null) {
      setReasoningStartTime(Date.now());
    }
  }, [hasStart, hasEnd, reasoningStartTime]);

  useEffect(() => {
    if (hasEnd && reasoningStartTime !== null && !completionHandledRef.current) {
      completionHandledRef.current = true;
      const elapsed = Date.now() - reasoningStartTime;
      const minDuration = animate ? THINKING_MIN_DURATION_MS : 0;
      if (elapsed >= minDuration) {
        onComplete();
      } else {
        timeoutRef.current = setTimeout(() => onComplete(), minDuration - elapsed);
      }
    }
  }, [hasEnd, reasoningStartTime, animate, onComplete]);

  useEffect(() => {
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, []);

  const renderMarkdown = useCallback(
    (text: string, isExpanded: boolean) => (
      <Markdown variant={isExpanded ? "muted" : "muted-collapsed"}>{text}</Markdown>
    ),
    []
  );

  if (!hasStart && !hasEnd && content.length === 0) {
    return children([
      {
        icon: "circle",
        status: THINKING_STATUS,
        content: <View />,
        noPaddingRight: true,
      },
    ]);
  }

  const reasoningContent = (
    <View style={{ paddingLeft: T.timelineCommonTextPadding }}>
      <ExpandableTextDisplay
        title="Full text"
        content={content}
        displayContent={displayContent}
        renderContent={renderMarkdown}
        isStreaming={!hasEnd}
        maxLines={4}
      />
    </View>
  );

  return children([
    {
      icon: "circle",
      status: displayStatus,
      content: reasoningContent,
      noPaddingRight: true,
    },
  ]);
}

export default ReasoningRenderer;
