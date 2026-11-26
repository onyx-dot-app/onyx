"use client";

import { createContext } from "react";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import type { ChatSubagent } from "@/lib/chat/types";

/** An agent's name: the last part of its path. */
export function subagentName(path: string): string {
  return path.slice(path.lastIndexOf("/") + 1);
}

/** Whether the agent's latest run still works or waits. */
export function isLiveSubagent(agent: ChatSubagent): boolean {
  return (
    !agent.stopped_by_user &&
    (agent.status === null ||
      agent.status === "running" ||
      agent.status === "suspended")
  );
}

/** When the agent's latest run started, in epoch milliseconds, if known. */
export function subagentStartedAt(agent: ChatSubagent): number | null {
  const parsed = agent.started_at ? Date.parse(agent.started_at) : NaN;
  return Number.isNaN(parsed) ? null : parsed;
}

/**
 * The path of the agent whose conversation renders: the root in the chat, a
 * subagent in its tab. A spawn names its agent relative to it.
 */
export const SubagentPathContext = createContext("/root");

/**
 * Whether the page shows subagent tabs: the chat page's right panel does; the
 * extension's has only Sources, so it opens no agent. Agent status still
 * loads there.
 */
export const SubagentTabsContext = createContext(true);

/** Opens a subagent's transcript in the open chat's right panel. */
export function openSubagent(agent: Pick<ChatSubagent, "id" | "path">): void {
  useChatSessionStore.getState().updateCurrentRightPanel({
    type: "openAgent",
    agentId: agent.id,
    name: subagentName(agent.path),
  });
}
