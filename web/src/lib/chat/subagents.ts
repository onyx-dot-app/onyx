"use client";

import { createContext } from "react";
import { useNavigation, useSearchParams } from "@opal/navigation";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";
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
 * subagent in its view. A spawn names its agent relative to it.
 */
export const SubagentPathContext = createContext("/root");

/**
 * Whether subagent cards open the subagent in the main view: the chat page's
 * do; the extension's (`NRFPage`) shows no subagent view. Agent status still
 * loads there.
 */
export const SubagentLinksContext = createContext(true);

interface SubagentNavigation {
  /** The subagent that the main view shows, or null for the chat. */
  shownId: string | null;
  /** Shows a subagent of the open chat in the main view. */
  open: (agent: Pick<ChatSubagent, "id">) => void;
  /** Shows the open chat again. */
  openParent: () => void;
}

/** Opens a subagent of the open chat in the main view and goes back. */
export function useSubagentNavigation(): SubagentNavigation {
  const navigation = useNavigation();
  const searchParams = useSearchParams();
  const go = (agentId: string | null) => {
    const params = new URLSearchParams(searchParams?.toString() ?? "");
    if (agentId === null) params.delete(SEARCH_PARAM_NAMES.SUBAGENT_ID);
    else params.set(SEARCH_PARAM_NAMES.SUBAGENT_ID, agentId);
    navigation.go(`?${params.toString()}`, { shallow: true });
  };
  return {
    shownId: searchParams?.get(SEARCH_PARAM_NAMES.SUBAGENT_ID) ?? null,
    open: (agent) => go(agent.id),
    openParent: () => go(null),
  };
}

/** What a subagent's latest run is doing or how it ended. */
export type SubagentState =
  | "starting"
  | "running"
  | "waiting"
  | "completed"
  | "stopped"
  | "failed"
  | "limit";

export function subagentState(agent: ChatSubagent): SubagentState {
  if (agent.stopped_by_user) return "stopped";
  switch (agent.status) {
    case null:
      return "starting";
    case "running":
      return "running";
    case "suspended":
      return "waiting";
    case "complete":
      return "completed";
    case "cancelled":
      return "stopped";
    case "error":
      return "failed";
    case "limit":
      return "limit";
  }
}

/** The summary bucket of a state, as T3 Code's group header counts them. */
export type SubagentBucket = "working" | "done" | "failed" | "stopped";

export function subagentBucket(state: SubagentState): SubagentBucket {
  switch (state) {
    case "starting":
    case "running":
    case "waiting":
      return "working";
    case "completed":
      return "done";
    case "failed":
    case "limit":
      return "failed";
    case "stopped":
      return "stopped";
  }
}
