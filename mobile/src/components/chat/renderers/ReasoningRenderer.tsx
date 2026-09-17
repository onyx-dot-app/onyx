// Streamed reasoning as a heading + windowed markdown. Headless: it hands a RendererResult to
// `children` rather than returning a tree — the step frame belongs to StepContainer.
import { useEffect, useMemo, useRef } from "react";
import { View } from "react-native";

import { getGroupKey } from "@/chat/messageProcessor";
import { Packet } from "@/chat/streamingModels";
import {
  constructCurrentReasoningState,
  extractFirstParagraph,
} from "@/chat/timeline/reasoningState";
import { timelineTokens } from "@/components/chat/timeline/primitives/timelineTokens";
import { ReasoningTextWindow } from "@/components/chat/timeline/ReasoningTextWindow";
import SvgCircle from "@/icons/circle";

import type { FullChatState, MessageRenderer } from "./timelineContract";

// Floor on the "Thinking" state so a fast reasoning burst doesn't flash past.
const THINKING_MIN_DURATION_MS = 500;
const THINKING_STATUS = "Thinking";

// Module-level: this re-renders on every stream flush, so don't rebuild the style object each time.
const bodyStyle = { paddingLeft: timelineTokens.timelineCommonTextPadding };

// `supportsCollapsible` is deliberately unset, matching web: no per-step collapse control, and a
// reasoning-only turn therefore renders with no step header.
export const ReasoningRenderer: MessageRenderer<Packet, FullChatState> = ({
  packets,
  state,
  onComplete,
  animate,
  children,
}) => {
  const { hasStart, hasEnd, content } = useMemo(
    () => constructCurrentReasoningState(packets),
    [packets],
  );
  const { title, remainingContent } = useMemo(
    () => extractFirstParagraph(content),
    [content],
  );

  // `||`, not `??`: an empty heading ("# " alone) extracts as "" and must still fall back.
  const displayStatus = title || THINKING_STATUS;
  const displayContent = title ? remainingContent : content;

  // The reader is opened by group key so the row can re-derive the text as the step streams on.
  const openFullText = state.openFullText;
  const firstPacket = packets[0];
  const handleExpand =
    openFullText && firstPacket
      ? () => openFullText(getGroupKey(firstPacket))
      : undefined;

  // Web holds the start time in state across two effects; mobile's lint forbids setState in an
  // effect, so it's a ref written and read inside the one effect that needs it. Same timing, one
  // commit instead of a cascading render.
  const startTimeRef = useRef<number | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const completionHandledRef = useRef(false);

  useEffect(() => {
    if (startTimeRef.current === null && (hasStart || hasEnd)) {
      startTimeRef.current = Date.now();
    }
    if (
      !hasEnd ||
      startTimeRef.current === null ||
      completionHandledRef.current
    ) {
      return;
    }
    completionHandledRef.current = true;

    // Historical messages replay with animate=false and skip the floor.
    const minimumThinkingDuration = animate ? THINKING_MIN_DURATION_MS : 0;
    const elapsedTime = Date.now() - startTimeRef.current;
    if (elapsedTime >= minimumThinkingDuration) {
      onComplete();
      return;
    }
    timeoutRef.current = setTimeout(
      onComplete,
      minimumThinkingDuration - elapsedTime,
    );
  }, [hasStart, hasEnd, animate, onComplete]);

  useEffect(
    () => () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    },
    [],
  );

  if (!hasStart && !hasEnd && content.length === 0) {
    return children([
      {
        icon: SvgCircle,
        status: THINKING_STATUS,
        content: <></>,
        noPaddingRight: true,
      },
    ]);
  }

  return children([
    {
      icon: SvgCircle,
      status: displayStatus,
      content: (
        <View style={bodyStyle}>
          <ReasoningTextWindow
            displayContent={displayContent}
            isStreaming={!hasEnd}
            onExpand={handleExpand}
          />
        </View>
      ),
      noPaddingRight: true,
    },
  ]);
};

export default ReasoningRenderer;
