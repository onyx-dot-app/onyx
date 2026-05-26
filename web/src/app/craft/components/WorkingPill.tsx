"use client";

import { useState, useEffect } from "react";
import { cn } from "@opal/utils";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/refresh-components/Collapsible";
import { Text } from "@opal/components";
import { SvgChevronDown, SvgPencilRuler } from "@opal/icons";
import { TimelineRoot } from "@/app/app/message/messageComponents/timeline/primitives/TimelineRoot";
import { ToolCallState } from "@/app/craft/types/displayTypes";
import CraftToolCard from "@/app/craft/components/tool-cards/CraftToolCard";

interface WorkingPillProps {
  toolCalls: ToolCallState[];
  /** Whether this is the latest/active working group - auto-collapses when false */
  isLatest?: boolean;
}

/**
 * WorkingPill - Consolidates multiple tool calls into a single expandable container.
 *
 * Stays open while any contained tool is actively running. As soon as all
 * tools settle into terminal status, the pill auto-collapses so a completed
 * turn doesn't leave a noisy expanded list behind. The user can still expand
 * it manually for review.
 */
export default function WorkingPill({
  toolCalls,
  isLatest = true,
}: WorkingPillProps) {
  const hasInProgress = toolCalls.some(
    (tc) => tc.status === "pending" || tc.status === "in_progress"
  );

  const [isOpen, setIsOpen] = useState(hasInProgress);

  // Open while this is the latest group AND work is active; closed otherwise.
  // Symmetric so a tool starting later (false→true on hasInProgress) reopens
  // the pill instead of staying hidden.
  useEffect(() => {
    setIsOpen(isLatest && hasInProgress);
  }, [isLatest, hasInProgress]);

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <div
        className={cn(
          "w-full border-[0.5px] rounded-lg overflow-hidden transition-colors",
          hasInProgress
            ? "bg-status-info-01 border-status-info-01"
            : "bg-background-neutral-01 border-border-01"
        )}
      >
        <CollapsibleTrigger asChild>
          <button
            className={cn(
              "w-full flex items-center justify-between gap-2 px-3 py-2",
              "transition-colors text-left rounded-t-lg",
              "hover:bg-background-tint-02"
            )}
          >
            <div className="flex items-center gap-2 min-w-0 flex-1">
              <SvgPencilRuler className="size-4 stroke-text-03 shrink-0" />
              <Text font="main-ui-action" color="text-04">
                Working
              </Text>
            </div>

            {/* Expand arrow */}
            <SvgChevronDown
              className={cn(
                "size-4 stroke-text-03 transition-transform duration-150 shrink-0",
                !isOpen && "-rotate-90"
              )}
            />
          </button>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <div className="px-3 pb-3 pt-0 space-y-1">
            <TimelineRoot>
              {toolCalls.map((toolCall) => (
                <CraftToolCard
                  key={toolCall.id}
                  toolCall={toolCall}
                  railVariant="none"
                />
              ))}
            </TimelineRoot>
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}
