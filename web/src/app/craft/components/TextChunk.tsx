"use client";

import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import { BlinkingBar } from "@/app/app/message/BlinkingBar";
import { useSmoothStreaming } from "@/hooks/useSmoothStreaming";
import { useTypewriter } from "@/hooks/useTypewriter";

interface TextChunkProps {
  content: string;
  /** True while this text is actively streaming in. */
  isStreaming?: boolean;
}

export default function TextChunk({
  content,
  isStreaming = false,
}: TextChunkProps) {
  const { enabled: smoothStreaming } = useSmoothStreaming();
  const animate = isStreaming && smoothStreaming;
  const { displayed } = useTypewriter(content, animate, !isStreaming);
  const visible = animate ? displayed : content;

  if (!visible && !isStreaming) return null;

  return (
    <div className="py-1">
      <MinimalMarkdown
        content={visible}
        className="text-text-05"
        streaming={isStreaming}
      />
      {isStreaming && <BlinkingBar />}
    </div>
  );
}
