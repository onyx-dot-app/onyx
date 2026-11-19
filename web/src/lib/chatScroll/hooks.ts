import { RefObject, useEffect, useRef } from "react";
import type { ChatScrollContainerHandle } from "@/lib/chatScroll/components/ChatScrollContainer";

/**
 * After a send adds a new turn, glide to the end. The latest turn fills the
 * viewport (its min-height), so the end puts the new user message at the
 * top, whether or not the view was following. A resumed run is not a send
 * and never moves the view.
 */
export function useScrollToNewTurn(
  scrollRef: RefObject<ChatScrollContainerHandle | null>,
  anchorSelector: string | undefined,
  sending: boolean
): void {
  const previousAnchorRef = useRef(anchorSelector);
  useEffect(() => {
    const changed = previousAnchorRef.current !== anchorSelector;
    previousAnchorRef.current = anchorSelector;
    if (changed && sending && anchorSelector) {
      scrollRef.current?.scrollToBottom("smooth");
    }
  }, [anchorSelector, sending, scrollRef]);
}
