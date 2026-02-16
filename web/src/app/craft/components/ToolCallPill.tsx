"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/refresh-components/Collapsible";
import {
  SvgChevronDown,
  SvgTerminalSmall,
  SvgFileText,
  SvgEdit,
  SvgLoader,
  SvgCheckSquare,
  SvgAlertCircle,
  SvgBubbleText,
} from "@opal/icons";
import RawOutputBlock from "@/app/craft/components/RawOutputBlock";
import DiffView from "@/app/craft/components/DiffView";
import { ToolCallState, ToolCallKind } from "@/app/craft/types/displayTypes";

interface ToolCallPillProps {
  toolCall: ToolCallState;
}

/**
 * Get icon based on tool kind
 */
function getToolIcon(kind: ToolCallKind) {
  switch (kind) {
    case "execute":
      return SvgTerminalSmall;
    case "read":
      return SvgFileText;
    case "task":
      return SvgBubbleText;
    case "other":
      return SvgEdit;
    default:
      return SvgTerminalSmall;
  }
}

/**
 * Get status icon and color
 */
function getStatusDisplay(status: string) {
  switch (status) {
    case "pending":
      return {
        icon: null,
        iconClass: "stroke-status-info-05",
        bgClass: "bg-status-info-01 border-status-info-01",
        showSpinner: true,
      };
    case "in_progress":
      return {
        icon: null,
        iconClass: "stroke-status-info-05",
        bgClass: "bg-status-info-01 border-status-info-01",
        showSpinner: true,
      };
    case "completed":
      return {
        icon: SvgCheckSquare,
        iconClass: "stroke-status-success-05",
        bgClass: "bg-background-neutral-01 border-border-01",
        showSpinner: false,
      };
    case "failed":
      return {
        icon: SvgAlertCircle,
        iconClass: "stroke-status-error-05",
        bgClass: "bg-status-error-01 border-status-error-01",
        showSpinner: false,
      };
    default:
      return {
        icon: null,
        iconClass: "stroke-text-03",
        bgClass: "bg-background-neutral-01 border-border-01",
        showSpinner: false,
      };
  }
}

/**
 * Get language hint for syntax highlighting based on tool kind and title
 */
function getLanguageHint(toolCall: ToolCallState): string | undefined {
  // Search results (glob/grep) - no highlighting for file lists
  if (
    toolCall.title === "Searching files" ||
    toolCall.title === "Searching content" ||
    toolCall.title === "Searching"
  ) {
    return undefined;
  }

  switch (toolCall.kind) {
    case "execute":
      return "bash";
    case "task":
      return "markdown";
    case "read":
    case "other":
      // Use description (file path) for syntax detection
      return toolCall.description;
    default:
      return undefined;
  }
}

/**
 * ToolCallPill - Expandable pill for tool calls
 *
 * Shows description and command in collapsed state.
 * Expands to show raw output.
 *
 * Status icons:
 * - pending: gray circle
 * - in_progress: blue spinner
 * - completed: green checkmark
 * - failed: red X
 */
export default function ToolCallPill({ toolCall }: ToolCallPillProps) {
  const [isOpen, setIsOpen] = useState(false);

  const Icon = getToolIcon(toolCall.kind);
  const statusDisplay = getStatusDisplay(toolCall.status);
  const StatusIcon = statusDisplay.icon;

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <div
        className={cn(
          "w-full border-[0.5px] rounded-lg overflow-hidden transition-colors",
          "hover:bg-background-tint-02",
          statusDisplay.bgClass
        )}
      >
        <CollapsibleTrigger asChild>
          <button
            className={cn(
              "w-full flex flex-col gap-1 px-3 py-2",
              "transition-colors text-left"
            )}
          >
            {/* Top row: status icon + title + description + expand arrow */}
            <div className="flex items-center justify-between gap-2 w-full">
              <div className="flex items-center gap-2 min-w-0 flex-1">
                {/* Status indicator */}
                {statusDisplay.showSpinner ? (
                  <SvgLoader className="size-4 stroke-status-info-05 animate-spin shrink-0" />
                ) : StatusIcon ? (
                  <StatusIcon
                    className={cn("size-4 shrink-0", statusDisplay.iconClass)}
                  />
                ) : (
                  <Icon className="size-4 stroke-text-03 shrink-0" />
                )}

                {/* Title (action) */}
                <span className="text-sm font-medium text-text-04 shrink-0">
                  {toolCall.title}
                </span>

                {/* Description (target) */}
                {toolCall.description && (
                  <span className="text-sm text-text-03 truncate">
                    {toolCall.description}
                  </span>
                )}
              </div>

              {/* Expand arrow */}
              <SvgChevronDown
                className={cn(
                  "size-4 stroke-text-03 transition-transform duration-150 shrink-0",
                  !isOpen && "rotate-[-90deg]"
                )}
              />
            </div>

            {/* Bottom row: command in monospace (for execute tools) */}
            {toolCall.kind === "execute" && toolCall.command && (
              <div
                className="text-xs text-text-03 truncate pl-6"
                style={{ fontFamily: "var(--font-dm-mono)" }}
              >
                {toolCall.command}
              </div>
            )}
          </button>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <div className="px-3 pb-3 pt-0">
            {/* Show diff view for edit operations (not new files) */}
            {toolCall.title === "Editing file" &&
            toolCall.oldContent !== undefined &&
            toolCall.newContent !== undefined ? (
              <DiffView
                oldContent={toolCall.oldContent}
                newContent={toolCall.newContent}
                maxHeight="300px"
                filePath={toolCall.description}
              />
            ) : (
              <RawOutputBlock
                content={toolCall.rawOutput}
                maxHeight="300px"
                language={getLanguageHint(toolCall)}
              />
            )}
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}
