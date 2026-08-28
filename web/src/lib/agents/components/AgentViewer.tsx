"use client";

import { useEffect } from "react";
import { useAgent } from "@/lib/agents/hooks";
import { FetchError } from "@/lib/fetcher";
import { AgentViewerModal } from "@/lib/agents/components";
import { useAppPosition } from "@/lib/app/position";

/** Whether the failure says the agent is absent, rather than unreachable. */
function namesNoAgent(error: unknown): boolean {
  return (
    error instanceof FetchError &&
    (error.status === 403 || error.status === 404)
  );
}

/**
 * The agent viewer, opened by the URL rather than by whichever card was
 * clicked.
 *
 * One instance for the whole listing, because only something holding the
 * position and the agent together can tell that the two disagree. A card
 * cannot: it knows about one agent, so an id naming no agent at all matches
 * nothing and leaves the parameter sitting in the URL with nothing open.
 */
export function AgentViewer() {
  const appPosition = useAppPosition();

  const previewedAgentId = appPosition.previewedAgent();
  const { agent, isLoading, error } = useAgent(previewedAgentId);

  // An id naming nothing the user can open is not a position, so it does not
  // stay in the URL. Replaced rather than pushed: going back should reach
  // wherever the user came from, not the address that named nothing.
  //
  // A request that failed is not the same as an id that names nothing. Only a
  // status saying the agent is not there, or not theirs, retires the position;
  // a timeout or a 500 is left for SWR to retry, so a blip does not discard a
  // link that works.
  const isUnopenable = previewedAgentId !== null && namesNoAgent(error);
  useEffect(() => {
    if (isUnopenable) appPosition.openMoreAgents({ replace: true });
  }, [isUnopenable, appPosition]);

  // Nothing is rendered while the agent loads. The listing stays interactive
  // underneath, and a modal appearing late reads better than an empty one.
  if (previewedAgentId === null || isLoading || agent === null) return null;

  return (
    <AgentViewerModal
      agent={agent}
      onClose={() => appPosition.openMoreAgents()}
    />
  );
}
