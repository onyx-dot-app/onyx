"use client";

import { Text } from "@opal/components";
import { SvgBubbleText, SvgArrowRight } from "@opal/icons";
import { cn } from "@opal/utils";
import {
  useSubagents,
  useBuildSessionStore,
} from "@/app/craft/hooks/useBuildSessionStore";
import type { ToolCardBodyProps } from "@/app/craft/components/tool-cards/interfaces";

/**
 * TaskBody - Compact launcher for the task (subagent) tool.
 *
 * Shows the subagent type badge, a one-line label, and the live run status.
 * The subagent's prompt and response live in the side-panel transcript — when
 * the spawned subagent is known, the whole card opens that transcript.
 */
export default function TaskBody({ toolCall }: ToolCardBodyProps) {
  const subagents = useSubagents();
  const openSubagentInPanel = useBuildSessionStore(
    (s) => s.openSubagentInPanel
  );

  const subagent =
    Array.from(subagents.values()).find(
      (s) => s.parentToolCallId === toolCall.id
    ) ?? null;

  const label = subagent?.name || toolCall.description || "";
  const stepCount =
    subagent?.turns.reduce((sum, turn) => sum + turn.toolCalls.length, 0) ?? 0;

  const statusLabel = subagent
    ? subagent.status === "running"
      ? `running · ${stepCount} steps`
      : subagent.status === "done"
        ? `done · ${stepCount} steps`
        : `failed · ${stepCount} steps`
    : null;

  const content = (
    <>
      <div className="flex items-center gap-2">
        <SvgBubbleText className="w-3.5 h-3.5 stroke-text-03 shrink-0" />
        {label && (
          <Text font="main-ui-action" color="text-04" nowrap>
            {label}
          </Text>
        )}
      </div>

      {statusLabel && (
        <Text font="main-ui-muted" color="text-02">
          {statusLabel}
        </Text>
      )}

      {subagent && (
        <div className="flex items-center gap-1">
          <Text font="main-ui-action" color="text-03">
            View transcript
          </Text>
          <SvgArrowRight className="w-3.5 h-3.5 stroke-action-link-05" />
        </div>
      )}
    </>
  );

  if (subagent) {
    return (
      <button
        type="button"
        onClick={() => openSubagentInPanel(subagent.sessionId)}
        aria-label="View subagent transcript"
        className={cn(
          "px-3 py-1 flex flex-col gap-1 w-full text-left rounded-08",
          "transition-colors hover:bg-background-tint-01"
        )}
      >
        {content}
      </button>
    );
  }

  return <div className="px-3 py-1 flex flex-col gap-1">{content}</div>;
}
