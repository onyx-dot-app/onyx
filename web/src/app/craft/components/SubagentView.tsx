"use client";

import { useMemo, useRef } from "react";
import { Text } from "@opal/components";
import { useSubagent } from "@/app/craft/hooks/useBuildSessionStore";
import BuildMessageList from "@/app/craft/components/BuildMessageList";
import type { BuildMessage } from "@/app/craft/types/streamingTypes";
import type {
  SubagentState,
  SubagentTurn,
} from "@/app/craft/types/displayTypes";
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

  const { messages, activeStreamItems } = useMemo<{
    messages: BuildMessage[];
    activeStreamItems: StreamItem[];
  }>(() => {
    if (!subagent) return { messages: [], activeStreamItems: [] };
    const out: BuildMessage[] = [];
    let activeItems: StreamItem[] = [];
    subagent.turns.forEach((turn, i) => {
      const prompt = promptForTurn(subagent, turn, i);
      if (prompt) {
        out.push({
          id: `${subagentSessionId}-u${i}`,
          type: "user",
          content: prompt,
          timestamp: new Date(),
        });
      }
      const isActiveTurn = isRunningActiveTurn(subagent, i);
      const streamItems = turnToStreamItems(
        turn,
        subagentSessionId,
        i,
        isActiveTurn
      );
      if (isActiveTurn) {
        activeItems = streamItems;
        return;
      }
      out.push({
        id: `${subagentSessionId}-a${i}`,
        type: "assistant",
        content: turn.response ?? "",
        timestamp: new Date(),
        message_metadata: { streamItems },
      });
    });
    return { messages: out, activeStreamItems: activeItems };
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
      streamItems={activeStreamItems}
      isStreaming={subagent.status === "running"}
      autoScrollEnabled={subagent.status === "running"}
      scrollContainerRef={scrollRef}
    />
  );
}

function promptForTurn(
  subagent: SubagentState,
  turn: SubagentTurn,
  index: number
): string {
  const name = index === 0 ? subagent.name : "";
  if (!turn.prompt) return name;
  if (!name || turn.prompt.includes(name)) return turn.prompt;
  return `${name}\n\n${turn.prompt}`;
}

function isRunningActiveTurn(subagent: SubagentState, index: number): boolean {
  return subagent.status === "running" && index === subagent.turns.length - 1;
}

function turnToStreamItems(
  turn: SubagentTurn,
  subagentSessionId: string,
  turnIndex: number,
  isActiveTurn: boolean
): StreamItem[] {
  if (turn.streamItems.length > 0) {
    return turn.streamItems;
  }

  return [
    ...(turn.thinking !== null
      ? [
          {
            type: "thinking" as const,
            id: `${subagentSessionId}-t${turnIndex}`,
            content: turn.thinking,
            isStreaming: isActiveTurn,
          },
        ]
      : []),
    ...turn.toolCalls.map((tc) => ({
      type: "tool_call" as const,
      id: tc.id,
      toolCall: tc,
    })),
    ...(turn.response !== null
      ? [
          {
            type: "text" as const,
            id: `${subagentSessionId}-r${turnIndex}`,
            content: turn.response,
            isStreaming: isActiveTurn,
          },
        ]
      : []),
  ];
}
