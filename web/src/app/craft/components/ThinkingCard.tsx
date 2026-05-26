"use client";

import { useState } from "react";
import { cn } from "@opal/utils";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/refresh-components/Collapsible";
import { Text } from "@opal/components";
import { SvgChevronDown, SvgBubbleText } from "@opal/icons";

interface ThinkingCardProps {
  content: string;
  isStreaming: boolean;
}

const APPROX_CHARS_PER_TOKEN = 4;

function estimateTokens(content: string): number {
  return Math.max(1, Math.round(content.length / APPROX_CHARS_PER_TOKEN));
}

/**
 * ThinkingCard - Expandable card for agent thinking content.
 *
 * Starts collapsed (shows just an "N tokens of thinking" summary). Stays
 * open while actively streaming so the user can watch the thought roll in.
 */
export default function ThinkingCard({
  content,
  isStreaming,
}: ThinkingCardProps) {
  const [isOpen, setIsOpen] = useState(false);

  if (!content) return null;

  const summary = isStreaming
    ? "Thinking..."
    : `Thinking - ~${estimateTokens(content)} tokens`;

  return (
    <Collapsible open={isOpen || isStreaming} onOpenChange={setIsOpen}>
      <div
        className={cn(
          "w-full border-[0.5px] rounded-lg overflow-hidden transition-colors",
          "hover:bg-background-tint-02",
          isStreaming
            ? "border-theme-blue-02 bg-theme-blue-01"
            : "border-border-01 bg-background-neutral-01"
        )}
      >
        <CollapsibleTrigger asChild>
          <button
            className={cn(
              "w-full flex items-center justify-between gap-2 px-3 py-2",
              "transition-colors text-left"
            )}
          >
            <div className="flex items-center gap-2 min-w-0">
              <SvgBubbleText
                className={cn(
                  "size-4 shrink-0",
                  isStreaming ? "stroke-theme-blue-05" : "stroke-text-03"
                )}
              />
              <span className={isStreaming ? "text-theme-blue-05" : ""}>
                <Text
                  font="main-ui-action"
                  color={isStreaming ? "inherit" : "text-04"}
                >
                  {summary}
                </Text>
              </span>
              {isStreaming && (
                <span className="text-theme-blue-04 animate-pulse">
                  <Text font="main-ui-muted" color="inherit">
                    ...
                  </Text>
                </span>
              )}
            </div>
            <SvgChevronDown
              className={cn(
                "size-4 stroke-text-03 transition-transform duration-150",
                !(isOpen || isStreaming) && "-rotate-90"
              )}
            />
          </button>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <div className="px-3 pb-3 pt-0">
            <div
              className={cn(
                "p-3 rounded-08 italic",
                "bg-background-neutral-02 max-h-48 overflow-y-auto",
                "whitespace-pre-wrap wrap-break-word"
              )}
            >
              <Text as="p" font="main-content-muted" color="text-03">
                {content}
              </Text>
            </div>
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}
