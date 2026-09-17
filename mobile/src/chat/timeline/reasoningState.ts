// Ported from web's `ReasoningRenderer` helpers; kept out of the renderer so it stays
// reanimated-free and unit-testable.
import { ResponseItem } from "@/chat/streamingModels";

// Longer headings are prose, not titles, and overflow the step header.
const MAX_TITLE_LENGTH = 60;

export interface ReasoningState {
  hasStart: boolean;
  hasEnd: boolean;
  content: string;
}

export interface FirstParagraph {
  // Set only when the reasoning opens with a short markdown heading.
  title: string | null;
  remainingContent: string;
}

export function extractFirstParagraph(content: string): FirstParagraph {
  if (!content || content.trim().length === 0) {
    return { title: null, remainingContent: content };
  }

  const trimmed = content.trim();
  const firstLine = trimmed.split(/\n\n|\n/)[0]?.trim();
  if (!firstLine) {
    return { title: null, remainingContent: content };
  }

  if (!/^#+\s/.test(firstLine)) {
    return { title: null, remainingContent: content };
  }

  const cleanTitle = firstLine.replace(/^#+\s*/, "").trim();
  if (cleanTitle.length > MAX_TITLE_LENGTH) {
    return { title: null, remainingContent: content };
  }

  return {
    title: cleanTitle,
    remainingContent: trimmed.slice(firstLine.length).replace(/^\n+/, ""),
  };
}

// Resolves one step's reasoning text from the processor's grouped items. The message row re-runs
// this every flush so an open full-text reader tracks the stream instead of freezing at open time.
export function resolveGroupReasoning(
  groupedItemsMap: Map<string, ResponseItem[]>,
  groupKey: string | null,
): string | null {
  if (groupKey === null) {
    return null;
  }
  const group = groupedItemsMap.get(groupKey);
  return group ? constructCurrentReasoningState(group).content : null;
}

export function constructCurrentReasoningState(
  items: ResponseItem[],
): ReasoningState {
  const reasoning = items.filter((item) => item.content.kind === "reasoning");
  return {
    hasStart: reasoning.length > 0,
    hasEnd:
      reasoning.length > 0 &&
      reasoning.every((item) => item.content.status !== "running"),
    content: reasoning
      .map((item) =>
        item.content.kind === "reasoning" ? item.content.text : "",
      )
      .join(""),
  };
}
