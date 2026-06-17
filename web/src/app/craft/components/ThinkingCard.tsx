"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { cn } from "@opal/utils";
import { Text } from "@opal/components";
import { SvgBubbleText, SvgChevronDown } from "@opal/icons";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/refresh-components/Collapsible";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";

// MinimalMarkdown's default `p` goes through MemoizedParagraph which forces
// the Opal `mainContentBody` preset (~16px). Override every text-bearing
// element here so reasoning renders at a uniform smaller size.
const thinkingP = ({ children }: { children?: ReactNode }) => (
  <p className="text-sm leading-relaxed text-text-03 my-1">{children}</p>
);
const thinkingHeader = ({ children }: { children?: ReactNode }) => (
  <p className="text-sm leading-relaxed text-text-03 font-semibold mt-4 mb-2">
    {children}
  </p>
);

// LLM reasoning typically uses single \n between lines; markdown collapses
// those into whitespace by default. Promote single newlines to paragraph
// breaks so each line keeps its own visible break. Also break around bold
// spans that abut other content — LLMs frequently emit section headers as
// "...prevContent.**Header**NextContent..." without separators, and
// markdown otherwise renders that as inline bold mid-paragraph.
function normalizeThinking(text: string): string {
  let out = text.replace(/(?<!\n)\n(?!\n)/g, "\n\n");
  out = out.replace(/([.!?)\]])(\*\*[^*\n]+\*\*)/g, "$1\n\n$2");
  out = out.replace(/(\*\*[^*\n]+\*\*)(?=[A-Z([])/g, "$1\n\n");
  return out;
}
const thinkingLi = ({ children }: { children?: ReactNode }) => (
  <li className="text-sm leading-relaxed text-text-03 my-0.5">{children}</li>
);
const thinkingUl = ({ children }: { children?: ReactNode }) => (
  <ul className="list-disc ml-4 my-1 text-sm">{children}</ul>
);
const thinkingOl = ({ children }: { children?: ReactNode }) => (
  <ol className="list-decimal ml-4 my-1 text-sm">{children}</ol>
);
const thinkingBlockquote = ({ children }: { children?: ReactNode }) => (
  <blockquote className="text-sm text-text-02 border-l-2 border-border-02 pl-2 my-1">
    {children}
  </blockquote>
);

const THINKING_MARKDOWN_OVERRIDES = {
  p: thinkingP,
  h1: thinkingHeader,
  h2: thinkingHeader,
  h3: thinkingHeader,
  h4: thinkingHeader,
  h5: thinkingHeader,
  h6: thinkingHeader,
  li: thinkingLi,
  ul: thinkingUl,
  ol: thinkingOl,
  blockquote: thinkingBlockquote,
};

interface ThinkingCardProps {
  content: string;
  isStreaming: boolean;
  defaultOpen?: boolean;
}

function ThinkingActivityIcon({ isStreaming }: { isStreaming: boolean }) {
  if (!isStreaming) {
    return <SvgBubbleText className="size-4 shrink-0 stroke-text-03" />;
  }

  return (
    <span
      aria-hidden
      className="relative flex size-4 shrink-0 items-center justify-center"
    >
      <span className="absolute size-3 rounded-full bg-status-info-03 opacity-35 motion-safe:animate-ping motion-reduce:hidden" />
      <span className="size-1.5 rounded-full bg-status-info-05" />
    </span>
  );
}

export default function ThinkingCard({
  content,
  isStreaming,
  defaultOpen = false,
}: ThinkingCardProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  if (!content) return null;

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger asChild>
        <button
          className={cn(
            "group w-full text-left px-3 py-1.5 rounded-md transition-colors duration-200",
            "hover:bg-background-tint-02 motion-reduce:transition-none"
          )}
        >
          <div className="flex items-center gap-2 min-w-0 w-full">
            <ThinkingActivityIcon isStreaming={isStreaming} />
            <Text font="main-ui-muted" color="text-04" nowrap>
              {isStreaming ? "Thinking..." : "Thinking"}
            </Text>
            <SvgChevronDown
              className={cn(
                "size-4 stroke-text-03 transition-all duration-150 shrink-0 ml-auto motion-reduce:transition-none",
                "group-hover:stroke-text-05",
                !isOpen && "-rotate-90"
              )}
            />
          </div>
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="px-3 pb-2 pt-0">
          <div className="py-1 max-h-48 overflow-y-auto">
            <MinimalMarkdown
              content={normalizeThinking(content)}
              className="text-text-03 prose-sm"
              streaming={isStreaming}
              components={THINKING_MARKDOWN_OVERRIDES}
            />
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
