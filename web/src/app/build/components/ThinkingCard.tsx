"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/refresh-components/Collapsible";
import { SvgChevronDown, SvgBubbleText } from "@opal/icons";

interface ThinkingCardProps {
  content: string;
  isStreaming: boolean;
}

/**
 * ThinkingCard - Expandable card for agent thinking content
 *
 * Starts open and stays open. User can manually toggle.
 */
export default function ThinkingCard({
  content,
  isStreaming,
}: ThinkingCardProps) {
  const [isOpen, setIsOpen] = useState(true);

  if (!content) return null;

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
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
            <div className="flex items-center gap-2">
              <SvgBubbleText
                className={cn(
                  "size-4",
                  isStreaming ? "stroke-theme-blue-05" : "stroke-text-03"
                )}
              />
              <span
                className={cn(
                  "text-sm font-medium",
                  isStreaming ? "text-theme-blue-05" : "text-text-04"
                )}
              >
                Thinking
              </span>
              {isStreaming && (
                <span className="text-xs text-theme-blue-04 animate-pulse">
                  ...
                </span>
              )}
            </div>
            <SvgChevronDown
              className={cn(
                "size-4 stroke-text-03 transition-transform duration-150",
                !isOpen && "rotate-[-90deg]"
              )}
            />
          </button>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <div className="px-3 pb-3 pt-0">
            <div
              className={cn(
                "p-3 rounded-08 text-sm",
                "bg-background-neutral-02 text-text-03",
                "max-h-48 overflow-y-auto",
                "italic"
              )}
            >
              <p className="whitespace-pre-wrap break-words m-0">{content}</p>
            </div>
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}
