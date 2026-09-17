import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { ResponseItem } from "@/app/app/services/streamingModels";
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
import { isComplete as itemsComplete } from "@/app/app/services/responseItems";

const THINKING_MIN_DURATION_MS = 500; // 0.5 second minimum for "Thinking" state

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

function constructCurrentReasoningState(items: ResponseItem[]) {
  const hasStart = items.length > 0;
  const hasEnd = itemsComplete(items);
  const content = items
    .map((item) => (item.content.kind === "reasoning" ? item.content.text : ""))
    .join("");

  return {
    hasStart,
    hasEnd,
    content,
  };
}

export const ReasoningRenderer: MessageRenderer<
  ResponseItem,
  FullChatState
> = ({ items, onComplete, animate, children }) => {
  const t = useTranslations("chat.messages.timeline");
  const thinkingStatus = t("reasoning.thinking.status");

  const { hasStart, hasEnd, content } = useMemo(
    () => constructCurrentReasoningState(items),
    [items]
  );

  const { title, remainingContent } = useMemo(
    () => extractFirstParagraph(content),
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
      {
        icon: SvgCircle,
        status: thinkingStatus,
        content: <></>,
        noPaddingRight: true,
      },
    ]);
  }

  const reasoningContent = (
    <div className="ps-(--timeline-common-text-padding)">
      <ExpandableTextDisplay
        title={t("reasoning.fullText.title")}
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
      noPaddingRight: true,
    },
  ]);
};

export default ReasoningRenderer;
