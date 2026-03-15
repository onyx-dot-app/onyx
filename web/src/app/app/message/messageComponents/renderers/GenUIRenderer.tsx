"use client";

import React, { useEffect, useMemo } from "react";
import {
  PacketType,
  GenUIPacket,
  GenUIDelta,
  SectionEnd,
} from "../../../services/streamingModels";
import { MessageRenderer, RenderType } from "../interfaces";
import { Renderer } from "@onyx/genui-react";
import { onyxLibrary } from "@onyx/genui-onyx";

function extractGenUIContent(packets: GenUIPacket[]): {
  content: string;
  isComplete: boolean;
} {
  const deltas = packets
    .filter((p) => p.obj.type === PacketType.GENUI_DELTA)
    .map((p) => p.obj as GenUIDelta);

  const hasEnd = packets.some(
    (p) =>
      p.obj.type === PacketType.SECTION_END || p.obj.type === PacketType.ERROR
  );

  const content = deltas.map((d) => d.content).join("");

  return { content, isComplete: hasEnd };
}

export const GenUIRenderer: MessageRenderer<GenUIPacket, {}> = ({
  packets,
  onComplete,
  renderType,
  stopPacketSeen,
  children,
}) => {
  const { content, isComplete } = extractGenUIContent(packets);

  useEffect(() => {
    if (isComplete) {
      onComplete();
    }
  }, [isComplete, onComplete]);

  const isStreaming = !isComplete && !stopPacketSeen;

  if (renderType === RenderType.FULL) {
    return children([
      {
        icon: null,
        status: null,
        content: (
          <Renderer
            response={content || null}
            library={onyxLibrary}
            isStreaming={isStreaming}
            fallbackToMarkdown
          />
        ),
      },
    ]);
  }

  return children([
    {
      icon: null,
      status: isStreaming ? "Generating..." : "Generated UI",
      content: (
        <Renderer
          response={content || null}
          library={onyxLibrary}
          isStreaming={isStreaming}
          fallbackToMarkdown
        />
      ),
    },
  ]);
};
