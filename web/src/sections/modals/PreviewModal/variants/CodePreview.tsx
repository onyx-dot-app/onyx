"use client";

import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import "@/app/app/message/custom-code-styles.css";

interface CodePreviewProps {
  content: string;
  language?: string | null;
}

export function CodePreview({ content, language }: CodePreviewProps) {
  const normalizedContent = content.replace(/~~~/g, "\\~\\~\\~");
  const fenceHeader = language ? `~~~${language}` : "~~~";

  return (
    <MinimalMarkdown
      content={`${fenceHeader}\n${normalizedContent}\n~~~`}
      className="w-full h-full break-words"
      showHeader={false}
    />
  );
}
