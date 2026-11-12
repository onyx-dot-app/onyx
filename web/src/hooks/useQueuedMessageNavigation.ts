import { useCallback, useState, type KeyboardEvent } from "react";
import { QueuedMessage } from "@/app/app/types";
import type { PendingChatMessage } from "@/lib/chat/types";

type QueuedItem = QueuedMessage | PendingChatMessage;

interface UseQueuedMessageNavigationParams {
  /** The messages currently queued for the active session. */
  messages: readonly QueuedItem[];
  /**
   * Whether the text input is empty. Up-arrow only enters navigation mode
   * when there is no text to move the caret within.
   */
  inputIsEmpty: boolean;
  /** Remove the queued message at `index`. */
  onRemove: (index: number) => void;
  /** Pull a queued message's text back into the input for editing. */
  onEdit: (index: number) => void;
  onSendNow?: (index: number) => void;
}

export interface QueuedMessageNavigation {
  /**
   * The queued message focused for keyboard editing, or null. Keyed by ID, so
   * a message that leaves the queue drops the highlight instead of passing it on.
   */
  highlightedId: QueuedItem["id"] | null;
  setHighlightedId: (id: QueuedItem["id"] | null) => void;
  /**
   * Handle a keydown for queue navigation. Returns true if the event was
   * consumed (the caller should stop processing it). Returns false when the
   * key should fall through to normal input handling — including the case
   * where an arbitrary key exits navigation mode and types as usual.
   */
  handleKeyDown: (event: KeyboardEvent<HTMLDivElement>) => boolean;
}

/** Queue navigation shared with Craft; Enter sends immediately when supported, otherwise edits. */
export function useQueuedMessageNavigation({
  messages,
  inputIsEmpty,
  onRemove,
  onEdit,
  onSendNow,
}: UseQueuedMessageNavigationParams): QueuedMessageNavigation {
  const [selectedId, setHighlightedId] = useState<QueuedItem["id"] | null>(
    null
  );
  const highlightedIndex = messages.findIndex(
    (message) => message.id === selectedId
  );
  const highlightedId = highlightedIndex === -1 ? null : selectedId;

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>): boolean => {
      // Navigation mode: keys act on the highlighted queued message.
      if (highlightedId !== null) {
        if (event.key === "Enter") {
          event.preventDefault();
          (onSendNow ?? onEdit)(highlightedIndex);
          setHighlightedId(null);
          return true;
        }
        if (event.key === "ArrowUp") {
          event.preventDefault();
          setHighlightedId(
            messages[Math.max(highlightedIndex - 1, 0)]?.id ?? null
          );
          return true;
        }
        if (event.key === "ArrowDown") {
          event.preventDefault();
          setHighlightedId(messages[highlightedIndex + 1]?.id ?? null);
          return true;
        }
        if (event.key === "Delete" || event.key === "Backspace") {
          event.preventDefault();
          // Stay in nav mode on a neighbor to prune in a row.
          setHighlightedId(
            (messages[highlightedIndex + 1] ?? messages[highlightedIndex - 1])
              ?.id ?? null
          );
          onRemove(highlightedIndex);
          return true;
        }
        if (event.key === "Escape") {
          event.preventDefault();
          setHighlightedId(null);
          return true;
        }
        if (
          event.key === "Shift" ||
          event.key === "Alt" ||
          event.key === "Control" ||
          event.key === "Meta" ||
          event.key === "Tab"
        ) {
          return true;
        }
        // Any other key exits navigation mode and falls through to type.
        setHighlightedId(null);
      }

      // Up arrow on an empty input enters navigation mode.
      const last = messages.at(-1);
      if (event.key === "ArrowUp" && inputIsEmpty && last) {
        event.preventDefault();
        setHighlightedId(last.id);
        return true;
      }

      return false;
    },
    [
      highlightedId,
      highlightedIndex,
      messages,
      inputIsEmpty,
      onRemove,
      onEdit,
      onSendNow,
    ]
  );

  return { highlightedId, setHighlightedId, handleKeyDown };
}
