"use client";

import {
  ToolCall,
  ToolCallStatus,
} from "@/app/build/services/buildStreamingModels";
import Text from "@/refresh-components/texts/Text";
import { SvgLoader, SvgCheck, SvgX, SvgSettings } from "@opal/icons";
import { cn } from "@/lib/utils";

interface ToolCallItemProps {
  toolCall: ToolCall;
  compact?: boolean;
}

/**
 * Get icon and color based on tool call status
 */
function getStatusDisplay(status: ToolCallStatus) {
  switch (status) {
    case "pending":
      return {
        icon: <SvgSettings className="size-3.5 text-text-03" />,
        color: "text-text-03",
        bgColor: "bg-background-02",
      };
    case "in_progress":
      return {
        icon: <SvgLoader className="size-3.5 text-accent-blue animate-spin" />,
        color: "text-accent-blue",
        bgColor: "bg-accent-blue/10",
      };
    case "completed":
      return {
        icon: <SvgCheck className="size-3.5 text-accent-green" />,
        color: "text-accent-green",
        bgColor: "bg-accent-green/10",
      };
    case "failed":
      return {
        icon: <SvgX className="size-3.5 text-accent-red" />,
        color: "text-accent-red",
        bgColor: "bg-accent-red/10",
      };
    case "cancelled":
      return {
        icon: <SvgX className="size-3.5 text-text-03" />,
        color: "text-text-03",
        bgColor: "bg-background-02",
      };
    default:
      return {
        icon: <SvgSettings className="size-3.5 text-text-03" />,
        color: "text-text-03",
        bgColor: "bg-background-02",
      };
  }
}

/**
 * Get a human-readable tool name from kind and name
 */
function getToolDisplayName(toolCall: ToolCall): string {
  const { kind, name, title } = toolCall;

  // Use title if available
  if (title && title !== `Running ${kind}...`) {
    return title;
  }

  // Map common tool kinds to friendly names
  const kindMap: Record<string, string> = {
    edit: "Edit",
    execute: "Execute",
    other: "",
  };

  const nameMap: Record<string, string> = {
    write: "Writing file",
    bash: "Running command",
    ls: "Listing files",
    todowrite: "Updating tasks",
    read: "Reading file",
    grep: "Searching",
  };

  const friendlyName = nameMap[name.toLowerCase()];
  if (friendlyName) return friendlyName;

  const prefix = kindMap[kind.toLowerCase()] || kind;
  return prefix ? `${prefix}: ${name}` : name;
}

/**
 * ToolCallItem - Displays a single tool call with status
 */
export default function ToolCallItem({
  toolCall,
  compact = false,
}: ToolCallItemProps) {
  const { icon, color, bgColor } = getStatusDisplay(toolCall.status);
  const displayName = getToolDisplayName(toolCall);

  if (compact) {
    return (
      <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-background-02">
        {icon}
        <Text secondaryMono text03 className="truncate max-w-[200px]">
          {displayName}
        </Text>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "flex items-center gap-2 px-3 py-2 rounded-lg border border-border-01 transition-colors",
        bgColor
      )}
    >
      <div className="shrink-0">{icon}</div>
      <div className="flex-1 min-w-0">
        <Text secondaryBody className={cn("truncate", color)}>
          {displayName}
        </Text>
        {toolCall.error && (
          <Text secondaryMono text03 className="truncate mt-0.5">
            {toolCall.error}
          </Text>
        )}
      </div>
    </div>
  );
}
