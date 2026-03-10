"use client";

import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import ScrollIndicatorDiv from "@/refresh-components/ScrollIndicatorDiv";
import { cn } from "@/lib/utils";
import "@/app/app/message/custom-code-styles.css";

interface CodePreviewProps {
  content: string;
  language?: string | null;
  normalize?: boolean;
}

export function CodePreview({
  content,
  language,
  normalize,
}: CodePreviewProps) {
  const markdownContent = normalize
    ? `~~~${language || ""}\n${content.replace(/~~~/g, "\\~\\~\\~")}\n~~~`
    : content;

  return (
    <ScrollIndicatorDiv
      className={cn("p-4", normalize && "bg-background-code-01")}
      backgroundColor={normalize ? "var(--background-code-01)" : undefined}
      variant="shadow"
      bottomSpacing="2rem"
      disableBottomIndicator
    >
      <MinimalMarkdown content={markdownContent} showHeader={false} />
    </ScrollIndicatorDiv>
  );
}
