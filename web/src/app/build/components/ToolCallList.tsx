"use client";

import { ToolCall } from "@/app/build/services/buildStreamingModels";
import ToolCallItem from "@/app/build/components/ToolCallItem";

interface ToolCallListProps {
  toolCalls: ToolCall[];
  compact?: boolean;
}

/**
 * ToolCallList - Displays a list of tool calls
 */
export default function ToolCallList({
  toolCalls,
  compact = false,
}: ToolCallListProps) {
  if (toolCalls.length === 0) return null;

  if (compact) {
    return (
      <div className="flex flex-wrap gap-1.5">
        {toolCalls.map((tc) => (
          <ToolCallItem key={tc.id} toolCall={tc} compact />
        ))}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {toolCalls.map((tc) => (
        <ToolCallItem key={tc.id} toolCall={tc} />
      ))}
    </div>
  );
}
