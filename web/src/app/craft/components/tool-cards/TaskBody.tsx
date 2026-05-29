"use client";

import { Text } from "@opal/components";
import {
  SvgCpu,
  SvgArrowRight,
  SvgLoader,
  SvgCheckCircle,
  SvgAlertTriangle,
} from "@opal/icons";
import { cn } from "@opal/utils";
import {
  useSubagents,
  useBuildSessionStore,
} from "@/app/craft/hooks/useBuildSessionStore";
import type { ToolCardBodyProps } from "@/app/craft/components/tool-cards/interfaces";

/**
 * TaskBody - The whole "Spawning subagent: …" row. An accent-tinted, clickable
 * affordance that opens the spawned subagent's transcript, with a live status
 * icon. (Rendered directly by CraftToolCard — no collapsible body.)
 */
export default function TaskBody({ toolCall }: ToolCardBodyProps) {
  const subagents = useSubagents();
  const viewSubagent = useBuildSessionStore((s) => s.viewSubagent);

  const subagent =
    Array.from(subagents.values()).find(
      (s) => s.parentToolCallId === toolCall.id
    ) ?? null;

  const status =
    subagent?.status ??
    (toolCall.status === "completed"
      ? "done"
      : toolCall.status === "failed"
        ? "failed"
        : "running");

  const label = toolCall.description || "Spawning subagent";

  function open() {
    const sessionId = useBuildSessionStore.getState().currentSessionId;
    if (sessionId && subagent) viewSubagent(sessionId, subagent.sessionId);
  }

  return (
    <button
      type="button"
      disabled={!subagent}
      onClick={open}
      aria-label={subagent ? `View subagent: ${label}` : label}
      className={cn(
        "group/task flex w-full items-center gap-2 rounded-08 px-3 py-2 text-left",
        subagent
          ? "cursor-pointer transition-colors hover:bg-background-tint-02"
          : "cursor-default"
      )}
    >
      {/* The accent cpu icon is the one spot of color — it marks this row as a
          delegated subagent you can open, without washing the whole surface. */}
      <SvgCpu className="w-4 h-4 stroke-action-link-05 shrink-0" />
      <span className="min-w-0 flex-1 truncate">
        <Text font="main-ui-action" color="text-04" nowrap>
          {label}
        </Text>
      </span>
      {status === "running" && (
        <SvgLoader className="w-4 h-4 stroke-action-link-05 animate-spin shrink-0" />
      )}
      {status === "done" && (
        <SvgCheckCircle className="w-4 h-4 stroke-status-success-05 shrink-0" />
      )}
      {status === "failed" && (
        <SvgAlertTriangle className="w-4 h-4 stroke-status-error-05 shrink-0" />
      )}
      {subagent && (
        <SvgArrowRight className="w-4 h-4 stroke-text-03 shrink-0 -translate-x-1 opacity-0 transition-all group-hover/task:translate-x-0 group-hover/task:opacity-100" />
      )}
    </button>
  );
}
