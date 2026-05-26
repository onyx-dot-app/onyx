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
import {
  TimelineRow,
  TimelineRowRailVariant,
} from "@/app/app/message/messageComponents/timeline/primitives/TimelineRow";
import { TimelineSurface } from "@/app/app/message/messageComponents/timeline/primitives/TimelineSurface";
import { SvgLoader } from "@/app/craft/components/tool-cards/helpers";
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
  isFirstStep?: boolean;
  isLastStep?: boolean;
  railVariant?: TimelineRowRailVariant;
}

function renderRailIcon(isStreaming: boolean) {
  const baseClass =
    "h-(--timeline-icon-size) w-(--timeline-icon-size) shrink-0";
  if (isStreaming) {
    return (
      <SvgLoader
        className={cn(baseClass, "stroke-status-info-05 animate-spin")}
      />
    );
  }
  return <SvgBubbleText className={cn(baseClass, "stroke-text-03")} />;
}

export default function ThinkingCard({
  content,
  isStreaming,
  isFirstStep = true,
  isLastStep = true,
  railVariant = "rail",
}: ThinkingCardProps) {
  const [isOpen, setIsOpen] = useState(false);

  if (!content) return null;

  return (
    <TimelineRow
      railVariant={railVariant}
      icon={renderRailIcon(isStreaming)}
      showIcon={railVariant === "rail"}
      isFirst={isFirstStep}
      isLast={isLastStep}
    >
      <TimelineSurface
        className="flex flex-col"
        roundedTop={isFirstStep}
        roundedBottom={isLastStep}
      >
        <Collapsible open={isOpen} onOpenChange={setIsOpen}>
          <CollapsibleTrigger asChild>
            <button
              className={cn(
                "group w-full text-left px-3 py-2 rounded-md transition-colors",
                "hover:bg-background-tint-02"
              )}
            >
              <div className="flex items-center gap-2 min-w-0 w-full">
                <Text font="main-ui-muted" color="text-04" nowrap>
                  Thinking
                </Text>
                <SvgChevronDown
                  className={cn(
                    "size-4 stroke-text-03 transition-all duration-150 shrink-0 ml-auto",
                    "group-hover:stroke-text-05",
                    !isOpen && "-rotate-90"
                  )}
                />
              </div>
            </button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="px-3 pb-2 pt-0">
              <div className="border-l border-border-02 pl-3 py-1 max-h-48 overflow-y-auto">
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
      </TimelineSurface>
    </TimelineRow>
  );
}
