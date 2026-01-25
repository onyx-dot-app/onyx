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
  SvgSearch,
  SvgGlobe,
} from "@opal/icons";
import RawOutputBlock from "@/app/build/components/RawOutputBlock";
import DiffView from "@/app/build/components/DiffView";
import { ToolCallState, ToolCallKind } from "@/app/build/types/displayTypes";

interface WorkingLineProps {
  toolCall: ToolCallState;
}

/**
 * Get icon based on tool kind and title
 */
function getToolIcon(kind: ToolCallKind, title: string) {
  // Check title for search-related tools
  if (
    title === "Searching files" ||
    title === "Searching content" ||
    title === "Searching"
  ) {
    return SvgSearch;
  }
  if (title === "Searching web" || title === "Fetching web content") {
    return SvgGlobe;
  }

  switch (kind) {
    case "execute":
      return SvgTerminalSmall;
    case "read":
      return SvgFileText;
    case "other":
      return SvgEdit;
    default:
      return SvgTerminalSmall;
  }
}

/**
 * Get status icon and styling
 */
function getStatusDisplay(status: string) {
  switch (status) {
    case "pending":
    case "in_progress":
      return {
        icon: SvgLoader,
        iconClass: "stroke-status-info-05 animate-spin",
      };
    case "completed":
      return {
        icon: SvgCheckSquare,
        iconClass: "stroke-status-success-05",
      };
    case "failed":
      return {
        icon: SvgAlertCircle,
        iconClass: "stroke-status-error-05",
      };
    default:
      return {
        icon: null,
        iconClass: "stroke-text-03",
      };
  }
}

/**
 * Get language hint for syntax highlighting
 */
function getLanguageHint(toolCall: ToolCallState): string | undefined {
  // Search results - no highlighting for file lists
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
    case "read":
    case "other":
      // Use description (file path) for syntax detection
      return toolCall.description;
    default:
      return undefined;
  }
}

/**
 * WorkingLine - A single expandable line within the Working pill.
 *
 * Shows: [status icon] [action text] [expand arrow]
 * Expands to show detailed content (diff view or raw output)
 */
export default function WorkingLine({ toolCall }: WorkingLineProps) {
  const [isOpen, setIsOpen] = useState(false);

  const statusDisplay = getStatusDisplay(toolCall.status);
  const StatusIcon = statusDisplay.icon;
  const ToolIcon = getToolIcon(toolCall.kind, toolCall.title);

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <div className="rounded-md overflow-hidden">
        <CollapsibleTrigger asChild>
          <button
            className={cn(
              "w-full flex gap-2 py-1.5 px-2 rounded-md",
              "hover:bg-background-tint-02 transition-colors text-left",
              isOpen ? "items-start" : "items-center"
            )}
          >
            {/* Status indicator */}
            {StatusIcon ? (
              <StatusIcon
                className={cn(
                  "size-3.5 shrink-0",
                  statusDisplay.iconClass,
                  isOpen && "mt-0.5"
                )}
              />
            ) : (
              <ToolIcon
                className={cn(
                  "size-3.5 stroke-text-03 shrink-0",
                  isOpen && "mt-0.5"
                )}
              />
            )}

            {/* Action text */}
            <span
              className={cn(
                "text-sm flex-1",
                isOpen ? "break-all whitespace-pre-wrap" : "truncate"
              )}
            >
              {toolCall.kind === "execute" && toolCall.description ? (
                <>
                  {/* For execute: show description as primary, command as secondary */}
                  <span className="text-text-04">
                    {toolCall.description.charAt(0).toUpperCase() +
                      toolCall.description.slice(1)}
                  </span>
                  {toolCall.command && (
                    <span className="text-text-02"> {toolCall.command}</span>
                  )}
                </>
              ) : (
                <>
                  <span className="text-text-04">{toolCall.title}</span>
                  {toolCall.description &&
                    toolCall.description !== toolCall.title && (
                      <span className="text-text-02">
                        {" "}
                        {toolCall.description}
                      </span>
                    )}
                </>
              )}
            </span>

            {/* Expand arrow */}
            <SvgChevronDown
              className={cn(
                "size-3.5 stroke-text-03 transition-transform duration-150 shrink-0",
                !isOpen && "rotate-[-90deg]"
              )}
            />
          </button>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <div className="pl-6 pr-2 pb-2">
            {/* Show diff view for edit operations (not new files) */}
            {toolCall.title === "Editing file" &&
            toolCall.oldContent !== undefined &&
            toolCall.newContent !== undefined ? (
              <DiffView
                oldContent={toolCall.oldContent}
                newContent={toolCall.newContent}
                maxHeight="200px"
                filePath={toolCall.description}
              />
            ) : (
              <RawOutputBlock
                content={toolCall.rawOutput}
                maxHeight="200px"
                language={getLanguageHint(toolCall)}
              />
            )}
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}
