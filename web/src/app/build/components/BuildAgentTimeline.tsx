"use client";

import React, { useState, useMemo } from "react";
import { SvgChevronDown } from "@opal/icons";
import { cn } from "@/lib/utils";
import { BuildMessage } from "@/app/build/services/buildStreamingModels";
import Text from "@/refresh-components/texts/Text";
import BuildToolCallRenderer from "@/app/build/components/renderers/BuildToolCallRenderer";

interface BuildAgentTimelineProps {
  messages: BuildMessage[];
}

/**
 * BuildAgentTimeline - Displays messages with metadata in chronological order
 *
 * Reconstructs the agent's execution timeline from saved messages:
 * - Tool calls (tool_call_start, tool_call_progress)
 * - Thinking steps (agent_thought_chunk)
 * - Plan updates (agent_plan_update)
 */
export default function BuildAgentTimeline({
  messages,
}: BuildAgentTimelineProps) {
  const [isExpanded, setIsExpanded] = useState(true);

  // Filter messages that have metadata (structured events)
  const structuredMessages = useMemo(() => {
    return messages.filter((m) => m.message_metadata?.type);
  }, [messages]);

  if (structuredMessages.length === 0) return null;

  // Group by type for status text
  const toolMessages = structuredMessages.filter(
    (m) =>
      m.message_metadata?.type === "tool_call_start" ||
      m.message_metadata?.type === "tool_call_progress"
  );
  const thinkingMessages = structuredMessages.filter(
    (m) => m.message_metadata?.type === "agent_thought_chunk"
  );
  const planMessages = structuredMessages.filter(
    (m) => m.message_metadata?.type === "agent_plan_update"
  );

  const statusText =
    `${toolMessages.length} ${toolMessages.length === 1 ? "tool" : "tools"}` +
    (thinkingMessages.length > 0
      ? `, ${thinkingMessages.length} thinking`
      : "") +
    (planMessages.length > 0 ? `, ${planMessages.length} plan` : "");

  return (
    <div className="my-2 border border-border-01 bg-background rounded-md overflow-hidden">
      {/* Header */}
      <div
        className="flex items-center justify-between gap-2 px-3 py-2 cursor-pointer hover:bg-background-tint-02 transition-colors"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <Text text02 className="text-sm">
          Agent Activity
        </Text>
        <div className="flex items-center gap-2">
          <Text text03 className="text-xs">
            {statusText}
          </Text>
          <SvgChevronDown
            className={cn(
              "w-4 h-4 stroke-text-400 transition-transform duration-150",
              !isExpanded && "rotate-[-90deg]"
            )}
          />
        </div>
      </div>

      {/* Timeline */}
      <div
        className={cn(
          "overflow-hidden transition-all duration-200",
          isExpanded ? "max-h-[2000px] opacity-100" : "max-h-0 opacity-0"
        )}
      >
        <div className="px-3 pb-3 space-y-0">
          {structuredMessages.map((message, index) => {
            const metadata = message.message_metadata!;
            const type = metadata.type;

            // Render tool calls
            if (type === "tool_call_start" || type === "tool_call_progress") {
              return (
                <BuildToolCallRenderer
                  key={message.id}
                  metadata={metadata}
                  isLastItem={index === structuredMessages.length - 1}
                  isLoading={false}
                />
              );
            }

            // Render thinking steps
            if (type === "agent_thought_chunk") {
              return (
                <BuildToolCallRenderer
                  key={message.id}
                  metadata={{
                    ...metadata,
                    kind: "thought",
                    title: "Thinking",
                  }}
                  isLastItem={index === structuredMessages.length - 1}
                  isLoading={false}
                />
              );
            }

            // Render plan updates
            if (type === "agent_plan_update") {
              return (
                <BuildToolCallRenderer
                  key={message.id}
                  metadata={{
                    ...metadata,
                    kind: "plan",
                    title: "Plan Update",
                  }}
                  isLastItem={index === structuredMessages.length - 1}
                  isLoading={false}
                />
              );
            }

            return null;
          })}
        </div>
      </div>
    </div>
  );
}
