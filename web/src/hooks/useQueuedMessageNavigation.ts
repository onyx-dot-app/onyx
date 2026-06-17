import {
  useCallback,
  useEffect,
  useState,
  type Dispatch,
  type KeyboardEvent,
  type SetStateAction,
} from "react";
import { QueuedMessage } from "@/app/app/interfaces";

interface UseQueuedMessageNavigationParams {
  /** The messages currently queued for the active session. */
  messages: readonly QueuedMessage[];
  /**
   * Whether the text input is empty. Up-arrow only enters navigation mode
   * when there is no text to move the caret within.
   */
  inputIsEmpty: boolean;
  /** Remove the queued message at `index`. */
  onRemove: (index: number) => void;
  /** Pull a queued message's text back into the input for editing. */
  onEdit: (text: string) => void;
}

export interface QueuedMessageNavigation {
  /** Index of the queued message focused for keyboard editing, or null. */
  highlightedIndex: number | null;
  setHighlightedIndex: Dispatch<SetStateAction<number | null>>;
  /**
   * Handle a keydown for queue navigation. Returns true if the event was
   * consumed (the caller should stop processing it). Returns false when the
   * key should fall through to normal input handling — including the case
   * where an arbitrary key exits navigation mode and types as usual.
   */
  handleKeyDown: (event: KeyboardEvent<HTMLDivElement>) => boolean;
}

/**
 * Keyboard navigation for the queued-message bar, shared by the main chat and
 * Craft input bars. Owns the highlight state and translates key presses into
 * remove / edit / navigate actions, leaving the store wiring to the caller.
 *
 * Behavior:
 * - ↑ on an empty input enters navigation mode at the last queued message.
 * - In navigation mode: ↑/↓ move (↓ past the end exits), Enter edits (pulls
 *   the message into the input), Delete/Backspace removes (staying in
 *   navigation mode so items can be pruned in a row), Escape exits.
 * - Any other key exits navigation mode and falls through so it types.
 */
export function useQueuedMessageNavigation({
  messages,
  inputIsEmpty,
  onRemove,
  onEdit,
}: UseQueuedMessageNavigationParams): QueuedMessageNavigation {
  const [highlightedIndex, setHighlightedIndex] = useState<number | null>(null);

  // Keep the highlight in range as the queue shrinks (auto-send or prune),
  // and clear it once the queue empties.
  useEffect(() => {
    setHighlightedIndex((prev) => {
      if (prev === null) return null;
      if (messages.length === 0) return null;
      return Math.min(prev, messages.length - 1);
    });
  }, [messages.length]);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>): boolean => {
      // Navigation mode: keys act on the highlighted queued message.
      if (highlightedIndex !== null) {
        if (event.key === "Enter") {
          event.preventDefault();
          const queued = messages[highlightedIndex];
          if (queued) {
            onRemove(highlightedIndex);
            onEdit(queued.text);
          }
          setHighlightedIndex(null);
          return true;
        }
        if (event.key === "ArrowUp") {
          event.preventDefault();
          setHighlightedIndex((prev) => Math.max((prev ?? 0) - 1, 0));
          return true;
        }
        if (event.key === "ArrowDown") {
          event.preventDefault();
          setHighlightedIndex((prev) => {
            const next = (prev ?? 0) + 1;
            return next >= messages.length ? null : next;
          });
          return true;
        }
        if (event.key === "Delete" || event.key === "Backspace") {
          event.preventDefault();
          // Stay in nav mode (clamp effect re-points the index) to prune in a row.
          onRemove(highlightedIndex);
          return true;
        }
        if (event.key === "Escape") {
          event.preventDefault();
          setHighlightedIndex(null);
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
        setHighlightedIndex(null);
      }

      // Up arrow on an empty input enters navigation mode.
      if (event.key === "ArrowUp" && inputIsEmpty && messages.length > 0) {
        event.preventDefault();
        setHighlightedIndex(messages.length - 1);
        return true;
      }

      return false;
    },
    [highlightedIndex, messages, inputIsEmpty, onRemove, onEdit]
  );

  return { highlightedIndex, setHighlightedIndex, handleKeyDown };
}
