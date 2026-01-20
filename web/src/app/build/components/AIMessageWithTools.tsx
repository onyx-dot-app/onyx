"use client";

import { ToolCall } from "@/app/build/services/buildStreamingModels";
import Text from "@/refresh-components/texts/Text";
import Logo from "@/refresh-components/Logo";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import ToolCallList from "@/app/build/components/ToolCallList";
import { SvgLoader } from "@opal/icons";

interface AIMessageWithToolsProps {
  content: string;
  toolCalls: ToolCall[];
  isStreaming?: boolean;
}

/**
 * AIMessageWithTools - AI message display with tool call activity
 *
 * Shows:
 * - Tool calls (when present) above the message content
 * - Message content with markdown rendering
 * - Loading indicator when streaming
 */
export default function AIMessageWithTools({
  content,
  toolCalls,
  isStreaming = false,
}: AIMessageWithToolsProps) {
  const hasContent = content.length > 0;
  const hasToolCalls = toolCalls.length > 0;
  const hasActiveToolCalls = toolCalls.some(
    (tc) => tc.status === "in_progress" || tc.status === "pending"
  );

  return (
    <div className="flex items-start gap-3 py-4">
      <div className="shrink-0 mt-0.5">
        <Logo folded size={24} />
      </div>
      <div className="flex-1 flex flex-col gap-3 min-w-0">
        {/* Tool calls section */}
        {hasToolCalls && (
          <div className="flex flex-col gap-2">
            <ToolCallList toolCalls={toolCalls} />
          </div>
        )}

        {/* Message content */}
        {!hasContent && isStreaming ? (
          <div className="flex items-center gap-2 py-1">
            <SvgLoader className="size-4 stroke-text-03 animate-spin" />
            <Text secondaryBody text03>
              {hasActiveToolCalls ? "Working..." : "Thinking..."}
            </Text>
          </div>
        ) : hasContent ? (
          <>
            <div className="py-1">
              <MinimalMarkdown content={content} className="text-text-05" />
            </div>
            {isStreaming && (
              <div className="flex items-center gap-1">
                <SvgLoader className="size-3 stroke-text-03 animate-spin" />
              </div>
            )}
          </>
        ) : null}
      </div>
    </div>
  );
}
