// Adapted from T3 Code (MIT, github.com/pingdotgg/t3code).

import { type ComponentProps, useEffect } from "react";
import { useTranslations } from "next-intl";
import { LineItemButton, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgBranch, SvgChevronRight } from "@opal/icons";
import type { IconProps } from "@opal/types";
import { formatDurationSeconds } from "@opal/time";
import type { CustomToolPacket } from "@/app/app/services/streamingModels";
import type { MessageRenderer } from "@/lib/timeline/chat/message/messageComponents/types";
import { STEP_ICONS } from "@/lib/timeline/icons";
import { openSubagent, useSpawnedSubagents } from "@/lib/chat/subagents";
import type { ChatSubagent } from "@/lib/chat/types";
import { useStreamingDuration } from "@/lib/timeline/useStreamingDuration";
import { agentToolCalls } from "@/lib/timeline/chat/renderers/agent/agentTools";

function isLive(agent: ChatSubagent): boolean {
  return (
    !agent.stopped_by_user &&
    (agent.status === null ||
      agent.status === "running" ||
      agent.status === "suspended")
  );
}

function startOf(agent: ChatSubagent | undefined): number | undefined {
  const parsed = agent?.started_at ? Date.parse(agent.started_at) : NaN;
  return Number.isNaN(parsed) ? undefined : parsed;
}

/** A live agent: the agent glyph with a small blue dot. */
function LiveAgentIcon(props: IconProps) {
  return (
    <span className="relative inline-block">
      <SvgBranch {...props} />
      <span
        aria-hidden
        className="absolute -end-0.5 -top-0.5 size-1.5 rounded-full bg-status-info-05"
      />
    </span>
  );
}

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

interface SpawnedRowProps {
  name: string;
  task: string;
  agent: ChatSubagent | undefined;
}

/** One spawned agent: what it does now, its run time, and its transcript. */
function SpawnedRow({ name, task, agent }: SpawnedRowProps) {
  const t = useTranslations("chat.messages.timeline.agentGroup");
  const live = agent !== undefined && isLive(agent);
  const activity =
    live && agent.activity_tool
      ? t("activity", { tool: agent.activity_tool })
      : task;
  return (
    <LineItemButton
      icon={live ? LiveAgentIcon : SvgBranch}
      title={name}
      titleMaxLines={1}
      description={activity || undefined}
      descriptionMaxLines={1}
      disabled={!agent}
      aria-label={t("open", { name })}
      onClick={agent ? () => openSubagent(agent) : undefined}
      rightChildren={
        <Section flexDirection="row" width="fit" height="fit" gap={0.5}>
          {live && (
            <Text
              font="secondary-body"
              color="action-selection-05"
              wordWrap="whitespace-nowrap"
            >
              {t("running")}
            </Text>
          )}
          {live && <Elapsed live startedAt={startOf(agent)} />}
          {agent && <SvgChevronRight className="size-4 text-text-03" />}
        </Section>
      }
    />
  );
}

/**
 * Agents that one turn spawned together, as T3 Code's subagent card: a count,
 * how many still work, the group's run time, and a row per agent that opens
 * its transcript.
 */
export function AgentGroupRenderer({
  packets,
  onComplete,
  children,
}: ComponentProps<MessageRenderer<CustomToolPacket, {}>>) {
  const t = useTranslations("chat.messages.timeline.agentGroup");
  const calls = agentToolCalls(packets);
  const agents = useSpawnedSubagents(calls.map((call) => call.name));
  const isComplete = calls.every((call) => call.isComplete);
  useEffect(() => {
    if (isComplete) onComplete();
  }, [isComplete, onComplete]);

  const working = agents.filter(
    (agent): agent is ChatSubagent => agent !== undefined && isLive(agent)
  );
  const failed = agents.filter(
    (agent) => agent?.status === "error" || agent?.status === "limit"
  ).length;
  const starts = working
    .map(startOf)
    .filter((start): start is number => start !== undefined);
  const groupStart = starts.length > 0 ? Math.min(...starts) : undefined;
  const title = t("title", { count: calls.length });

  return children([
    {
      icon: STEP_ICONS.agent,
      status: title,
      statusKey: "agent-group",
      headerAccessory: (
        <Section flexDirection="row" width="fit" height="fit" gap={0.5}>
          <Text
            font="secondary-body"
            color={
              working.length > 0
                ? "action-selection-05"
                : failed > 0
                  ? "status-error-05"
                  : "text-03"
            }
            wordWrap="whitespace-nowrap"
          >
            {working.length > 0
              ? t("working", { count: working.length })
              : failed > 0
                ? t("failed", { count: failed })
                : t("done")}
          </Text>
          {working.length > 0 && <Elapsed live startedAt={groupStart} />}
        </Section>
      ),
      supportsCollapsible: true,
      alwaysCollapsible: true,
      timelineLayout: "timeline",
      content: (
        <Section gap={0.25} alignItems="stretch" height="auto">
          {calls.map((call, index) => (
            <SpawnedRow
              key={`${index}-${call.name}`}
              name={call.name}
              task={call.message}
              agent={agents[index]}
            />
          ))}
        </Section>
      ),
    },
  ]);
}

export default AgentGroupRenderer;
