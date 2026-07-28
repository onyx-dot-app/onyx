// Pure scroll-position helpers for the chat message list, kept side-effect-free so they can be
// unit-tested without RN/FlashList. See useChatAutoScroll for the follow model these feed.
import { Message } from "@/chat/interfaces";

// Newest turn this far (px) below the viewport counts as "scrolled up": reveal the jump button and
// stop following. Web uses 32px; 48px matches this list's existing button threshold.
export const AT_BOTTOM_THRESHOLD_PX = 48;

export interface ScrollMetrics {
  offsetY: number;
  contentHeight: number;
  viewportHeight: number;
}

// Distance from the bottom of the content to the bottom of the viewport. Negative when the content
// is shorter than the viewport (short chat) — treated as "at bottom".
export function distanceFromBottom(metrics: ScrollMetrics): number {
  return metrics.contentHeight - (metrics.offsetY + metrics.viewportHeight);
}

export function isWithinBottomBand(
  metrics: ScrollMetrics,
  threshold: number = AT_BOTTOM_THRESHOLD_PX,
): boolean {
  return distanceFromBottom(metrics) <= threshold;
}

// A value that changes exactly when the list's rendered content grows: a new turn (count/last node)
// or a streaming flush (the last assistant node's packets append). Drives the auto-follow — comparing
// it, rather than reacting to every render, means the follow fires only on real content growth.
//
// It is height-blind: growth from late async layout (e.g. an image finishing load after the final
// packet) doesn't change it, so the follow won't chase that growth — but the jump button still
// surfaces it, via onContentSizeChange in useChatAutoScroll.
export function contentSignature(messages: Message[]): string {
  const last = messages.length ? messages[messages.length - 1] : undefined;
  return `${messages.length}:${last?.nodeId ?? ""}:${last?.packets.length ?? 0}:${last?.message.length ?? 0}`;
}
