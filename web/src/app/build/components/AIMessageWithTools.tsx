"use client";

import { BuildMessage } from "@/app/build/services/buildStreamingModels";
import Text from "@/refresh-components/texts/Text";
import Logo from "@/refresh-components/Logo";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import BuildAgentTimeline from "@/app/build/components/BuildAgentTimeline";
import { SvgLoader } from "@opal/icons";

interface AIMessageWithToolsProps {
  content: string;
  /** Structured event messages (tool calls, thinking, plans) to display in timeline */
  eventMessages?: BuildMessage[];
  isStreaming?: boolean;
}

/**
 * AIMessageWithTools - AI message display with tool call activity
 *
 * Shows:
 * - Agent timeline (tool calls, thinking, plans) when present
 * - Message content with markdown rendering
 * - Loading indicator when streaming
 */
export default function AIMessageWithTools({
  content,
  eventMessages = [],
  isStreaming = false,
}: AIMessageWithToolsProps) {
  const hasContent = content.length > 0;
  const hasEvents = eventMessages.length > 0;
  const hasActiveEvents = eventMessages.some(
    (msg) => msg.message_metadata?.status === "in_progress"
  );

  // Don't render anything if there's no content and no events
  if (!hasContent && !hasEvents && !isStreaming) {
    return null;
  }

  return (
    <div className="flex items-start gap-3 py-4">
      <div className="shrink-0 mt-0.5">
        <Logo folded size={24} />
      </div>
      <div className="flex-1 flex flex-col gap-3 min-w-0">
        {/* Agent timeline section */}
        {hasEvents && (
          <div className="flex flex-col gap-2">
            <BuildAgentTimeline messages={eventMessages} />
          </div>
        )}

        {/* Message content */}
        {!hasContent && isStreaming ? (
          <div className="flex items-center gap-2 py-1">
            <SvgLoader className="size-4 stroke-text-03 animate-spin" />
            <Text secondaryBody text03>
              {hasActiveEvents ? "Working..." : "Thinking..."}
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
