"use client";

import { Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { markdown } from "@opal/utils";

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

/**
 * Splits off a leading bold line ("**Checking the notes**"), the heading a
 * model often starts a reasoning block with. Without one, the heading is null.
 */
function splitBoldHeading(text: string): {
  heading: string | null;
  rest: string;
} {
  const trimmed = text.trim();
  const match = trimmed.match(/^\*\*([^*\n]+)\*\*\s*(?:\n|$)/);
  if (!match || !match[1]) return { heading: null, rest: trimmed };
  return {
    heading: match[1].trim(),
    rest: trimmed.slice(match[0].length).trim(),
  };
}

interface ThinkingBodyProps {
  /** The whole reasoning. */
  content: string;
  /** The reasoning shown in the body, without the step's title. */
  displayContent: string;
  isStreaming: boolean;
}

/**
 * The body of a thinking step: a leading bold heading the model wrote, then
 * the reasoning (markdown, `secondary-body` in `text-03`). Both are generated
 * text, so both are plain `Text`. Shared by chat and Craft.
 */
export function ThinkingBody({ displayContent }: ThinkingBodyProps) {
  const { heading, rest } = splitBoldHeading(displayContent);

  return (
    <div className="ps-(--timeline-common-text-padding)">
      <Section alignItems="stretch" gap={0} height="fit">
        {heading && (
          <Text as="p" font="secondary-action" color="text-04">
            {heading}
          </Text>
        )}
        {rest && (
          <Text as="p" font="secondary-body" color="text-03">
            {markdown(rest)}
          </Text>
        )}
      </Section>
    </div>
  );
}
