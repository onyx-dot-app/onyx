"use client";

// Adapted from T3 Code (MIT, github.com/pingdotgg/t3code).

import { useContext } from "react";
import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgChevronRight } from "@opal/icons";
import { formatDurationSeconds } from "@opal/time";
import { cn } from "@opal/utils";
import {
  isLiveSubagent,
  subagentBucket,
  SubagentLinksContext,
  subagentStartedAt,
  subagentState,
  type SubagentBucket,
  type SubagentState,
  useSubagentNavigation,
} from "@/lib/chat/subagents";
import type { ChatSubagent } from "@/lib/chat/types";
import { STEP_ICONS } from "@/lib/timeline/icons";
import { useStreamingDuration } from "@/lib/timeline/useStreamingDuration";

const DOT_CLASSES = {
  working: "bg-status-info-05",
  done: "bg-status-success-05",
  failed: "bg-status-error-05",
  stopped: "bg-text-03",
} satisfies Record<SubagentBucket, string>;

interface SubagentAvatarProps {
  state: SubagentState | null;
}

/** The agent icon in a circle, with a dot for its state. */
export function SubagentAvatar({ state }: SubagentAvatarProps) {
  const Icon = STEP_ICONS.agent;
  return (
    <Section
      aria-hidden
      width={1.5}
      height={1.5}
      shrink={false}
      gap={0}
      className="relative rounded-full border border-border-01 bg-background-tint-02 ring-2 ring-background-neutral-00"
    >
      <Icon className="size-3.5 text-text-03" />
      {state !== null && (
        <span
          className={cn(
            "absolute -end-px -bottom-px size-2 rounded-full ring-2 ring-background-neutral-00",
            DOT_CLASSES[subagentBucket(state)]
          )}
        />
      )}
    </Section>
  );
}

/**
 * A spawned agent's state. A spawn whose agent the list does not hold yet
 * still starts, unless the list may miss it (`listed` false: the list is
 * full, or there is none, as in a shared chat); then only a spawn call that
 * has not ended still starts.
 */
export function spawnedSubagentState(
  spawnFailed: boolean,
  spawnComplete: boolean,
  agent: ChatSubagent | undefined,
  listed: boolean
): SubagentState | null {
  if (spawnFailed) return "failed";
  if (agent !== undefined) return subagentState(agent);
  return listed || !spawnComplete ? "starting" : null;
}

interface SubagentCardProps {
  name: string;
  // The instructions it was spawned with
  task: string;
  // Null until the chat lists the agent
  agent: ChatSubagent | undefined;
  // Null when unknown, such as an agent the list does not hold
  state: SubagentState | null;
}

/**
 * One subagent, as T3 Code's subagent link: its avatar, name, what it does
 * now, its state and time. It opens the agent in the main view.
 */
export function SubagentCard({ name, task, agent, state }: SubagentCardProps) {
  const t = useTranslations("chat.messages.timeline.agentGroup");
  const tStatus = useTranslations("chat.subagents.status");
  const links = useContext(SubagentLinksContext);
  const { open } = useSubagentNavigation();
  const live = agent !== undefined && isLiveSubagent(agent);
  const startedAt = live ? (subagentStartedAt(agent) ?? undefined) : undefined;
  const elapsed = useStreamingDuration(live, startedAt);
  const failed = state === "failed" || state === "limit";
  const statusLabel = state === null ? null : tStatus(state);
  const detail =
    (live && agent.activity_tool
      ? t("activity", { tool: agent.activity_tool })
      : task.trim()) || null;
  const seconds =
    startedAt !== undefined
      ? Math.max(1, elapsed)
      : !live && agent?.duration_seconds != null
        ? Math.max(1, agent.duration_seconds)
        : null;

  const openable = links && agent !== undefined;
  const content = (
    <Section flexDirection="row" justifyContent="start" gap={2.5} height="fit">
      <SubagentAvatar state={state} />
      <Section
        alignItems="stretch"
        justifyContent="start"
        gap={0}
        width="auto"
        height="fit"
        grow={1}
      >
        <Text font="secondary-action" color="text-05" maxLines={1}>
          {name || t("title", { count: 1 })}
        </Text>
        {(detail ?? statusLabel) !== null && (
          <Text
            font="figure-small-value"
            color={failed ? "status-error-05" : "text-03"}
            maxLines={1}
          >
            {detail ?? statusLabel ?? ""}
          </Text>
        )}
      </Section>
      {detail !== null && statusLabel !== null && state !== "completed" && (
        <Text
          font="secondary-body"
          color={failed ? "status-error-05" : "text-03"}
          wordWrap="whitespace-nowrap"
        >
          {statusLabel}
        </Text>
      )}
      {seconds !== null && (
        // Plain text, so the ticks do not flash
        <Text
          font="secondary-body"
          color="text-03"
          wordWrap="whitespace-nowrap"
        >
          {formatDurationSeconds(seconds)}
        </Text>
      )}
      {openable && (
        <SvgChevronRight
          aria-hidden
          className="size-3.5 shrink-0 text-text-02 transition-colors group-hover/subagent:text-text-05"
        />
      )}
    </Section>
  );
  const className =
    "group/subagent block w-full min-w-0 rounded-08 px-2 py-1.5 text-start";

  if (!links || agent === undefined)
    return (
      <div data-subagent-card className={className}>
        {content}
      </div>
    );
  return (
    // oxlint-disable-next-line react/forbid-elements -- T3 Code's subagent card: a two-line row with an avatar and a trailing state that no Opal button lays out
    <button
      type="button"
      data-subagent-card
      aria-label={t("open", { name })}
      onClick={() => open(agent)}
      className={cn(
        className,
        "cursor-pointer transition-colors hover:bg-background-tint-02 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-border-04"
      )}
    >
      {content}
    </button>
  );
}
