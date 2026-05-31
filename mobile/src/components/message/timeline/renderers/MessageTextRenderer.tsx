// MessageTextRenderer.tsx — the final assistant answer (markdown + inline
// citations + streaming caret). Ports web MessageTextRenderer minus the
// typewriter/voice-sync (we render text as it arrives; store flushes are already
// rAF-batched, so markdown re-parse runs at frame cadence, not per token).

import { useEffect, useMemo, useRef } from "react";
import { View } from "react-native";

import { PacketType, type ChatPacket, type MessageStart, type MessageDelta } from "@/lib/types";
import type { MessageRendererProps } from "@/components/message/interfaces";
import { Markdown } from "@/components/markdown";
import { BlinkingBar } from "@/components/message/BlinkingBar";
import { processContent } from "@/components/message/citations/processContent";
import { isFinalAnswerComplete } from "@/state/timeline/packetUtils";

export function MessageTextRenderer({
  packets,
  state,
  onComplete,
  stopPacketSeen,
  children,
}: MessageRendererProps<ChatPacket>) {
  const fullContent = useMemo(
    () =>
      packets
        .map((p) =>
          p.obj.type === PacketType.MESSAGE_START ||
          p.obj.type === PacketType.MESSAGE_DELTA
            ? (p.obj as MessageStart | MessageDelta).content || ""
            : ""
        )
        .join(""),
    [packets]
  );

  const processed = useMemo(() => processContent(fullContent), [fullContent]);

  const isStreamFinished = useMemo(
    () => isFinalAnswerComplete(packets),
    [packets]
  );

  const onCompleteFiredRef = useRef(false);
  useEffect(() => {
    if (isStreamFinished && !onCompleteFiredRef.current) {
      onCompleteFiredRef.current = true;
      onComplete();
    }
  }, [isStreamFinished, onComplete]);

  const showCursor = !stopPacketSeen && !isStreamFinished;

  return children([
    {
      icon: null,
      status: null,
      content:
        processed.length > 0 ? (
          <View>
            <Markdown citations={state.citations} documents={state.docs}>
              {processed}
            </Markdown>
            {showCursor && <BlinkingBar addMargin />}
          </View>
        ) : (
          <BlinkingBar addMargin />
        ),
    },
  ]);
}

export default MessageTextRenderer;
