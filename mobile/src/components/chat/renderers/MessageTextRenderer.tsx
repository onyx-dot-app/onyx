// The final-answer renderer: reveals concatenated stream content via useTypewriter, then hands the
// markdown to `children`. 9a inline citations ride along as `[[n]](url)` markers opened by openUrl.
import { useEffect, useMemo, useRef, useState } from "react";

import { ResponseItem } from "@/chat/streamingModels";
import { textContent, isComplete } from "@/chat/responseItems";
import { openUrl } from "@/chat/openSource";
import { StreamingMarkdown } from "@/components/chat/StreamingMarkdown";
import { useTypewriter } from "@/hooks/useTypewriter";

import type { FullChatState, MessageRenderer } from "./timelineContract";

export const MessageTextRenderer: MessageRenderer<
  ResponseItem,
  FullChatState
> = ({ items, onComplete, animate, stopPacketSeen, children }) => {
  // Stable across packet flushes so the typewriter target grows only when content does.
  const content = useMemo(
    () => textContent(items) + textContent(items, "commentary"),
    [items],
  );

  const messageEndSeen = useMemo(() => isComplete(items), [items]);
  const isStreamFinished = stopPacketSeen || messageEndSeen;

  // Captured once at mount: live messages animate; historical ones snap.
  const [animateAtMount] = useState(() => animate);
  const { displayed } = useTypewriter(
    content,
    animateAtMount,
    isStreamFinished,
  );

  // Timeline pacing gate (9b.7): fire once when the answer is fully shown. Ref-guarded because
  // `onComplete`'s identity changes each parent render.
  const streamFullyDisplayed =
    isStreamFinished && displayed.length >= content.length;
  const onCompleteFiredRef = useRef(false);
  useEffect(() => {
    if (streamFullyDisplayed && !onCompleteFiredRef.current) {
      onCompleteFiredRef.current = true;
      onComplete();
    }
  }, [streamFullyDisplayed, onComplete]);

  return children([
    {
      icon: null,
      status: null,
      content: (
        <StreamingMarkdown
          content={displayed}
          isStreaming={!isStreamFinished}
          onLinkPress={openUrl}
        />
      ),
    },
  ]);
};
