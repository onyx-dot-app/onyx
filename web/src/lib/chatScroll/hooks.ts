import { RefObject, useEffect, useRef } from "react";
import type { ChatScrollContainerHandle } from "@/lib/chatScroll/components/ChatScrollContainer";

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
