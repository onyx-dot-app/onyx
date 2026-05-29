"use client";

import { Text } from "@opal/components";
import { SvgCpu, SvgArrowRight } from "@opal/icons";
import {
  useSubagents,
  useBuildSessionStore,
} from "@/app/craft/hooks/useBuildSessionStore";
import ToolCardSurface, {
  ToolCardSection,
} from "@/app/craft/components/tool-cards/ToolCardSurface";
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
  const viewSubagent = useBuildSessionStore((s) => s.viewSubagent);

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
        <SvgCpu className="w-3.5 h-3.5 stroke-text-03 shrink-0" />
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
      <ToolCardSurface scroll={false}>
        <button
          type="button"
          onClick={() => {
            const sessionId = useBuildSessionStore.getState().currentSessionId;
            if (sessionId) viewSubagent(sessionId, subagent.sessionId);
          }}
          aria-label="View subagent transcript"
          className="w-full text-left transition-colors hover:bg-background-tint-01"
        >
          <ToolCardSection className="flex flex-col gap-1">
            {content}
          </ToolCardSection>
        </button>
      </ToolCardSurface>
    );
  }

  return (
    <ToolCardSurface scroll={false}>
      <ToolCardSection className="flex flex-col gap-1">
        {content}
      </ToolCardSection>
    </ToolCardSurface>
  );
}
