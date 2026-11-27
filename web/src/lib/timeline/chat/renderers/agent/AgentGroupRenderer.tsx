// Adapted from T3 Code (MIT, github.com/pingdotgg/t3code).

import { type ComponentProps, useEffect } from "react";
import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { formatDurationSeconds } from "@opal/time";
import type { CustomToolPacket } from "@/app/app/services/streamingModels";
import type { MessageRenderer } from "@/lib/timeline/chat/message/messageComponents/types";
import { STEP_ICONS } from "@/lib/timeline/icons";
import {
  isLiveSubagent,
  subagentBucket,
  subagentStartedAt,
  type SubagentBucket,
} from "@/lib/chat/subagents";
import { useSpawnedSubagents } from "@/lib/chat/hooks";
import type { ChatSubagent } from "@/lib/chat/types";
import { useStreamingDuration } from "@/lib/timeline/useStreamingDuration";
import { agentToolCalls } from "@/lib/timeline/chat/renderers/agent/agentTools";
import {
  SubagentCard,
  spawnedSubagentState,
} from "@/lib/timeline/chat/renderers/agent/SubagentCard";

/** Plain text, so the ticks do not flash. */
function Elapsed({ live, startedAt }: { live: boolean; startedAt?: number }) {
  const seconds = useStreamingDuration(live, startedAt);
  if (startedAt === undefined) return null;
  return (
    <Text font="secondary-body" color="text-03" wordWrap="whitespace-nowrap">
      {formatDurationSeconds(Math.max(1, seconds))}
    </Text>
  );
}

const BUCKETS: SubagentBucket[] = ["working", "done", "failed", "stopped"];

/**
 * Agents that one turn spawned together, as T3 Code's subagent group: a count,
 * a summary of their states, the group's run time, and a card per agent that
 * opens it in the main view.
 */
export function AgentGroupRenderer({
  packets,
  onComplete,
  children,
}: ComponentProps<MessageRenderer<CustomToolPacket, {}>>) {
  const t = useTranslations("chat.messages.timeline.agentGroup");
  const calls = agentToolCalls(packets);
  // A failed spawn made no agent
  const { agents, available, complete } = useSpawnedSubagents(
    calls.map((call) => (call.failed ? "" : call.agentName))
  );
  const isComplete = calls.every((call) => call.isComplete);
  useEffect(() => {
    if (isComplete) onComplete();
  }, [isComplete, onComplete]);

  const states = calls.map((call, index) =>
    spawnedSubagentState(
      call.failed,
      call.isComplete,
      agents[index],
      available && complete
    )
  );
  const counts = new Map<SubagentBucket, number>();
  for (const state of states)
    if (state !== null) {
      const bucket = subagentBucket(state);
      counts.set(bucket, (counts.get(bucket) ?? 0) + 1);
    }
  const summary = BUCKETS.filter((bucket) => counts.has(bucket))
    .map((bucket) => t(`summary.${bucket}`, { count: counts.get(bucket) ?? 0 }))
    .join(" · ");
  const working = agents.filter(
    (agent): agent is ChatSubagent =>
      agent !== undefined && isLiveSubagent(agent)
  );
  const starts = working
    .map(subagentStartedAt)
    .filter((start): start is number => start !== null);
  const groupStart = starts.length > 0 ? Math.min(...starts) : undefined;
  const title = t("title", { count: calls.length });

  return children([
    {
      icon: STEP_ICONS.agent,
      status: title,
      statusKey: "agent-group",
      headerAccessory: (
        <Section flexDirection="row" width="fit" height="fit" gap={0.5}>
          {summary && (
            <Text
              font="secondary-body"
              color={
                counts.has("working")
                  ? "action-selection-05"
                  : counts.has("failed")
                    ? "status-error-05"
                    : "text-03"
              }
              wordWrap="whitespace-nowrap"
            >
              {summary}
            </Text>
          )}
          {working.length > 0 && <Elapsed live startedAt={groupStart} />}
        </Section>
      ),
      supportsCollapsible: true,
      alwaysCollapsible: true,
      timelineLayout: "timeline",
      content: (
        <Section gap={0.25} alignItems="stretch" height="auto">
          {calls.map((call, index) => (
            <SubagentCard
              key={`${index}-${call.name}`}
              name={call.name}
              task={call.message}
              agent={agents[index]}
              state={states[index] ?? null}
            />
          ))}
        </Section>
      ),
    },
  ]);
}

export default AgentGroupRenderer;
