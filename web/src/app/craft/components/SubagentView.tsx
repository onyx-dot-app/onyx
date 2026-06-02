"use client";

import { useMemo, useRef } from "react";
import { Text } from "@opal/components";
import { useSubagent } from "@/app/craft/hooks/useBuildSessionStore";
import BuildMessageList from "@/app/craft/components/BuildMessageList";
import type { BuildMessage } from "@/app/craft/types/streamingTypes";
import type { StreamItem } from "@/app/craft/types/displayTypes";

interface SubagentViewProps {
  subagentSessionId: string;
}

/**
 * SubagentView - Read-only transcript of a subagent's run. Reuses the main
 * chat renderer (BuildMessageList): each turn becomes a user message (the
 * dispatch prompt) + an assistant message whose stream items are the
 * subagent's tool calls and final response — so tool groups, assistant
 * styling, etc. all mirror the main conversation.
 */
export default function SubagentView({ subagentSessionId }: SubagentViewProps) {
  const subagent = useSubagent(subagentSessionId);
  // Static transcript (autoScroll off) — ref only satisfies the prop contract.
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const messages = useMemo<BuildMessage[]>(() => {
    if (!subagent) return [];
    const out: BuildMessage[] = [];
    subagent.turns.forEach((turn, i) => {
      if (turn.prompt) {
        out.push({
          id: `${subagentSessionId}-u${i}`,
          type: "user",
          content: turn.prompt,
          timestamp: new Date(),
        });
      }
      const streamItems: StreamItem[] = [
        ...turn.toolCalls.map((tc) => ({
          type: "tool_call" as const,
          id: tc.id,
          toolCall: tc,
        })),
        ...(turn.response !== null
          ? [
              {
                type: "text" as const,
                id: `${subagentSessionId}-r${i}`,
                content: turn.response,
                isStreaming: false,
              },
            ]
          : []),
      ];
      out.push({
        id: `${subagentSessionId}-a${i}`,
        type: "assistant",
        content: turn.response ?? "",
        timestamp: new Date(),
        message_metadata: { streamItems },
      });
    });
    return out;
  }, [subagent, subagentSessionId]);

  if (!subagent) {
    return (
      <div className="flex h-full items-center justify-center">
        <Text font="main-ui-body" color="text-02">
          Subagent not found.
        </Text>
      </div>
    );
  }

  return (
    <BuildMessageList
      messages={messages}
      streamItems={[]}
      isStreaming={false}
      autoScrollEnabled={false}
      scrollContainerRef={scrollRef}
    />
  );
}
