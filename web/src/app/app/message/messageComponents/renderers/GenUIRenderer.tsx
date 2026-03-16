"use client";

import React, { useEffect } from "react";
import {
  PacketType,
  GenUIPacket,
  GenUIDelta,
} from "../../../services/streamingModels";
import { MessageRenderer, RenderType } from "../interfaces";
import { Renderer } from "@onyx/genui-react";
import { onyxLibrary } from "@onyx/genui-onyx";

/**
 * Strip markdown code fences that some LLMs wrap around GenUI output.
 * Handles ```genui, ```\n, etc.
 */
function stripCodeFences(raw: string): string {
  let s = raw;
  // Strip opening fence: ```genui\n or ```\n
  s = s.replace(/^```[a-zA-Z]*\s*\n?/, "");
  // Strip closing fence at end
  s = s.replace(/\n?```\s*$/, "");
  return s;
}

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

  const raw = deltas.map((d) => d.content).join("");
  const content = stripCodeFences(raw);

  return { content, isComplete: hasEnd };
}

function GeneratingIndicator() {
  return (
    <div className="flex items-center gap-2 py-4 text-text-03">
      <div className="flex gap-1">
        <span className="w-1.5 h-1.5 rounded-full bg-text-04 animate-bounce [animation-delay:0ms]" />
        <span className="w-1.5 h-1.5 rounded-full bg-text-04 animate-bounce [animation-delay:150ms]" />
        <span className="w-1.5 h-1.5 rounded-full bg-text-04 animate-bounce [animation-delay:300ms]" />
      </div>
      <span className="text-sm">Generating structured view...</span>
    </div>
  );
}

export const GenUIRenderer: MessageRenderer<GenUIPacket, {}> = ({
  packets,
  onComplete,
  renderType,
  stopPacketSeen,
  children,
}) => {
  const { content, isComplete } = extractGenUIContent(packets);

  // GenUI responses may not receive an explicit SECTION_END from the backend
  // (content streams end with the overall STOP packet). Treat stopPacketSeen
  // as an alternative completion signal.
  const effectiveComplete = isComplete || stopPacketSeen;

  useEffect(() => {
    if (effectiveComplete) {
      onComplete();
    }
  }, [effectiveComplete, onComplete]);

  const isStreaming = !effectiveComplete;

  // During generation, show a loading indicator instead of streaming
  // partial GenUI content (which can look broken mid-parse).
  if (isStreaming) {
    return children([
      {
        icon: null,
        status: renderType === RenderType.FULL ? null : "Generating...",
        content: <GeneratingIndicator />,
      },
    ]);
  }

  if (renderType === RenderType.FULL) {
    return children([
      {
        icon: null,
        status: null,
        content: (
          <Renderer
            response={content || null}
            library={onyxLibrary}
            isStreaming={false}
            fallbackToMarkdown
          />
        ),
      },
    ]);
  }

  return children([
    {
      icon: null,
      status: "Generated UI",
      content: (
        <Renderer
          response={content || null}
          library={onyxLibrary}
          isStreaming={false}
          fallbackToMarkdown
        />
      ),
    },
  ]);
};
