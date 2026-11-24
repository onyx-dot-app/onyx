import { RefObject, useCallback, useEffect, useRef } from "react";
import type { ChatScrollContainerHandle } from "@/lib/chatScroll/components/ChatScrollContainer";
import { useOptionalScrollContainer } from "@/lib/chatScroll/components/ScrollContainerContext";
import { prefersReducedMotion } from "@opal/utils";
import { FOLD_OPEN_MS } from "@opal/components";

/**
 * After a send adds a new turn, glide to the end. The latest turn fills the
 * viewport (its min-height), so the end puts the new user message at the
 * top, whether or not the view was following. A turn taller than the view
 * stops the glide at its user message. A resumed run is not a send
 * and never moves the view, and neither is a switch back to a chat that is
 * still running.
 */
export function useScrollToNewTurn(
  scrollRef: RefObject<ChatScrollContainerHandle | null>,
  sessionId: string | null | undefined,
  anchorSelector: string | undefined,
  sending: boolean
): void {
  const previousRef = useRef({ sessionId, anchorSelector });
  useEffect(() => {
    const previous = previousRef.current;
    previousRef.current = { sessionId, anchorSelector };
    // A new chat gets its id with its first send, so only a switch from
    // another chat's id is not a send.
    const switchedChat =
      previous.sessionId != null && previous.sessionId !== sessionId;
    const changed = previous.anchorSelector !== anchorSelector;
    if (!switchedChat && changed && sending && anchorSelector) {
      scrollRef.current?.scrollToNewTurn();
    }
  }, [sessionId, anchorSelector, sending, scrollRef]);
}

/**
 * Brings a row into view after the user opens it. Put `rowRef` on the row and
 * call `onToggle` with the new open state when the user opens or closes it.
 * Outside a chat scroll container it does nothing.
 */
export function useRevealOnOpen() {
  const scroll = useOptionalScrollContainer();
  const rowRef = useRef<HTMLDivElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const onToggle = useCallback(
    (open: boolean) => {
      // A row closed again before the wait ends does not scroll.
      clearTimeout(timerRef.current);
      if (!open || !scroll) return;
      // Measure once the fold has its full height: a scroll is clamped to the
      // height the content has when it starts. A row that unmounts before
      // then has a null ref, so the late timer does nothing.
      timerRef.current = setTimeout(
        () => {
          const row = rowRef.current;
          if (row?.isConnected) scroll.revealContent(row);
        },
        prefersReducedMotion() ? 0 : FOLD_OPEN_MS
      );
    },
    [scroll]
  );
  return { rowRef, onToggle };
}
