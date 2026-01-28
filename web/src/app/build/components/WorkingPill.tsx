"use client";

import { useState, useEffect } from "react";
import { cn } from "@/lib/utils";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/refresh-components/Collapsible";
import { SvgChevronDown, SvgPencilRuler } from "@opal/icons";
import { ToolCallState } from "@/app/build/types/displayTypes";
import WorkingLine from "@/app/build/components/WorkingLine";

interface WorkingPillProps {
  toolCalls: ToolCallState[];
  /** Whether this is the latest/active working group - auto-collapses when false */
  isLatest?: boolean;
}

/**
 * WorkingPill - Consolidates multiple tool calls into a single expandable container.
 *
 * Features:
 * - Auto-expanded by default when isLatest
 * - Auto-collapses when a newer Working pill appears (isLatest becomes false)
 * - Each action renders as an expandable WorkingLine
 */
export default function WorkingPill({
  toolCalls,
  isLatest = true,
}: WorkingPillProps) {
  const [isOpen, setIsOpen] = useState(true); // Auto-expanded by default

  // Auto-collapse when this is no longer the latest working group
  useEffect(() => {
    if (!isLatest) {
      setIsOpen(false);
    }
  }, [isLatest]);

  // Check if any tool is in progress (for background color)
  const hasInProgress = toolCalls.some(
    (tc) => tc.status === "pending" || tc.status === "in_progress"
  );

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
              {/* Static icon */}
              <SvgPencilRuler className="size-4 stroke-text-03 shrink-0" />

              {/* Title */}
              <span className="text-sm font-medium text-text-04">Working</span>
            </div>

            {/* Expand arrow */}
            <SvgChevronDown
              className={cn(
                "size-4 stroke-text-03 transition-transform duration-150 shrink-0",
                !isOpen && "rotate-[-90deg]"
              )}
            />
          </button>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <div className="pl-5 pr-3 pb-3 pt-0 space-y-1">
            {toolCalls.map((toolCall) => (
              <WorkingLine key={toolCall.id} toolCall={toolCall} />
            ))}
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}
