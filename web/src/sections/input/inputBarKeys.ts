import type { KeyboardEvent } from "react";
import type { QueuedMessageNavigation } from "@/hooks/useQueuedMessageNavigation";

/**
 * Consults an input bar's navigation handlers in priority order, returning
 * whether one consumed the event (the caller should then stop processing it).
 *
 * Queue navigation runs first: while a queued message is highlighted it owns
 * keys like Backspace and Enter, and the rich-tile handler's leading-tile
 * Backspace guard would otherwise swallow the queue's delete key. Each handler
 * is a no-op outside its active state, so neither interferes with the other.
 */
export function handleInputNavKeys(
  event: KeyboardEvent<HTMLDivElement>,
  queueNav: Pick<QueuedMessageNavigation, "handleKeyDown">,
  handleTileKeyDown: (event: KeyboardEvent<HTMLDivElement>) => boolean
): boolean {
  return queueNav.handleKeyDown(event) || handleTileKeyDown(event);
}
