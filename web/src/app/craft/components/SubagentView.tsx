"use client";

import { useMemo, useRef } from "react";
import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { useSubagent } from "@/app/craft/hooks/useBuildSessionStore";
import BuildMessageList from "@/app/craft/components/BuildMessageList";
import type { BuildMessage } from "@/app/craft/types/streamingTypes";
import type {
  SubagentState,
  SubagentTurn,
} from "@/app/craft/types/displayTypes";
import type { TimelineEvent } from "@/lib/timeline/events";

interface SubagentViewProps {
  subagentSessionId: string;
}

/**
 * SubagentView - Read-only transcript of a subagent's run. Reuses the main
 * chat renderer (BuildMessageList): each turn becomes a user message (the
 * dispatch prompt) + an assistant message whose timeline events are the
 * subagent's thinking, tool calls and response — so the transcript mirrors
 * the main conversation.
 */
export default function SubagentView({ subagentSessionId }: SubagentViewProps) {
  const t = useTranslations("craft.subagentView");
  const subagent = useSubagent(subagentSessionId);
  // Static transcript (autoScroll off) — ref only satisfies the prop contract.
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const { messages, activeEvents } = useMemo<{
    messages: BuildMessage[];
    activeEvents: TimelineEvent[];
  }>(() => {
    if (!subagent) return { messages: [], activeEvents: [] };
    const out: BuildMessage[] = [];
    let active: TimelineEvent[] = [];
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
      if (isRunningActiveTurn(subagent, i)) {
        active = turn.timelineEvents;
        return;
      }
      out.push({
        id: `${subagentSessionId}-a${i}`,
        type: "assistant",
        content: turn.response ?? "",
        timestamp: new Date(),
        timelineEvents: turn.timelineEvents,
      });
    });
    return { messages: out, activeEvents: active };
  }, [subagent, subagentSessionId]);

  if (!subagent) {
    return (
      <div className="flex h-full items-center justify-center">
        <Text font="main-ui-body" color="text-02">
          {t("notFound.label")}
        </Text>
      </div>
    );
  }

  return (
    <BuildMessageList
      sessionId={null}
      messages={messages}
      timelineEvents={activeEvents}
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
