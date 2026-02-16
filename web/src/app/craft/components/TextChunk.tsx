"use client";

import MinimalMarkdown from "@/components/chat/MinimalMarkdown";

interface TextChunkProps {
  content: string;
}

/**
 * TextChunk - Renders markdown text content
 *
 * Uses MinimalMarkdown for consistent rendering with the main chat.
 */
export default function TextChunk({ content }: TextChunkProps) {
  if (!content) return null;

  return (
    <div className="py-1">
      <MinimalMarkdown content={content} className="text-text-05" />
    </div>
  );
}
