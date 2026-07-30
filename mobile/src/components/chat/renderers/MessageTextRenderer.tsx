// The final-answer renderer: reveals concatenated stream content via useTypewriter, then hands the
// markdown to `children`. 9a inline citations ride along as `[[n]](url)` markers opened by openUrl.
import { useEffect, useMemo, useRef, useState } from "react";

import {
  MessageDelta,
  MessageStart,
  Packet,
  PacketType,
} from "@/chat/streamingModels";
import { openUrl } from "@/chat/openSource";
import { StreamingMarkdown } from "@/components/chat/StreamingMarkdown";
import { useTypewriter } from "@/hooks/useTypewriter";

import type { FullChatState, MessageRenderer } from "./timelineContract";

function accumulateContent(packets: Packet[]): string {
  let content = "";
  for (const packet of packets) {
    if (
      packet.obj.type === PacketType.MESSAGE_START ||
      packet.obj.type === PacketType.MESSAGE_DELTA
    ) {
      // message_start can arrive with no content; guard prevents appending literal "undefined".
      content += (packet.obj as MessageStart | MessageDelta).content ?? "";
    }
  }
  return content;
}

export const MessageTextRenderer: MessageRenderer<Packet, FullChatState> = ({
  packets,
  onComplete,
  animate,
  stopPacketSeen,
  children,
}) => {
  // Stable across packet flushes so the typewriter target grows only when content does.
  const content = useMemo(() => accumulateContent(packets), [packets]);

  // Reproduces the processor's `isComplete` (MESSAGE_END or STOP) from the contract props — the signal
  // that tells the typewriter to drain to the end and snap.
  const messageEndSeen = useMemo(
    () => packets.some((packet) => packet.obj.type === PacketType.MESSAGE_END),
    [packets],
  );
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
