"use client";

import { Text } from "@opal/components";
import { SvgBubbleText, SvgCheckCircle, SvgAlertTriangle } from "@opal/icons";
import { cn } from "@opal/utils";
import {
  useActivePanelTabId,
  useBuildSessionStore,
} from "@/app/craft/hooks/useBuildSessionStore";
import { panelTabId, type SubagentState } from "@/app/craft/types/displayTypes";

interface AgentPillProps {
  subagent: SubagentState;
}

export default function AgentPill({ subagent }: AgentPillProps) {
  const activePanelTabId = useActivePanelTabId();
  const openSubagentInPanel = useBuildSessionStore(
    (s) => s.openSubagentInPanel
  );

  const tabId = panelTabId({
    kind: "subagent",
    subagentSessionId: subagent.sessionId,
  });
  const isActive = activePanelTabId === tabId;
  const isRunning = subagent.status === "running";
  const stepCount = subagent.turns.reduce(
    (sum, turn) => sum + turn.toolCalls.length,
    0
  );

  return (
    <button
      type="button"
      onClick={() => openSubagentInPanel(subagent.sessionId)}
      aria-label={`View subagent transcript: ${subagent.name || subagent.subagentType || subagent.sessionId}`}
      className={cn(
        "flex items-center gap-2 px-2 py-1 rounded-08",
        "border transition-colors",
        "hover:bg-background-tint-01",
        isActive
          ? "border-border-03 bg-background-tint-01"
          : "border-border-01 bg-background-neutral-00"
      )}
    >
      <SvgBubbleText className="w-3.5 h-3.5 stroke-text-03 shrink-0" />

      {subagent.name && (
        <span className="truncate max-w-[8rem]">
          <Text font="figure-small-value" color="text-03" nowrap>
            {subagent.name}
          </Text>
        </span>
      )}

      {isRunning && (
        <span
          aria-hidden
          className="w-2 h-2 rounded-full bg-action-link-04 animate-pulse"
        />
      )}
      {subagent.status === "done" && (
        <SvgCheckCircle className="w-3.5 h-3.5 stroke-status-success-05" />
      )}
      {subagent.status === "failed" && (
        <SvgAlertTriangle className="w-3.5 h-3.5 stroke-status-error-05" />
      )}

      <Text font="figure-small-value" color="text-02" nowrap>
        {String(stepCount)}
      </Text>
    </button>
  );
}
