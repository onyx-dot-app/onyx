"use client";

import { useCallback } from "react";
import { useTranslations } from "next-intl";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import ExpandableTextDisplay from "@/refresh-components/texts/ExpandableTextDisplay";
import {
  mutedTextMarkdownComponents,
  collapsedMarkdownComponents,
} from "@/lib/timeline/components/bodies/markdownComponents";

/**
 * Splits reasoning into a short title (a leading markdown heading) and the
 * rest. Without such a heading, the title is null and the text is unchanged.
 */
export function splitThinkingTitle(content: string): {
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

interface ThinkingBodyProps {
  /** The whole reasoning, shown in the full-text view. */
  content: string;
  /** The reasoning shown inline, without its title. */
  displayContent: string;
  isStreaming: boolean;
}

/**
 * The body of a thinking step: the reasoning as muted markdown, clipped
 * inline with a view of the full text. Shared by chat and Craft.
 */
export function ThinkingBody({
  content,
  displayContent,
  isStreaming,
}: ThinkingBodyProps) {
  const t = useTranslations("chat.messages.timeline");
  // Collapsed components (no spacing) inline, normal spacing in the full view.
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

  return (
    <div className="ps-(--timeline-common-text-padding)">
      <ExpandableTextDisplay
        title={t("reasoning.fullText.title")}
        content={content}
        displayContent={displayContent}
        renderContent={renderMarkdown}
        isStreaming={isStreaming}
      />
    </div>
  );
}
