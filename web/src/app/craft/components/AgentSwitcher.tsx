"use client";

import { useMemo, useState } from "react";
import { Popover, PopoverMenu, Text, LineItemButton } from "@opal/components";
import {
  SvgChevronDown,
  SvgCpu,
  SvgCheckCircle,
  SvgAlertTriangle,
} from "@opal/icons";
import { cn } from "@opal/utils";
import {
  useSubagents,
  useViewedSubagentSessionId,
  useCurrentSessionTitle,
  useBuildSessionStore,
} from "@/app/craft/hooks/useBuildSessionStore";
import type { SubagentState } from "@/app/craft/types/displayTypes";

/** Live-status glyph shown on the right of a menu row. */
function SubagentStatus({ subagent }: { subagent: SubagentState }) {
  return (
    <div className="flex items-center">
      {subagent.status === "running" && (
        <span
          aria-hidden
          className="w-2 h-2 rounded-full bg-action-link-04 animate-pulse shrink-0"
        />
      )}
      {subagent.status === "done" && (
        <SvgCheckCircle className="w-3.5 h-3.5 stroke-status-success-05 shrink-0" />
      )}
      {subagent.status === "failed" && (
        <SvgAlertTriangle className="w-3.5 h-3.5 stroke-status-error-05 shrink-0" />
      )}
    </div>
  );
}

/**
 * AgentSwitcher - The session title rendered as a dropdown that switches the
 * main column between the main agent and any subagent. When a subagent is
 * being viewed, a breadcrumb segment (` / 🗨 name · status`) is appended so the
 * user always knows where they are. The dropdown itself is the way "back" to
 * the main agent — there is no separate back button.
 */
export default function AgentSwitcher() {
  const title = useCurrentSessionTitle();
  const subagents = useSubagents();
  const viewedSubagentSessionId = useViewedSubagentSessionId();
  const viewSubagent = useBuildSessionStore((s) => s.viewSubagent);
  const returnToMainAgent = useBuildSessionStore((s) => s.returnToMainAgent);
  const [open, setOpen] = useState(false);

  const sorted = useMemo(() => {
    return Array.from(subagents.values()).sort((a, b) => {
      const aRunning = a.status === "running";
      const bRunning = b.status === "running";
      if (aRunning !== bRunning) return aRunning ? -1 : 1;
      return b.startedAt - a.startedAt;
    });
  }, [subagents]);

  const isViewingSubagent = viewedSubagentSessionId !== null;
  const viewedSubagent = viewedSubagentSessionId
    ? subagents.get(viewedSubagentSessionId)
    : undefined;
  const hasSubagents = sorted.length > 0;
  // No fallback: a session with no title yet (no message sent) shows nothing.
  const titleLabel = title;

  function selectMainAgent() {
    const sessionId = useBuildSessionStore.getState().currentSessionId;
    if (sessionId) returnToMainAgent(sessionId);
    setOpen(false);
  }

  function selectSubagent(subagentSessionId: string) {
    const sessionId = useBuildSessionStore.getState().currentSessionId;
    if (sessionId) viewSubagent(sessionId, subagentSessionId);
    setOpen(false);
  }

  // The trigger reflects the current selection: the subagent's title when one
  // is being viewed, otherwise the session title (the main agent).
  const triggerLabel =
    isViewingSubagent && viewedSubagent
      ? viewedSubagent.name || viewedSubagent.subagentType || "subagent"
      : titleLabel;

  // Nothing to show (untitled session, not viewing a subagent) — render nothing.
  if (!triggerLabel) return null;

  const labelNode = (
    <span className="flex min-w-0 items-center gap-1.5">
      {isViewingSubagent && (
        <SvgCpu className="w-4 h-4 stroke-text-03 shrink-0" />
      )}
      <Text font="main-ui-action" color="text-04" nowrap>
        {triggerLabel}
      </Text>
      {isViewingSubagent && viewedSubagent && (
        <SubagentStatus subagent={viewedSubagent} />
      )}
    </span>
  );

  if (!hasSubagents) {
    return <span className="truncate px-1.5 py-1">{labelNode}</span>;
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button
          type="button"
          aria-label="Switch agent"
          className={cn(
            "flex items-center gap-1 min-w-0 px-1.5 py-1 rounded-08",
            "transition-colors hover:bg-background-tint-01",
            open && "bg-background-tint-01"
          )}
        >
          <span className="truncate">{labelNode}</span>
          <SvgChevronDown className="w-4 h-4 stroke-text-03 shrink-0" />
        </button>
      </Popover.Trigger>
      <Popover.Content side="bottom" align="start">
        <PopoverMenu>
          {[
            <LineItemButton
              key="main"
              sizePreset="main-ui"
              variant="section"
              state={!isViewingSubagent ? "selected" : "empty"}
              onClick={selectMainAgent}
              title={titleLabel ?? "Main agent"}
            />,
            ...sorted.map((s) => (
              <LineItemButton
                key={s.sessionId}
                sizePreset="main-ui"
                variant="section"
                icon={SvgCpu}
                state={
                  s.sessionId === viewedSubagentSessionId ? "selected" : "empty"
                }
                onClick={() => selectSubagent(s.sessionId)}
                rightChildren={<SubagentStatus subagent={s} />}
                title={s.name || s.subagentType || "subagent"}
              />
            )),
          ]}
        </PopoverMenu>
      </Popover.Content>
    </Popover>
  );
}
