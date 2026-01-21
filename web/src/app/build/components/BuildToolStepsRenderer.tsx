"use client";

import React, { useState } from "react";
import {
  SvgChevronDown,
  SvgTerminalSmall,
  SvgFileText,
  SvgEdit,
  SvgPlayCircle,
  SvgSettings,
  SvgCheck,
  SvgX,
  SvgLoader,
  SvgMinusCircle,
} from "@opal/icons";
import { cn } from "@/lib/utils";
import {
  ToolCall,
  ToolCallStatus,
} from "@/app/build/services/buildStreamingModels";
import Text from "@/refresh-components/texts/Text";

/**
 * Get the appropriate icon for a tool based on its kind
 */
function getToolIcon(kind: string) {
  const kindLower = kind?.toLowerCase() || "";

  if (kindLower.includes("bash") || kindLower.includes("execute")) {
    return SvgTerminalSmall;
  }
  if (kindLower.includes("write") || kindLower === "edit") {
    return SvgEdit;
  }
  if (kindLower.includes("read")) {
    return SvgFileText;
  }
  return SvgSettings;
}

/**
 * Get status icon based on tool call status
 */
function getStatusIcon(status: ToolCallStatus) {
  switch (status) {
    case "completed":
      return SvgCheck;
    case "failed":
      return SvgX;
    case "in_progress":
      return SvgLoader;
    case "pending":
      return SvgMinusCircle;
    case "cancelled":
      return SvgX;
    default:
      return SvgMinusCircle;
  }
}

/**
 * Extract command from raw_input for technical display
 */
function extractCommand(toolCall: ToolCall): string | null {
  const rawInput = toolCall.raw_input;

  if (!rawInput) return null;

  // For bash/execute tools, extract the command
  if (rawInput.command) {
    return rawInput.command;
  }

  // For file write/edit tools, show the file path
  if (rawInput.file_path || rawInput.path) {
    const path = rawInput.file_path || rawInput.path;
    const operation = toolCall.kind === "edit" ? "Edit" : "Write";
    return `${operation} ${path}`;
  }

  return null;
}

/**
 * Extract user-friendly description from content or title
 */
function extractDescription(toolCall: ToolCall): string {
  // Try to get description from content block
  if (toolCall.content) {
    const content = toolCall.content;
    if (content.type === "text" && content.text) {
      return content.text;
    }
    if (Array.isArray(content)) {
      const textBlocks = content.filter(
        (c: any) => c.type === "text" && c.text
      );
      if (textBlocks.length > 0) {
        return textBlocks.map((c: any) => c.text).join(" ");
      }
    }
  }

  // Fallback to title
  return toolCall.title || toolCall.name || "Running tool...";
}

/**
 * Get status text based on tool status
 */
function getStatusText(status: ToolCallStatus): string {
  switch (status) {
    case "completed":
      return "Complete";
    case "failed":
      return "Failed";
    case "in_progress":
      return "Running";
    case "pending":
      return "Pending";
    case "cancelled":
      return "Cancelled";
    default:
      return "Unknown";
  }
}

/**
 * Single tool step row with vertical connector
 */
function ToolStepRow({
  toolCall,
  isLastItem,
}: {
  toolCall: ToolCall;
  isLastItem: boolean;
}) {
  const ToolIcon = getToolIcon(toolCall.kind);
  const StatusIcon = getStatusIcon(toolCall.status);
  const command = extractCommand(toolCall);
  const description = extractDescription(toolCall);
  const statusText = getStatusText(toolCall.status);
  const isLoading =
    toolCall.status === "in_progress" || toolCall.status === "pending";
  const isFailed = toolCall.status === "failed";

  return (
    <div className="relative">
      {/* Vertical connector line */}
      {!isLastItem && (
        <div
          className="absolute w-px bg-border-02 z-0"
          style={{ left: "10px", top: "20px", bottom: "0" }}
        />
      )}

      <div className={cn("flex items-start gap-2 relative z-10")}>
        {/* Icon circle */}
        <div className="flex flex-col items-center w-5">
          <div className="flex-shrink-0 flex items-center justify-center w-5 h-5 bg-background rounded-full border border-border-01">
            <ToolIcon
              className={cn("w-3.5 h-3.5", isLoading && "text-action-link-01")}
            />
          </div>
        </div>

        {/* Content */}
        <div
          className={cn(
            "flex-1 min-w-0 overflow-hidden",
            !isLastItem && "pb-4"
          )}
        >
          {/* Status and title */}
          <div className="flex items-center gap-2 mb-1">
            <StatusIcon
              className={cn(
                "w-3.5 h-3.5",
                toolCall.status === "completed" && "text-status-success-03",
                toolCall.status === "failed" && "text-status-error-03",
                toolCall.status === "in_progress" &&
                  "text-action-link-01 animate-spin",
                toolCall.status === "pending" && "text-text-03"
              )}
            />
            <Text
              text02
              className={cn(isLoading && !isFailed && "loading-text")}
            >
              {statusText}
            </Text>
          </div>

          {/* User-friendly description */}
          <Text secondaryBody text03 className="mb-1">
            {description}
          </Text>

          {/* Technical command (if available) */}
          {command && (
            <div className="mt-1 px-2 py-1 rounded bg-background-tint-02 border border-border-01">
              <Text secondaryMono text03 className="text-xs break-all">
                {command}
              </Text>
            </div>
          )}

          {/* Error message */}
          {toolCall.error && (
            <div className="mt-1 px-2 py-1 rounded bg-status-error-01 border border-status-error-02">
              <Text secondaryMono className="text-xs text-status-error-03">
                {toolCall.error}
              </Text>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

interface BuildToolStepsRendererProps {
  toolCalls: ToolCall[];
}

/**
 * BuildToolStepsRenderer - Displays tool calls in chronological order
 * with both technical details and user-friendly descriptions.
 *
 * Inspired by ResearchAgentRenderer from deep research UI.
 */
export default function BuildToolStepsRenderer({
  toolCalls,
}: BuildToolStepsRendererProps) {
  const [isExpanded, setIsExpanded] = useState(true);

  if (toolCalls.length === 0) return null;

  // Sort tool calls chronologically
  const sortedToolCalls = [...toolCalls].sort(
    (a, b) => a.startedAt.getTime() - b.startedAt.getTime()
  );

  // Determine overall status
  const hasActiveTools = sortedToolCalls.some(
    (tc) => tc.status === "in_progress" || tc.status === "pending"
  );
  const hasFailedTools = sortedToolCalls.some((tc) => tc.status === "failed");
  const allComplete = sortedToolCalls.every((tc) => tc.status === "completed");

  let statusText: string;
  if (allComplete) {
    statusText = "All steps complete";
  } else if (hasFailedTools) {
    statusText = "Some steps failed";
  } else if (hasActiveTools) {
    const activeTools = sortedToolCalls.filter(
      (tc) => tc.status === "in_progress" || tc.status === "pending"
    );
    const lastActiveTool = activeTools[activeTools.length - 1];
    statusText = lastActiveTool
      ? extractDescription(lastActiveTool)
      : "Processing";
  } else {
    statusText = "Processing";
  }

  return (
    <div className="my-2 p-3 rounded-lg border border-border-01 bg-background-neutral-02">
      {/* Header with toggle */}
      <div
        className="flex items-center justify-between gap-2 cursor-pointer group"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-2">
          <SvgPlayCircle className="w-4 h-4 text-text-03" />
          <Text text02 className="truncate">
            {statusText}
          </Text>
        </div>
        <div className="flex items-center gap-2">
          <Text secondaryMono text03 className="text-xs">
            {sortedToolCalls.length}{" "}
            {sortedToolCalls.length === 1 ? "step" : "steps"}
          </Text>
          <SvgChevronDown
            className={cn(
              "w-4 h-4 stroke-text-03 transition-transform duration-150 ease-in-out",
              !isExpanded && "rotate-[-90deg]"
            )}
          />
        </div>
      </div>

      {/* Collapsible tool steps */}
      <div
        className={cn(
          "overflow-hidden transition-all duration-200 ease-in-out",
          isExpanded ? "max-h-[2000px] opacity-100 mt-3" : "max-h-0 opacity-0"
        )}
      >
        <div className="space-y-0.5">
          {sortedToolCalls.map((toolCall, index) => (
            <ToolStepRow
              key={toolCall.id}
              toolCall={toolCall}
              isLastItem={index === sortedToolCalls.length - 1}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
